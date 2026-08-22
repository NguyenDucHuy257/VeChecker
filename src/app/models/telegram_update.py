"""Persistent idempotency records for Telegram updates."""

from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
import sqlite3
from typing import TYPE_CHECKING, Any, Mapping

if TYPE_CHECKING:
    from app.database import Database


class TelegramUpdateState(StrEnum):
    ACCEPTED = "ACCEPTED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


def _parse_datetime(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


@dataclass(frozen=True, slots=True)
class TelegramUpdate:
    update_id: int
    telegram_user_id: int
    chat_id: int
    state: TelegramUpdateState
    error_code: str | None
    created_at: datetime
    finished_at: datetime | None

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "TelegramUpdate":
        return cls(
            update_id=int(row["update_id"]),
            telegram_user_id=int(row["telegram_user_id"]),
            chat_id=int(row["chat_id"]),
            state=TelegramUpdateState(row["state"]),
            error_code=row["error_code"],
            created_at=_parse_datetime(row["created_at"]),  # type: ignore[arg-type]
            finished_at=_parse_datetime(row["finished_at"]),
        )


class TelegramUpdateRepository:
    def __init__(self, database: "Database") -> None:
        self._database = database

    def reserve(self, update_id: int, telegram_user_id: int, chat_id: int) -> bool:
        if update_id < 0:
            raise ValueError("update_id cannot be negative")
        try:
            with self._database.transaction() as connection:
                connection.execute(
                    """
                    INSERT INTO telegram_updates (
                        update_id, telegram_user_id, chat_id, state
                    ) VALUES (?, ?, ?, 'ACCEPTED')
                    """,
                    (update_id, telegram_user_id, chat_id),
                )
        except sqlite3.IntegrityError:
            return False
        return True

    def release(self, update_id: int) -> None:
        with self._database.transaction() as connection:
            connection.execute(
                "DELETE FROM telegram_updates WHERE update_id = ? AND state = 'ACCEPTED'",
                (update_id,),
            )

    def finish(
        self,
        update_id: int,
        state: TelegramUpdateState,
        *,
        error_code: str | None = None,
    ) -> TelegramUpdate:
        state = TelegramUpdateState(state)
        if state is TelegramUpdateState.ACCEPTED:
            raise ValueError("finish requires COMPLETED or FAILED")
        with self._database.transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE telegram_updates SET
                    state = ?, error_code = ?,
                    finished_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                WHERE update_id = ? AND state = 'ACCEPTED'
                """,
                (state.value, error_code, update_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("Telegram update is missing or already finished")
            row = connection.execute(
                "SELECT * FROM telegram_updates WHERE update_id = ?",
                (update_id,),
            ).fetchone()
        assert row is not None
        return TelegramUpdate.from_row(row)

    def get(self, update_id: int) -> TelegramUpdate | None:
        with closing(self._database.connect()) as connection:
            row = connection.execute(
                "SELECT * FROM telegram_updates WHERE update_id = ?",
                (update_id,),
            ).fetchone()
        return TelegramUpdate.from_row(row) if row is not None else None
