from datetime import date

import pytest

from app.database import Database
from app.models.lookup import LookupRepository, LookupStatus


def test_success_requires_and_persists_all_three_result_fields(tmp_path):
    database = Database(tmp_path / "test.sqlite3")
    database.initialize()
    repository = LookupRepository(database)

    pending = repository.create(
        user_id=None,
        input_plate="30A12345",
        queried_plate="30A12345T",
    )
    running = repository.mark_running(pending.id)
    result = repository.finish(
        running.id,
        status=LookupStatus.SUCCESS,
        vehicle_type="Ô tô con",
        brand="TOYOTA",
        inspection_expiry=date(2027, 8, 8),
        duration_ms=123,
    )

    assert result.status is LookupStatus.SUCCESS
    assert result.input_plate == "30A12345"
    assert result.queried_plate == "30A12345T"
    assert result.vehicle_type == "Ô tô con"
    assert result.brand == "TOYOTA"
    assert result.inspection_expiry == date(2027, 8, 8)
    assert result.finished_at is not None


def test_success_rejects_missing_required_result(tmp_path):
    database = Database(tmp_path / "test.sqlite3")
    database.initialize()
    repository = LookupRepository(database)
    lookup = repository.create(user_id=None, input_plate="A", queried_plate="AT")

    with pytest.raises(ValueError, match="brand"):
        repository.finish(
            lookup.id,
            status=LookupStatus.SUCCESS,
            vehicle_type="Ô tô",
            brand=" ",
            inspection_expiry=date(2027, 1, 1),
        )


def test_non_success_does_not_store_vehicle_result(tmp_path):
    database = Database(tmp_path / "test.sqlite3")
    database.initialize()
    repository = LookupRepository(database)
    lookup = repository.create(user_id=None, input_plate="BAD", queried_plate="BADT")

    result = repository.finish(
        lookup.id,
        status=LookupStatus.INVALID,
        vehicle_type="must not persist",
        brand="must not persist",
        inspection_expiry=date(2027, 1, 1),
        error_code="INVALID_PLATE",
        duration_ms=5,
    )

    assert result.status is LookupStatus.INVALID
    assert result.vehicle_type is None
    assert result.brand is None
    assert result.inspection_expiry is None
    assert result.error_code == "INVALID_PLATE"
