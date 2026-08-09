"""Vehicle lookup model and SQLite repository."""

from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from typing import TYPE_CHECKING, Mapping, Any

if TYPE_CHECKING:
    from app.database import Database


class LookupStatus(str, Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    INVALID = "INVALID"
    NOT_FOUND = "NOT_FOUND"
    ERROR = "ERROR"


TERMINAL_LOOKUP_STATUSES = frozenset(
    {
        LookupStatus.SUCCESS,
        LookupStatus.INVALID,
        LookupStatus.NOT_FOUND,
        LookupStatus.ERROR,
    }
)


def _parse_datetime(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


@dataclass(frozen=True, slots=True)
class Lookup:
    id: int
    user_id: int | None
    input_plate: str
    queried_plate: str
    status: LookupStatus
    vehicle_type: str | None
    brand: str | None
    inspection_expiry: date | None
    error_code: str | None
    duration_ms: int | None
    created_at: datetime
    finished_at: datetime | None

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "Lookup":
        expiry = row["inspection_expiry"]
        return cls(
            id=int(row["id"]),
            user_id=row["user_id"],
            input_plate=row["input_plate"],
            queried_plate=row["queried_plate"],
            status=LookupStatus(row["status"]),
            vehicle_type=row["vehicle_type"],
            brand=row["brand"],
            inspection_expiry=date.fromisoformat(expiry) if expiry else None,
            error_code=row["error_code"],
            duration_ms=row["duration_ms"],
            created_at=_parse_datetime(row["created_at"]),  # type: ignore[arg-type]
            finished_at=_parse_datetime(row["finished_at"]),
        )


class LookupRepository:
    def __init__(self, database: "Database") -> None:
        self._database = database

    def get(self, lookup_id: int) -> Lookup | None:
        with closing(self._database.connect()) as connection:
            row = connection.execute("SELECT * FROM lookups WHERE id = ?", (lookup_id,)).fetchone()
        return Lookup.from_row(row) if row is not None else None

    def list_all(self) -> list[Lookup]:
        with closing(self._database.connect()) as connection:
            rows = connection.execute("SELECT * FROM lookups ORDER BY id").fetchall()
        return [Lookup.from_row(row) for row in rows]

    def create(
        self,
        *,
        user_id: int | None,
        input_plate: str,
        queried_plate: str,
        status: LookupStatus = LookupStatus.QUEUED,
    ) -> Lookup:
        input_plate = _required_text(input_plate, "input_plate")
        queried_plate = _required_text(queried_plate, "queried_plate")
        status = LookupStatus(status)
        if status in TERMINAL_LOOKUP_STATUSES:
            raise ValueError("Use finish() to create a terminal lookup result")

        with self._database.transaction() as connection:
            cursor = connection.execute(
                """
                INSERT INTO lookups (user_id, input_plate, queried_plate, status)
                VALUES (?, ?, ?, ?)
                """,
                (user_id, input_plate, queried_plate, status.value),
            )
            lookup_id = int(cursor.lastrowid)
            row = connection.execute("SELECT * FROM lookups WHERE id = ?", (lookup_id,)).fetchone()
        assert row is not None
        return Lookup.from_row(row)

    def mark_running(self, lookup_id: int) -> Lookup:
        with self._database.transaction() as connection:
            cursor = connection.execute(
                "UPDATE lookups SET status = 'RUNNING' WHERE id = ? AND status = 'QUEUED'",
                (lookup_id,),
            )
            if cursor.rowcount != 1:
                raise ValueError("Lookup does not exist or is not QUEUED")
            row = connection.execute("SELECT * FROM lookups WHERE id = ?", (lookup_id,)).fetchone()
        assert row is not None
        return Lookup.from_row(row)

    def finish(
        self,
        lookup_id: int,
        *,
        status: LookupStatus,
        vehicle_type: str | None = None,
        brand: str | None = None,
        inspection_expiry: date | None = None,
        error_code: str | None = None,
        duration_ms: int | None = None,
    ) -> Lookup:
        status = LookupStatus(status)
        if status not in TERMINAL_LOOKUP_STATUSES:
            raise ValueError("finish() requires a terminal status")
        if duration_ms is not None and duration_ms < 0:
            raise ValueError("duration_ms cannot be negative")

        if status is LookupStatus.SUCCESS:
            vehicle_type = _required_text(vehicle_type, "vehicle_type")
            brand = _required_text(brand, "brand")
            if inspection_expiry is None:
                raise ValueError("inspection_expiry is required for SUCCESS")
            error_code = None
        else:
            vehicle_type = None
            brand = None
            inspection_expiry = None

        with self._database.transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE lookups SET
                    status = ?,
                    vehicle_type = ?,
                    brand = ?,
                    inspection_expiry = ?,
                    error_code = ?,
                    duration_ms = ?,
                    finished_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                WHERE id = ? AND status IN ('QUEUED', 'RUNNING')
                """,
                (
                    status.value,
                    vehicle_type,
                    brand,
                    inspection_expiry.isoformat() if inspection_expiry else None,
                    error_code,
                    duration_ms,
                    lookup_id,
                ),
            )
            if cursor.rowcount != 1:
                raise ValueError("Lookup does not exist or is already finished")
            row = connection.execute("SELECT * FROM lookups WHERE id = ?", (lookup_id,)).fetchone()
        assert row is not None
        return Lookup.from_row(row)


def _required_text(value: str | None, field_name: str) -> str:
    if value is None or not value.strip():
        raise ValueError(f"{field_name} is required")
    return value.strip()
