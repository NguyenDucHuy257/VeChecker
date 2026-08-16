"""Controller for candidate generation, lookup orchestration, and audit writes."""

from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata
from time import perf_counter, sleep
from collections.abc import Callable

from app.models import LookupRepository, LookupStatus
from app.services.errors import (
    ErrorCode,
    InvalidPlateError,
    VehicleNotFoundError,
    VrServiceError,
)
from app.services.vr_parser import VehicleResult
from app.services.webforms_client import WebFormsClient


_PLATE_PATTERN = re.compile(
    r"^(?P<province>[0-9]{2})(?P<series>[A-Z]{1,2})"
    r"(?P<number>[0-9]{5})(?P<suffix>[TXV])?$"
)


@dataclass(frozen=True, slots=True)
class CandidateResult:
    lookup_id: int
    queried_plate: str
    status: LookupStatus
    vehicle: VehicleResult | None = None
    error_code: str | None = None
    duration_ms: int = 0


@dataclass(frozen=True, slots=True)
class LookupRunResult:
    input_plate: str
    attempts: tuple[CandidateResult, ...]

    @property
    def successes(self) -> tuple[CandidateResult, ...]:
        return tuple(item for item in self.attempts if item.status is LookupStatus.SUCCESS)

    @property
    def status(self) -> LookupStatus:
        if self.successes:
            return LookupStatus.SUCCESS
        statuses = {item.status for item in self.attempts}
        if LookupStatus.ERROR in statuses:
            return LookupStatus.ERROR
        if statuses == {LookupStatus.INVALID}:
            return LookupStatus.INVALID
        return LookupStatus.NOT_FOUND


class LookupController:
    def __init__(
        self,
        client: WebFormsClient,
        repository: LookupRepository,
        *,
        user_id: int | None = None,
        candidate_delay_seconds: float = 0.0,
        sleep_func: Callable[[float], None] = sleep,
    ) -> None:
        if candidate_delay_seconds < 0:
            raise ValueError("candidate_delay_seconds cannot be negative")
        self.client = client
        self.repository = repository
        self.user_id = user_id
        self.candidate_delay_seconds = candidate_delay_seconds
        self._sleep = sleep_func

    @staticmethod
    def normalize_plate(value: str) -> str:
        normalized = unicodedata.normalize("NFKC", value).upper()
        normalized = "".join(
            character
            for character in normalized
            if not (
                character.isspace()
                or character in {"-", "."}
                or unicodedata.category(character) == "Cf"
            )
        )
        if not normalized:
            raise InvalidPlateError("Biển số không được để trống.")
        return normalized

    @classmethod
    def create_candidates(cls, value: str) -> tuple[str, ...]:
        normalized = cls.normalize_plate(value)
        match = _PLATE_PATTERN.fullmatch(normalized)
        if match is None:
            raise InvalidPlateError(
                "Biển số phải có dạng 2 số, 1-2 chữ, 5 số và có thể kèm đuôi T/X/V."
            )
        if match.group("suffix") is not None:
            return (normalized,)
        if match.group("series") in {"KT", "LD"}:
            return (normalized,)
        return (
            f"{normalized}T",
            f"{normalized}X",
            f"{normalized}V",
        )

    @staticmethod
    def is_valid_plate(value: str) -> bool:
        return _PLATE_PATTERN.fullmatch(value) is not None

    def lookup(self, input_plate: str) -> LookupRunResult:
        normalized = self.normalize_plate(input_plate)
        if not self.is_valid_plate(normalized):
            return self._record_local_invalid(normalized)
        results: list[CandidateResult] = []

        for candidate_index, candidate in enumerate(self.create_candidates(normalized)):
            if candidate_index and self.candidate_delay_seconds:
                self._sleep(self.candidate_delay_seconds)
            row = self.repository.create(
                user_id=self.user_id,
                input_plate=normalized,
                queried_plate=candidate,
            )
            self.repository.mark_running(row.id)
            started = perf_counter()
            try:
                result = self._lookup_one(row.id, candidate, started)
            except Exception:
                self._finish_unexpected(row.id, started)
                raise
            results.append(result)

        return LookupRunResult(normalized, tuple(results))

    def _record_local_invalid(self, normalized: str) -> LookupRunResult:
        row = self.repository.create(
            user_id=self.user_id,
            input_plate=normalized,
            queried_plate=normalized,
        )
        self.repository.mark_running(row.id)
        saved = self.repository.finish(
            row.id,
            status=LookupStatus.INVALID,
            error_code=ErrorCode.INVALID_PLATE.value,
            duration_ms=0,
        )
        attempt = CandidateResult(
            saved.id,
            normalized,
            saved.status,
            error_code=saved.error_code,
            duration_ms=0,
        )
        return LookupRunResult(normalized, (attempt,))

    def _lookup_one(
        self,
        lookup_id: int,
        candidate: str,
        started: float,
    ) -> CandidateResult:
        try:
            vehicle = self.client.lookup_candidate(candidate)
        except InvalidPlateError as exc:
            status = LookupStatus.INVALID
            error_code = exc.code.value
        except VehicleNotFoundError as exc:
            status = LookupStatus.NOT_FOUND
            error_code = exc.code.value
        except VrServiceError as exc:
            duration = self._duration_ms(started)
            self.repository.finish(
                lookup_id,
                status=LookupStatus.ERROR,
                error_code=exc.code.value,
                duration_ms=duration,
            )
            raise
        else:
            duration = self._duration_ms(started)
            saved = self.repository.finish(
                lookup_id,
                status=LookupStatus.SUCCESS,
                vehicle_type=vehicle.vehicle_type,
                brand=vehicle.brand,
                inspection_expiry=vehicle.inspection_expiry,
                duration_ms=duration,
            )
            return CandidateResult(
                saved.id,
                candidate,
                saved.status,
                vehicle=vehicle,
                duration_ms=duration,
            )

        duration = self._duration_ms(started)
        saved = self.repository.finish(
            lookup_id,
            status=status,
            error_code=error_code,
            duration_ms=duration,
        )
        return CandidateResult(
            saved.id,
            candidate,
            saved.status,
            error_code=saved.error_code,
            duration_ms=duration,
        )

    def _finish_unexpected(self, lookup_id: int, started: float) -> None:
        """Best-effort guard against RUNNING rows after an unexpected code error."""

        try:
            current = self.repository.get(lookup_id)
            if current is None or current.status not in {
                LookupStatus.QUEUED,
                LookupStatus.RUNNING,
            }:
                return
            self.repository.finish(
                lookup_id,
                status=LookupStatus.ERROR,
                error_code=ErrorCode.SOURCE_ERROR.value,
                duration_ms=self._duration_ms(started),
            )
        except Exception:
            # If the database itself is unavailable, Phase 3 startup recovery owns
            # the stale row. Never replace the original application exception.
            return

    @staticmethod
    def _duration_ms(started: float) -> int:
        return max(0, round((perf_counter() - started) * 1_000))
