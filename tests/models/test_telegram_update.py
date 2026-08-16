import pytest

from app.database import Database
from app.models import TelegramUpdateRepository, TelegramUpdateState


def make_repository(tmp_path):
    database = Database(tmp_path / "updates.sqlite3")
    database.initialize()
    return TelegramUpdateRepository(database)


def test_reserve_is_idempotent_and_finish_is_terminal(tmp_path) -> None:
    repository = make_repository(tmp_path)

    assert repository.reserve(10, 1001, 1001) is True
    assert repository.reserve(10, 1001, 1001) is False
    finished = repository.finish(10, TelegramUpdateState.COMPLETED)

    assert finished.state is TelegramUpdateState.COMPLETED
    with pytest.raises(ValueError):
        repository.finish(10, TelegramUpdateState.FAILED)


def test_release_allows_busy_update_to_be_retried(tmp_path) -> None:
    repository = make_repository(tmp_path)

    assert repository.reserve(11, 1002, 1002) is True
    repository.release(11)

    assert repository.get(11) is None
    assert repository.reserve(11, 1002, 1002) is True
