"""Run an opt-in record-retention dry run; deletion requires --delete-expired."""

from __future__ import annotations

import argparse
from pathlib import Path

from backend.mushroom.config import Settings
from backend.mushroom.db import FirebaseDB, MemoryDB
from backend.mushroom.retention import RetentionJob


def main() -> int:
    """Show the number of expired records, deleting only after an explicit flag."""
    parser = argparse.ArgumentParser(
        description="Review or apply configured record retention."
    )
    parser.add_argument(
        "--delete-expired",
        action="store_true",
        help="Delete expired records after review",
    )
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    settings = Settings.from_env(root / "backend" / ".env", root)
    database = (
        MemoryDB()
        if settings.db_backend == "memory"
        else FirebaseDB(settings.firebase_url, str(settings.firebase_credentials))
    )
    result = RetentionJob(database, settings.retention_days_records).run(
        dry_run=not args.delete_expired
    )
    action = "would delete" if not args.delete_expired else "deleted"
    print(
        f"Retention enabled: {result['enabled']}; expired records: {result['candidates']}; {action}: {result['deleted']}."
    )
    if not result["enabled"]:
        print("Set RETENTION_DAYS_RECORDS to a positive number to enable cleanup.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
