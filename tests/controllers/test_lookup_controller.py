from datetime import date

import pytest

from app.controllers.lookup_controller import LookupController
from app.database import Database
from app.models import LookupRepository, LookupStatus
from app.services.errors import (
    InvalidPlateError,
    SourceTimeoutError,
    VehicleNotFoundError,
)
from app.services.vr_parser import VehicleResult


VEHICLE_T = VehicleResult("Xe tải thử nghiệm", "NHÃN HIỆU T", date(2030, 1, 2))
VEHICLE_V = VehicleResult("Xe khách thử nghiệm", "NHÃN HIỆU V", date(2031, 3, 4))


class FakeClient:
    def __init__(self, outcomes) -> None:
        self.outcomes = list(outcomes)
        self.plates: list[str] = []

    def lookup_candidate(self, plate):
        self.plates.append(plate)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def controller(tmp_path, client):
    database = Database(tmp_path / "test.sqlite3")
    database.initialize()
    repository = LookupRepository(database)
    return LookupController(client, repository), repository


def test_candidate_generation() -> None:
    assert LookupController.create_candidates(" 00a00000 ") == (
        "00A00000T",
        "00A00000V",
    )
    assert LookupController.create_candidates("00a00000t") == ("00A00000T",)
    assert LookupController.create_candidates("00a00000V") == ("00A00000V",)
    with pytest.raises(InvalidPlateError):
        LookupController.create_candidates("   ")


@pytest.mark.parametrize(
    "value",
    [
        "37ABCD12",
        "37A1234567",
        "37A12-345",
        "37A12345X",
        "ABC",
    ],
)
def test_candidate_generation_rejects_unproven_formats(value) -> None:
    with pytest.raises(InvalidPlateError):
        LookupController.create_candidates(value)


def test_base_plate_runs_both_candidates_and_returns_success(tmp_path) -> None:
    fake = FakeClient([VEHICLE_T, VehicleNotFoundError()])
    lookup, repository = controller(tmp_path, fake)

    result = lookup.lookup("00a00000")

    assert fake.plates == ["00A00000T", "00A00000V"]
    assert result.status is LookupStatus.SUCCESS
    assert [item.queried_plate for item in result.successes] == ["00A00000T"]
    rows = repository.list_all()
    assert [row.status for row in rows] == [LookupStatus.SUCCESS, LookupStatus.NOT_FOUND]


def test_suffixed_plate_runs_once(tmp_path) -> None:
    fake = FakeClient([VEHICLE_V])
    lookup, repository = controller(tmp_path, fake)

    result = lookup.lookup("00a00000v")

    assert fake.plates == ["00A00000V"]
    assert len(result.successes) == 1
    assert len(repository.list_all()) == 1


def test_both_candidates_can_return_data(tmp_path) -> None:
    fake = FakeClient([VEHICLE_T, VEHICLE_V])
    lookup, _ = controller(tmp_path, fake)

    result = lookup.lookup("00a00000")

    assert len(result.successes) == 2


def test_base_plate_waits_between_source_candidates(tmp_path) -> None:
    database = Database(tmp_path / "delay.sqlite3")
    database.initialize()
    delays: list[float] = []
    fake = FakeClient([VEHICLE_T, VEHICLE_V])
    lookup = LookupController(
        fake,
        LookupRepository(database),
        candidate_delay_seconds=2.0,
        sleep_func=delays.append,
    )

    lookup.lookup("00a00000")

    assert delays == [2.0]


def test_local_invalid_returns_invalid_without_calling_source(tmp_path) -> None:
    fake = FakeClient([])
    lookup, repository = controller(tmp_path, fake)

    result = lookup.lookup("37ABCD12")

    assert result.status is LookupStatus.INVALID
    assert fake.plates == []
    rows = repository.list_all()
    assert len(rows) == 1
    assert rows[0].status is LookupStatus.INVALID
    assert rows[0].error_code == "INVALID_PLATE"


def test_source_can_still_reject_valid_shaped_candidates(tmp_path) -> None:
    fake = FakeClient([InvalidPlateError(), InvalidPlateError()])
    lookup, _ = controller(tmp_path, fake)

    result = lookup.lookup("00A00000")

    assert result.status is LookupStatus.INVALID
    assert fake.plates == ["00A00000T", "00A00000V"]


def test_source_failure_is_recorded_and_raised(tmp_path) -> None:
    fake = FakeClient([SourceTimeoutError()])
    lookup, repository = controller(tmp_path, fake)

    with pytest.raises(SourceTimeoutError):
        lookup.lookup("00a00000t")

    row = repository.list_all()[0]
    assert row.status is LookupStatus.ERROR
    assert row.error_code == "SOURCE_TIMEOUT"


@pytest.mark.parametrize("outcome", [ValueError("bug"), object()])
def test_unexpected_failure_does_not_leave_running_row(tmp_path, outcome) -> None:
    fake = FakeClient([outcome])
    lookup, repository = controller(tmp_path, fake)

    with pytest.raises((ValueError, AttributeError)):
        lookup.lookup("00a00000t")

    row = repository.list_all()[0]
    assert row.status is LookupStatus.ERROR
    assert row.error_code == "SOURCE_ERROR"
