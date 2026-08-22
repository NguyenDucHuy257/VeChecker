"""Create or restore a consistent SQLite application backup."""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from app.config import load_config
from app.database import Database


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)
    backup = subcommands.add_parser("backup")
    backup.add_argument("--output", type=Path, default=None)
    restore = subcommands.add_parser("restore")
    restore.add_argument("backup_file", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = load_config(
        require_vr_credentials=False,
        require_admin_ids=False,
        require_telegram_token=False,
    )
    database = Database(config.database_path)
    if args.command == "backup":
        stamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
        output = args.output or Path("runtime/backups") / f"dktle-{stamp}.sqlite3"
        print(f"backup={database.backup(output)}")
        return 0

    print("Dừng bot trước khi restore để không có transaction đang chạy.")
    print(f"restored={database.restore(args.backup_file)}")
    database.migrate()
    database.recover_incomplete_work()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
