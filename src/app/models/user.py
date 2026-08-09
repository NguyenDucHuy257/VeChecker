"""User model and SQLite repository."""

from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import sqlite3
from typing import TYPE_CHECKING, Mapping, Any

if TYPE_CHECKING:
    from app.database import Database


class UserRole(str, Enum):
    ADMIN = "ADMIN"
    USER = "USER"


class UserStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    BLOCKED = "BLOCKED"


def _parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


@dataclass(frozen=True, slots=True)
class User:
    id: int
    telegram_user_id: int
    telegram_username: str | None
    role: UserRole
    status: UserStatus
    created_by: int | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "User":
        return cls(
            id=int(row["id"]),
            telegram_user_id=int(row["telegram_user_id"]),
            telegram_username=row["telegram_username"],
            role=UserRole(row["role"]),
            status=UserStatus(row["status"]),
            created_by=row["created_by"],
            created_at=_parse_datetime(row["created_at"]),
            updated_at=_parse_datetime(row["updated_at"]),
        )


class UserRepository:
    def __init__(self, database: "Database") -> None:
        self._database = database

    def get(self, user_id: int) -> User | None:
        with closing(self._database.connect()) as connection:
            row = connection.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return User.from_row(row) if row is not None else None

    def get_by_telegram_id(self, telegram_user_id: int) -> User | None:
        with closing(self._database.connect()) as connection:
            row = connection.execute(
                "SELECT * FROM users WHERE telegram_user_id = ?",
                (telegram_user_id,),
            ).fetchone()
        return User.from_row(row) if row is not None else None

    def list_all(self) -> list[User]:
        with closing(self._database.connect()) as connection:
            rows = connection.execute("SELECT * FROM users ORDER BY id").fetchall()
        return [User.from_row(row) for row in rows]

    def create(
        self,
        telegram_user_id: int,
        *,
        telegram_username: str | None = None,
        role: UserRole = UserRole.USER,
        status: UserStatus = UserStatus.PENDING,
        created_by: int | None = None,
    ) -> User:
        _validate_telegram_user_id(telegram_user_id)
        role = UserRole(role)
        status = UserStatus(status)
        with self._database.transaction() as connection:
            cursor = connection.execute(
                """
                INSERT INTO users (
                    telegram_user_id, telegram_username, role, status, created_by
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (telegram_user_id, telegram_username, role.value, status.value, created_by),
            )
            user_id = int(cursor.lastrowid)
            row = connection.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        assert row is not None
        return User.from_row(row)

    def upsert_admin(self, telegram_user_id: int) -> User:
        _validate_telegram_user_id(telegram_user_id)
        with self._database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO users (telegram_user_id, role, status)
                VALUES (?, 'ADMIN', 'ACTIVE')
                ON CONFLICT(telegram_user_id) DO UPDATE SET
                    role = 'ADMIN',
                    status = 'ACTIVE',
                    updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                """,
                (telegram_user_id,),
            )
            row = connection.execute(
                "SELECT * FROM users WHERE telegram_user_id = ?",
                (telegram_user_id,),
            ).fetchone()
        assert row is not None
        return User.from_row(row)

    def seed_admins(self, telegram_user_ids: tuple[int, ...] | list[int]) -> list[User]:
        unique_ids = tuple(dict.fromkeys(telegram_user_ids))
        for telegram_user_id in unique_ids:
            _validate_telegram_user_id(telegram_user_id)

        with self._database.transaction() as connection:
            for telegram_user_id in unique_ids:
                connection.execute(
                    """
                    INSERT INTO users (telegram_user_id, role, status)
                    VALUES (?, 'ADMIN', 'ACTIVE')
                    ON CONFLICT(telegram_user_id) DO UPDATE SET
                        role = 'ADMIN',
                        status = 'ACTIVE',
                        updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                    """,
                    (telegram_user_id,),
                )
            if not unique_ids:
                rows: list[sqlite3.Row] = []
            else:
                placeholders = ",".join("?" for _ in unique_ids)
                rows = connection.execute(
                    f"SELECT * FROM users WHERE telegram_user_id IN ({placeholders})",
                    unique_ids,
                ).fetchall()

        by_id = {int(row["telegram_user_id"]): User.from_row(row) for row in rows}
        return [by_id[telegram_user_id] for telegram_user_id in unique_ids]


def _validate_telegram_user_id(value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0 or value > 2**63 - 1:
        raise ValueError("telegram_user_id must be a positive 64-bit integer")
