import sqlite3

import pytest

from app.database import Database
from app.models.user import UserRepository, UserRole, UserStatus


def test_user_telegram_id_is_unique(tmp_path):
    database = Database(tmp_path / "test.sqlite3")
    database.initialize()
    repository = UserRepository(database)
    repository.create(1001)

    with pytest.raises(sqlite3.IntegrityError):
        repository.create(1001)


def test_seed_admin_promotes_existing_user(tmp_path):
    database = Database(tmp_path / "test.sqlite3")
    database.initialize()
    repository = UserRepository(database)
    original = repository.create(1001, status=UserStatus.BLOCKED)

    admins = repository.seed_admins([1001])

    assert admins[0].id == original.id
    assert admins[0].role is UserRole.ADMIN
    assert admins[0].status is UserStatus.ACTIVE


def test_get_or_create_pending_and_update_status(tmp_path):
    database = Database(tmp_path / "pending.sqlite3")
    database.initialize()
    repository = UserRepository(database)

    user, created = repository.get_or_create_pending(
        5001,
        telegram_username="first_name",
    )
    same, created_again = repository.get_or_create_pending(
        5001,
        telegram_username="updated_name",
    )
    active = repository.update_status(5001, UserStatus.ACTIVE)

    assert created is True
    assert created_again is False
    assert same.id == user.id
    assert same.telegram_username == "updated_name"
    assert active.status is UserStatus.ACTIVE


def test_count_active_admins(tmp_path):
    database = Database(tmp_path / "admins.sqlite3")
    database.initialize()
    repository = UserRepository(database)
    repository.seed_admins([1001, 1002])
    repository.update_status(1002, UserStatus.BLOCKED)

    assert repository.count_active_admins() == 1
