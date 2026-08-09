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
        return UserRepository(self).seed_admins(list(telegram_admin_ids))
