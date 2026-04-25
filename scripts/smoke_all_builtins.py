#!/usr/bin/env python3
"""End-to-end smoke driver for every built-in template.

Loads each template from data/builtin_templates.json, POSTs it to the running
server, polls until the job reaches a terminal state, then validates every
report artefact. Produces a verdict table and a detailed per-template log.

Usage:
    # Server must already be running (python run.py)
    python scripts/smoke_all_builtins.py
    python scripts/smoke_all_builtins.py --host http://127.0.0.1:8000
    python scripts/smoke_all_builtins.py --only 1,2,5         # template indexes
    python scripts/smoke_all_builtins.py --skip 13,14,15       # skip PyRIT multimodal
    python scripts/smoke_all_builtins.py --timeout 900         # per-job wait (s)
    python scripts/smoke_all_builtins.py --dry-preflight       # preflight only

Exit codes:
    0  all templates passed (completed + reports clean)
    1  at least one template failed or produced an error-laden report
    2  server unreachable
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parent.parent
BUILTIN_TEMPLATES_PATH = REPO_ROOT / "data" / "builtin_templates.json"

TERMINAL_STATUSES = {"completed", "failed", "error", "cancelled"}
POLL_INTERVAL_SEC = 3.0

# Markers we flag in run_log / HTML report when auditing for errors.
# Each is matched line-anchored in a smart way: the checker below skips a
# marker if it's inside a JSON value (e.g. Garak's summary embeds a
# "target_error_marker": "GARAK_TARGET_ERROR:" config string which is not
# an actual error).
ERROR_MARKERS = [
    "Traceback (most recent call last):",
    "Uncaught exception",
    "FATAL:",
    "AssertionError:",
]


def _log_has_real_error(log_text: str) -> list[str]:
    """Return the list of ERROR_MARKERS that appear on their own on a line,
    not as a substring of a JSON string value. This avoids flagging
    config dumps that contain the words ERROR / Exception.
    """
    hits = []
    for line in log_text.splitlines():
        stripped = line.strip()
        # Skip obvious JSON-value lines like:
        #   "target_error_marker": "GARAK_TARGET_ERROR:"
        if stripped.startswith('"') and stripped.endswith(('",', '"')):
            continue
        for marker in ERROR_MARKERS:
            if marker in line:
                hits.append(marker)
                break
    return sorted(set(hits))


def http_json(url: str, method: str = "GET", payload: dict | None = None,
              timeout: float = 30.0) -> dict:
    req = urllib.request.Request(url, method=method)
    data_bytes = None
    if payload is not None:
        data_bytes = json.dumps(payload).encode("utf-8")
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, data=data_bytes, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def parse_template_selection(spec: str) -> set[int]:
    if not spec:
        return set()
    out: set[int] = set()
    for chunk in spec.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "-" in chunk:
            a, b = chunk.split("-", 1)
            out.update(range(int(a), int(b) + 1))
        else:
            out.add(int(chunk))
    return out


def short(obj: Any, n: int = 180) -> str:
    s = json.dumps(obj, default=str) if not isinstance(obj, str) else obj
    return s if len(s) <= n else s[: n - 1] + "…"


def validate_report(job_record: dict, audit: dict) -> list[str]:
    """Return a list of issues found in the report. Empty list = clean."""
    issues: list[str] = []
    status = job_record.get("status")
    errors = job_record.get("errors") or []

    if status != "completed":
        issues.append(f"job.status={status!r} (expected 'completed')")

    if errors:
        for e in errors[:3]:
            msg = e.get("message") if isinstance(e, dict) else str(e)
            issues.append(f"job.errors: {short(msg)}")

    result = job_record.get("result") or {}
    if not result:
        issues.append("job.result is empty — no scan output recorded")
        return issues

    # For each mode present, verify the expected artefacts
    for mode_name in ("blackbox", "whitebox"):
        mode = result.get(mode_name)
        if not isinstance(mode, dict):
            continue
        artefacts = mode.get("artifacts") or {}
        # Summary HTML + JSON + run_log should all exist
        for expected_key in ("summary_report_html", "summary_results_json", "summary_run_log"):
            path_str = artefacts.get(expected_key)
            if not path_str:
                issues.append(f"{mode_name}: missing artefact '{expected_key}'")
                continue
            p = Path(path_str)
            if not p.exists():
                issues.append(f"{mode_name}.{expected_key}: file missing on disk ({p})")
            elif p.stat().st_size == 0:
                issues.append(f"{mode_name}.{expected_key}: file is empty ({p})")

        # Normalized severity payload shape. The real payload (see
        # reporting.normalized._build_normalized_severity_payload) returns:
        #   schema_version, severity_engine_version, mapping_ruleset_version,
        #   framework, scan_mode, source_artifacts, overall_normalized_verdict,
        #   normalized_findings, severity_mapping_log, non_scored_attacks,
        #   normalized_evidence_references
        ns = mode.get("normalized_severity") or {}
        if not ns:
            issues.append(f"{mode_name}: normalized_severity payload missing")
        else:
            required_keys = {"overall_normalized_verdict", "normalized_findings", "framework", "scan_mode"}
            missing = required_keys - set(ns.keys())
            if missing:
                issues.append(f"{mode_name}.normalized_severity: missing keys {sorted(missing)}")
            # If the framework run produced evidence, overall_verdict should
            # carry a label or a per-severity count dict; empty structure is
            # usually a sign the scan never produced findings.
            verdict = ns.get("overall_normalized_verdict") or {}
            if isinstance(verdict, dict) and not verdict:
                issues.append(f"{mode_name}.overall_normalized_verdict is an empty dict (no findings produced)")

        # results_json should be readable as JSON
        rj = artefacts.get("summary_results_json")
        if rj and Path(rj).exists():
            try:
                json.loads(Path(rj).read_text(encoding="utf-8"))
            except Exception as exc:
                issues.append(f"{mode_name}.summary_results_json: not valid JSON ({exc})")

        # run_log should not contain tracebacks / FATAL markers (line-aware;
        # skips JSON-value lines where config strings might contain the words).
        rl = artefacts.get("summary_run_log")
        if rl and Path(rl).exists():
            try:
                log_text = Path(rl).read_text(encoding="utf-8", errors="replace")
                hits = _log_has_real_error(log_text)
                if hits:
                    issues.append(f"{mode_name}.summary_run_log contains error markers: {hits}")
            except OSError as exc:
                issues.append(f"{mode_name}.summary_run_log: read failed ({exc})")

        # HTML report: must be non-trivial; scan for obvious error panels
        rh = artefacts.get("summary_report_html")
        if rh and Path(rh).exists():
            try:
                html_text = Path(rh).read_text(encoding="utf-8", errors="replace")
                if len(html_text) < 500:
                    issues.append(f"{mode_name}.summary_report_html: suspiciously short ({len(html_text)} bytes)")
                for bad in ("Traceback (most recent call last)", "class=\"error-panel\"",
                            "Exception occurred:", "INTERNAL ERROR"):
                    if bad in html_text:
                        issues.append(f"{mode_name}.summary_report_html contains '{bad}'")
                        break
            except OSError as exc:
                issues.append(f"{mode_name}.summary_report_html: read failed ({exc})")

    # Framework-level run: every framework the job asked for must have a real run record
    requested = set(job_record.get("configuration", {}).get("frameworks") or [])
    framework_runs = result.get("framework_runs") or {}
    for fw in requested:
        fr = framework_runs.get(fw)
        if not fr:
            issues.append(f"framework_runs.{fw}: missing")
        elif fr.get("status") in {"failed", "error"}:
            issues.append(f"framework_runs.{fw}.status={fr.get('status')!r} — {short(fr.get('error') or fr.get('message'))}")

    audit["result_keys"] = list(result.keys())
    audit["framework_runs"] = {fw: (fr.get("status") if isinstance(fr, dict) else None) for fw, fr in framework_runs.items()}
    return issues


def run_one_template(host: str, index: int, template: dict, args) -> dict:
    verdict: dict[str, Any] = {
        "index": index,
        "template_id": template.get("template_id"),
        "template_name": template.get("template_name"),
        "job_id": None,
        "status": None,
        "elapsed_sec": None,
        "issues": [],
        "audit": {},
    }
    payload = template.get("payload") or {}

    if args.dry_preflight:
        try:
            pre = http_json(f"{host}/api/scans/preflight", method="POST", payload=payload, timeout=60)
        except urllib.error.URLError as exc:
            verdict["issues"].append(f"preflight transport error: {exc}")
            return verdict
        pre_data = pre.get("preflight") or {}
        verdict["audit"]["preflight_status"] = pre_data.get("status")
        verdict["audit"]["preflight_blockers"] = pre_data.get("blockers") or []
        verdict["status"] = pre_data.get("status") or "unknown"
        if pre_data.get("blockers"):
            verdict["issues"].extend(f"preflight blocker: {b}" for b in pre_data["blockers"])
        return verdict

    # Launch
    try:
        created = http_json(f"{host}/api/scans", method="POST", payload=payload, timeout=60)
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8")
        except Exception:
            pass
        verdict["issues"].append(f"launch HTTP {exc.code}: {body[:400]}")
        return verdict
    except urllib.error.URLError as exc:
        verdict["issues"].append(f"launch transport error: {exc}")
        return verdict

    job = created.get("job") or {}
    job_id = job.get("job_id")
    verdict["job_id"] = job_id
    if not job_id:
        verdict["issues"].append(f"launch did not return job_id: {created}")
        return verdict

    # Poll until terminal. Print a heartbeat every ~15s so long-running
    # scans (Garak probe suites, PyRIT attack loops, TextAttack model
    # loads) show visible progress even when output is piped through tee.
    t_start = time.time()
    last_heartbeat = t_start
    print(f"     launched job_id={job_id}, polling…", flush=True)
    while True:
        try:
            record = http_json(f"{host}/api/scans/{job_id}", timeout=30).get("job") or {}
        except urllib.error.URLError as exc:
            verdict["issues"].append(f"poll transport error: {exc}")
            return verdict
        status = record.get("status") or "unknown"
        verdict["status"] = status
        elapsed = time.time() - t_start
        verdict["elapsed_sec"] = round(elapsed, 1)
        if status in TERMINAL_STATUSES:
            verdict["issues"] = validate_report(record, verdict["audit"])
            return verdict
        if elapsed > args.timeout:
            verdict["issues"].append(f"timeout after {int(elapsed)}s in status={status!r}")
            return verdict
        now = time.time()
        if now - last_heartbeat >= 15:
            print(f"       … still {status} at {int(elapsed)}s", flush=True)
            last_heartbeat = now
        time.sleep(POLL_INTERVAL_SEC)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", default="http://127.0.0.1:8000", help="Server base URL.")
    parser.add_argument("--only", default="", help="Comma/range list of template indexes to run.")
    parser.add_argument("--skip", default="", help="Comma/range list of template indexes to skip.")
    parser.add_argument("--timeout", type=int, default=900, help="Per-template timeout (sec). Default 900.")
    parser.add_argument("--dry-preflight", action="store_true", help="Run preflight only, don't launch scans.")
    parser.add_argument("--json-out", default="", help="Write the full verdict list as JSON here.")
    args = parser.parse_args()

    if not BUILTIN_TEMPLATES_PATH.exists():
        print(f"[error] {BUILTIN_TEMPLATES_PATH} does not exist", file=sys.stderr)
        return 2
    templates = json.loads(BUILTIN_TEMPLATES_PATH.read_text(encoding="utf-8"))

    # Server reachability check
    try:
        http_json(f"{args.host}/api/options", timeout=5)
    except Exception as exc:
        print(f"[error] server not reachable at {args.host}: {exc}", file=sys.stderr)
        print("Start it first with:  python run.py", file=sys.stderr)
        return 2

    only = parse_template_selection(args.only)
    skip = parse_template_selection(args.skip)

    verdicts: list[dict] = []
    for idx, template in enumerate(templates, 1):
        if only and idx not in only:
            continue
        if skip and idx in skip:
            continue
        name = template.get("template_name", "<unnamed>")
        print(f"\n[{idx:2d}/{len(templates)}] {name}")
        verdict = run_one_template(args.host, idx, template, args)
        verdicts.append(verdict)
        status = verdict["status"] or "?"
        marker = "OK" if (status == "completed" and not verdict["issues"]) else "FAIL"
        issue_summary = "; ".join(verdict["issues"][:3])
        print(f"     → {marker}  status={status}  job_id={verdict['job_id']}  elapsed={verdict['elapsed_sec']}s"
              + (f"\n        issues: {issue_summary}" if verdict["issues"] else ""))

    # Final verdict table
    print("\n" + "=" * 100)
    print(f"{'#':>3}  {'status':10s}  {'issues':>6s}  template")
    print("-" * 100)
    ok = 0
    fail = 0
    for v in verdicts:
        clean = v["status"] == "completed" and not v["issues"]
        if clean: ok += 1
        else: fail += 1
        print(f"{v['index']:>3}  {str(v['status'])[:10]:10s}  {len(v['issues']):>6d}  "
              f"{(v['template_name'] or '')[:70]}")
    print("-" * 100)
    print(f"Total: {len(verdicts)}   Clean: {ok}   With issues: {fail}")

    # Per-template detail for failures
    failing = [v for v in verdicts if v["issues"]]
    if failing:
        print("\n" + "=" * 100)
        print("Per-template diagnostics (templates with issues):")
        print("=" * 100)
        for v in failing:
            print(f"\n#{v['index']}  {v['template_name']}")
            print(f"  job_id: {v['job_id']}")
            print(f"  final status: {v['status']}")
            print(f"  elapsed: {v['elapsed_sec']}s")
            if v["audit"].get("framework_runs"):
                print(f"  framework_runs: {v['audit']['framework_runs']}")
            print(f"  issues ({len(v['issues'])}):")
            for issue in v["issues"]:
                print(f"    - {issue}")

    if args.json_out:
        Path(args.json_out).write_text(json.dumps(verdicts, indent=2, default=str), encoding="utf-8")
        print(f"\nDetailed JSON written to: {args.json_out}")

    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
