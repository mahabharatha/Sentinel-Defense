#!/usr/bin/env python3
"""Remove failed job records (and their artifact dirs) from data/jobs/.

Usage:
    python scripts/cleanup_failed_jobs.py           # dry-run, lists what would be removed
    python scripts/cleanup_failed_jobs.py --apply   # actually delete

Task 4 (Phase 3): the data/jobs/ directory accumulated records from runs that
failed during wrapper registration ("must inherit from BaseScanAdapter"). These
records carry no useful artifacts and clutter the job list; this script deletes
them safely.

A record is considered eligible for removal when:
    * status == "failed", OR
    * status is missing / unknown and result is empty/missing and errors are non-empty.

For each removed job id we also delete data/job_reports/<job_id>/ if present.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
JOBS_DIR = REPO_ROOT / "data" / "jobs"
JOB_REPORTS_DIR = REPO_ROOT / "data" / "job_reports"


def _is_failed(record: dict) -> bool:
    status = (record.get("status") or "").lower()
    if status == "failed":
        return True
    if status in {"completed", "running", "queued", "pending", "in_progress"}:
        return False
    # Unknown status: treat as failed only if there is no result and there are errors.
    result = record.get("result")
    errors = record.get("errors") or []
    return (not result) and bool(errors)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually delete files. Without this flag the script runs in dry-run mode.",
    )
    args = parser.parse_args()

    if not JOBS_DIR.exists():
        print(f"[skip] {JOBS_DIR} does not exist; nothing to clean.")
        return 0

    to_remove: list[tuple[Path, str]] = []
    kept = 0
    for job_path in sorted(JOBS_DIR.glob("*.json")):
        try:
            record = json.loads(job_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"[warn] unreadable {job_path.name}: {exc}")
            continue
        if _is_failed(record):
            to_remove.append((job_path, record.get("job_id") or job_path.stem))
        else:
            kept += 1

    if not to_remove:
        print(f"No failed jobs to remove. Kept {kept} record(s).")
        return 0

    label = "Would remove" if not args.apply else "Removing"
    print(f"{label} {len(to_remove)} failed job record(s); keeping {kept}:")
    for job_path, job_id in to_remove:
        artifact_dir = JOB_REPORTS_DIR / job_id
        extra = f" + {artifact_dir}" if artifact_dir.exists() else ""
        print(f"  - {job_path.name}  (job_id={job_id}){extra}")
        if args.apply:
            try:
                job_path.unlink()
            except OSError as exc:
                print(f"    [error] could not delete {job_path}: {exc}")
                return 1
            if artifact_dir.exists():
                try:
                    shutil.rmtree(artifact_dir)
                except OSError as exc:
                    print(f"    [error] could not delete {artifact_dir}: {exc}")
                    return 1

    if not args.apply:
        print("\nDry-run only. Re-run with --apply to actually delete.")
    else:
        print("\nDone.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
