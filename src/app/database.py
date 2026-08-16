"""SQLite connection, migration, and startup helpers."""

from __future__ import annotations

from contextlib import closing, contextmanager
from pathlib import Path
import sqlite3
from collections.abc import Iterator, Sequence

from app.migrations import MIGRATIONS
from app.models.user import User, UserRepository


class Database:
    def __init__(self, path: str | Path, *, busy_timeout_ms: int = 5_000) -> None:
        self.path = Path(path)
        if busy_timeout_ms <= 0:
            raise ValueError("busy_timeout_ms must be greater than zero")
        self.busy_timeout_ms = busy_timeout_ms

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=self.busy_timeout_ms / 1_000)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(f"PRAGMA busy_timeout = {self.busy_timeout_ms}")
        return connection

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            connection.execute("BEGIN")
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def migrate(self) -> int:
        with closing(self.connect()) as connection:
            current_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            latest_version = MIGRATIONS[-1].version if MIGRATIONS else 0
            if current_version > latest_version:
                raise RuntimeError(
                    f"Database schema version {current_version} is newer than supported {latest_version}"
                )
            for migration in MIGRATIONS:
                if migration.version > current_version:
                    connection.executescript(migration.read_sql())
                    applied_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
                    if applied_version != migration.version:
                        raise RuntimeError(
                            f"Migration {migration.filename} did not set user_version={migration.version}"
                        )
                    current_version = applied_version
        return current_version

    def initialize(self, telegram_admin_ids: Sequence[int] = ()) -> list[User]:
        """Apply migrations and idempotently bootstrap configured admins."""

        self.migrate()
        self.recover_incomplete_work()
        return UserRepository(self).seed_admins(list(telegram_admin_ids))

    def recover_incomplete_work(self) -> tuple[int, int]:
        """Fail work that cannot safely resume after a process restart."""

        with self.transaction() as connection:
            lookups = connection.execute(
                """
                UPDATE lookups SET
                    status = 'ERROR', error_code = 'SOURCE_ERROR',
                    finished_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                WHERE status IN ('QUEUED', 'RUNNING')
                """
            ).rowcount
            updates = connection.execute(
                """
                UPDATE telegram_updates SET
                    state = 'FAILED', error_code = 'SOURCE_ERROR',
                    finished_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                WHERE state = 'ACCEPTED'
                """
            ).rowcount
        return int(lookups), int(updates)

    def backup(self, destination: str | Path) -> Path:
        """Create a consistent online SQLite backup and verify its integrity."""

        target = Path(destination)
        self._validate_copy_paths(self.path, target)
        if not self.path.is_file():
            raise FileNotFoundError(f"Database does not exist: {self.path}")
        target.parent.mkdir(parents=True, exist_ok=True)
        with closing(self.connect()) as source, closing(sqlite3.connect(target)) as output:
            source.backup(output)
            if output.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("Backup SQLite failed integrity_check")
        return target.resolve()

    def restore(self, source: str | Path) -> Path:
        """Restore this database from a verified SQLite backup."""

        backup_path = Path(source)
        self._validate_copy_paths(backup_path, self.path)
        if not backup_path.is_file():
            raise FileNotFoundError(f"Backup does not exist: {backup_path}")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(backup_path)) as backup_connection:
            if backup_connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("Backup SQLite failed integrity_check")
            with closing(self.connect()) as destination:
                backup_connection.backup(destination)
        return self.path.resolve()

    @staticmethod
    def _validate_copy_paths(source: Path, destination: Path) -> None:
        if source.expanduser().resolve() == destination.expanduser().resolve():
            raise ValueError("SQLite source and destination must be different files")
