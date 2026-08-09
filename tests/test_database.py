from contextlib import closing

from app.database import Database
from app.models.user import UserRole, UserStatus


def test_migration_creates_two_business_tables_and_is_idempotent(tmp_path):
    database = Database(tmp_path / "nested" / "test.sqlite3")

    assert database.migrate() == 1
    assert database.migrate() == 1

    with closing(database.connect()) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            )
        }
    assert tables == {"users", "lookups"}


def test_initialize_seeds_admins_idempotently(tmp_path):
    database = Database(tmp_path / "test.sqlite3")

    first = database.initialize([1001, 1002])
    second = database.initialize([1001, 1002])

    assert [user.id for user in first] == [user.id for user in second]
    assert len(second) == 2
    assert all(user.role is UserRole.ADMIN for user in second)
    assert all(user.status is UserStatus.ACTIVE for user in second)


def test_transaction_rolls_back_on_error(tmp_path):
    database = Database(tmp_path / "test.sqlite3")
    database.initialize()

    try:
        with database.transaction() as connection:
            connection.execute(
                "INSERT INTO users (telegram_user_id, role, status) VALUES (1, 'USER', 'PENDING')"
            )
            raise RuntimeError("stop")
    except RuntimeError:
        pass

    with closing(database.connect()) as connection:
        count = connection.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    assert count == 0
