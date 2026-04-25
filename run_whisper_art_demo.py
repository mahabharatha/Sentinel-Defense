from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from fastapi.testclient import TestClient

PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_PARENT = PACKAGE_DIR.parent
if str(PROJECT_PARENT) not in sys.path:
    sys.path.insert(0, str(PROJECT_PARENT))

from whitebox_scan_platform.app import app


def main() -> None:
    client = TestClient(app)
    created = client.post("/api/scans/demo/whisper-art")
    created.raise_for_status()
    job_id = created.json()["job"]["job_id"]

    last = None
    for _ in range(120):
        response = client.get(f"/api/scans/{job_id}")
        response.raise_for_status()
        payload = response.json()["job"]
        last = payload
        if payload["status"] in {"completed", "failed"}:
            break
        time.sleep(1)

    out_dir = PACKAGE_DIR / "data" / "demo"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "whisper_art_demo_job.json"
    path.write_text(json.dumps(last, indent=2), encoding="utf-8")
    print(path.resolve())
    print(json.dumps(last, indent=2))

    framework_run = ((last or {}).get("result") or {}).get("framework_runs", {}).get("art", {})
    artifacts = framework_run.get("artifacts") or {}
    if artifacts.get("results_json"):
        print(f"results_json={artifacts['results_json']}")
    if artifacts.get("report_html"):
        print(f"report_html={artifacts['report_html']}")
    if artifacts.get("run_log"):
        print(f"run_log={artifacts['run_log']}")


if __name__ == "__main__":
    main()
