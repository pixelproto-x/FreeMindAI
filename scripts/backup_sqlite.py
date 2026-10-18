from __future__ import annotations

import argparse
import sqlite3
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from freemind.config import get_database_url


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Create a consistent SQLite backup of FreeMind AI.")
    parser.add_argument("destination", nargs="?", help="Optional destination .db path")
    args = parser.parse_args()

    url = get_database_url()
    if not url.startswith("sqlite:"):
        parser.error("DATABASE_URL is not SQLite. Use your managed PostgreSQL backup/snapshot process instead.")
    source_value = url.removeprefix("sqlite:///")
    source = Path(source_value).expanduser()
    if not source.is_absolute():
        source = Path.cwd() / source
    if not source.is_file():
        parser.error(f"Database file does not exist: {source}")

    if args.destination:
        target = Path(args.destination).expanduser()
    else:
        target = source.parent / "backups" / f"freemind-{datetime.now().strftime('%Y%m%d-%H%M%S')}.db"
    if not target.is_absolute():
        target = Path.cwd() / target
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.resolve() == target.resolve():
        parser.error("Backup destination must be different from the live database path.")

    with sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True) as source_conn:
        with sqlite3.connect(target) as target_conn:
            source_conn.backup(target_conn)
    print(f"Backup saved: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
