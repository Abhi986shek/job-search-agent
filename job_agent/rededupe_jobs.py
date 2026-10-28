"""Re-apply the current dedupe rules to jobs already in the database. No API calls, no credits.

Run from job_agent/ with the app stopped:
    ..\\Myenv\\Scripts\\python.exe rededupe_jobs.py            # dry run: shows what would merge
    ..\\Myenv\\Scripts\\python.exe rededupe_jobs.py --apply    # backs up the database, then merges

Merges keep the oldest job and move sources, matches, CV versions, contacts and outreach onto it.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime

from config import DATA_DIR, settings
from db import repositories as repo
from db.session import init_db


def _backup_sqlite() -> str | None:
    if not settings.database_url.startswith("sqlite:///"):
        return None
    src_path = settings.database_url.removeprefix("sqlite:///")
    dst_path = DATA_DIR / f"job_agent.backup-{datetime.now():%Y%m%d-%H%M%S}.db"
    src, dst = sqlite3.connect(src_path), sqlite3.connect(dst_path)
    try:
        src.backup(dst)  # consistent copy, includes data still in the WAL file
    finally:
        dst.close()
        src.close()
    return str(dst_path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="write the merges (default is a dry run)")
    args = parser.parse_args()

    init_db()
    if args.apply:
        backup = _backup_sqlite()
        if backup:
            print(f"Backup written to {backup}")
    report = repo.rededupe_all(apply=args.apply)
    print(json.dumps(report, indent=2))
    if not args.apply and report["groups_to_merge"]:
        print("Dry run only. Re-run with --apply to merge.")


if __name__ == "__main__":
    main()
