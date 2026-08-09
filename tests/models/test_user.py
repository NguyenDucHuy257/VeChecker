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
