"""Sync allowlisted employer boards into the hosted public-demo database."""

import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.demo_sync import sync_demo_jobs


def main() -> int:
    database_url = os.environ.get("DEMO_DATABASE_URL")
    if not database_url:
        print("DEMO_DATABASE_URL is required", file=sys.stderr)
        return 2
    results = sync_demo_jobs(database_url)
    print(json.dumps(results, indent=2, default=str))
    return 1 if any(result.get("status") == "failed" for result in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
