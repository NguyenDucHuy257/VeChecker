"""Ordered SQLite migrations for the application."""

from __future__ import annotations

from dataclasses import dataclass
from importlib.resources import files


@dataclass(frozen=True, slots=True)
class Migration:
    version: int
    filename: str

    def read_sql(self) -> str:
        return files(__package__).joinpath(self.filename).read_text(encoding="utf-8")


MIGRATIONS: tuple[Migration, ...] = (
    Migration(version=1, filename="001_initial.sql"),
)
