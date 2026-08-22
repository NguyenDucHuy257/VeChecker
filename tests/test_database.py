from contextlib import closing
import sqlite3

from app.database import Database
from app.models.user import UserRole, UserStatus
from app.models import LookupRepository, LookupStatus, TelegramUpdateRepository
from app.migrations import MIGRATIONS


def test_migration_creates_phase_three_schema_and_is_idempotent(tmp_path):
    database = Database(tmp_path / "nested" / "test.sqlite3")

    assert database.migrate() == 3
    assert database.migrate() == 3

    with closing(database.connect()) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            )
        }
    assert tables == {"users", "lookups", "telegram_updates"}


def test_phase_three_db_trigger_rejects_inconsistent_lookup_atomically(tmp_path):
    database = Database(tmp_path / "constraints.sqlite3")
    database.initialize()

    try:
        with database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO lookups (
                    input_plate, queried_plate, status, vehicle_type, brand,
                    inspection_expiry, finished_at
                ) VALUES ('00A00000', '00A00000T', 'SUCCESS', NULL, 'BRAND',
                          '2030-01-01', strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
                """
            )
    except Exception as exc:
        assert "invalid lookup state" in str(exc)
    else:
        raise AssertionError("inconsistent SUCCESS row must fail")

    with closing(database.connect()) as connection:
        assert connection.execute("SELECT COUNT(*) FROM lookups").fetchone()[0] == 0


def test_phase_two_database_migrates_to_v3_without_losing_data(tmp_path):
    path = tmp_path / "phase2.sqlite3"
    with closing(sqlite3.connect(path)) as connection:
        connection.executescript(MIGRATIONS[0].read_sql())
        connection.executescript(MIGRATIONS[1].read_sql())
        connection.execute(
            "INSERT INTO users (telegram_user_id, role, status) VALUES (7, 'USER', 'ACTIVE')"
        )
        connection.commit()

    database = Database(path)

    assert database.migrate() == 3
    with closing(database.connect()) as connection:
        assert connection.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 1
        triggers = connection.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type = 'trigger'"
        ).fetchone()[0]
    assert triggers == 4


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


def test_initialize_recovers_incomplete_work_after_restart(tmp_path):
    database = Database(tmp_path / "restart.sqlite3")
    database.initialize()
    lookups = LookupRepository(database)
    updates = TelegramUpdateRepository(database)
    queued = lookups.create(user_id=None, input_plate="00A00000", queried_plate="00A00000T")
    running = lookups.create(user_id=None, input_plate="00A00000", queried_plate="00A00000V")
    lookups.mark_running(running.id)
    assert updates.reserve(10, 1001, 1001)

    database.initialize()

    assert lookups.get(queued.id).status is LookupStatus.ERROR
    assert lookups.get(running.id).status is LookupStatus.ERROR
    assert lookups.get(queued.id).error_code == "SOURCE_ERROR"
    assert updates.get(10).state.value == "FAILED"
    assert updates.get(10).error_code == "SOURCE_ERROR"


def test_sqlite_backup_and_restore_round_trip(tmp_path):
    database = Database(tmp_path / "live.sqlite3")
    database.initialize([1001])
    backup = database.backup(tmp_path / "backups" / "snapshot.sqlite3")

    with database.transaction() as connection:
        connection.execute("DELETE FROM users")
    database.restore(backup)

    with closing(database.connect()) as connection:
        admin_count = connection.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
    assert admin_count == 1
    assert integrity == "ok"


def test_backup_rejects_same_source_and_destination(tmp_path):
    database = Database(tmp_path / "same.sqlite3")
    database.initialize()

    try:
        database.backup(database.path)
    except ValueError as exc:
        assert "different" in str(exc)
    else:
        raise AssertionError("same-path backup must fail")
