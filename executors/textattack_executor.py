from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import html
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..compatibility import framework_run_compatibility
from ..storage import resolve_workspace_path


TEXTATTACK_RECIPE_ALIASES = {
    "textfooler": "textfooler",
    "textfoolerjin2019": "textfooler",
    "pwws": "pwws",
    "pwwsren2019": "pwws",
    "bae": "bae",
    "baegarg2019": "bae",
    "deepwordbug": "deepwordbug",
    "deepwordbuggao2018": "deepwordbug",
}

TEXTATTACK_GOAL_FUNCTIONS = {
    "untargeted-classification",
}

TEXTATTACK_CONSTRAINT_MODES = {
    "default",
}


def _now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _reports_root(job_record: dict[str, Any]) -> Path:
    job_id = str(job_record.get("job_id", "adhoc"))
    root = Path(__file__).resolve().parents[1] / "data" / "textattack_runs" / job_id / "reports"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _coerce_positive_int(value: Any, *, field_name: str, default: int) -> int:
    if value is None or str(value).strip() == "":
        return default
    try:
        resolved = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Expected '{field_name}' to be an integer.") from exc
    if resolved <= 0:
        raise ValueError(f"Expected '{field_name}' to be greater than zero.")
    return resolved


def _coerce_optional_positive_int(value: Any, *, field_name: str) -> int | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        resolved = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Expected '{field_name}' to be an integer.") from exc
    if resolved <= 0:
        raise ValueError(f"Expected '{field_name}' to be greater than zero.")
    return resolved


def _normalize_recipe(value: Any) -> str:
    raw_value = str(value or "textfooler").strip().lower()
    resolved = TEXTATTACK_RECIPE_ALIASES.get(raw_value)
    if resolved:
        return resolved
    supported = ", ".join(sorted(set(TEXTATTACK_RECIPE_ALIASES.values())))
    raise ValueError(f"Unsupported TextAttack recipe '{raw_value}'. Supported values in this build: {supported}.")


def _normalize_goal_function(value: Any) -> str:
    raw_value = str(value or "untargeted-classification").strip().lower()
    if raw_value in TEXTATTACK_GOAL_FUNCTIONS:
        return raw_value
    supported = ", ".join(sorted(TEXTATTACK_GOAL_FUNCTIONS))
    raise ValueError(
        f"Unsupported TextAttack goal function '{raw_value}'. Supported values in this build: {supported}."
    )


def _normalize_constraint_mode(value: Any) -> str:
    raw_value = str(value or "default").strip().lower()
    if raw_value in TEXTATTACK_CONSTRAINT_MODES:
        return raw_value
    supported = ", ".join(sorted(TEXTATTACK_CONSTRAINT_MODES))
    raise ValueError(
        f"Unsupported TextAttack constraint mode '{raw_value}'. Supported values in this build: {supported}."
    )


def _resolve_local_path(path_value: Any) -> str:
    raw_path = str(path_value or "").strip()
    if not raw_path:
        return ""
    return str(resolve_workspace_path(raw_path, field_name="sample_path"))


def _resolve_textattack_options(job_record: dict[str, Any]) -> dict[str, Any]:
    model = job_record.get("model") or {}
    config = job_record.get("configuration") or {}
    extra_options = config.get("extra_options") or {}

    source_type = str(model.get("source_type") or "").strip().lower()
    source_value = str(model.get("source_value") or "").strip()
    model_id = str(model.get("model_id") or "").strip()
    if not source_value:
        raise ValueError("TextAttack requires a model source value.")

    recipe = _normalize_recipe(extra_options.get("textattack_recipe") or "textfooler")
    goal_function = _normalize_goal_function(
        extra_options.get("textattack_goal_function") or "untargeted-classification"
    )
    constraint_mode = _normalize_constraint_mode(extra_options.get("textattack_constraint_mode") or "default")
    max_examples = _coerce_positive_int(
        extra_options.get("textattack_max_examples") or config.get("min_samples") or 1,
        field_name="textattack_max_examples",
        default=1,
    )
    query_budget = _coerce_optional_positive_int(
        extra_options.get("textattack_query_budget"),
        field_name="textattack_query_budget",
    )
    sample_path = _resolve_local_path(config.get("sample_path") or "")
    target_text = str(config.get("target_text") or "").strip()
    if not sample_path and not target_text:
        raise ValueError("TextAttack requires either Target Text or Sample Path.")

    return {
        "job_id": str(job_record.get("job_id") or "adhoc"),
        "job_name": str(job_record.get("job_name") or "textattack run"),
        "generated_at_utc": _now_utc(),
        "model": {
            "model_id": model_id,
            "source_type": source_type,
            "source_value": source_value,
            "task_family": str(model.get("task_family") or ""),
            "modality": str(model.get("modality") or ""),
        },
        "recipe": recipe,
        "goal_function": goal_function,
        "constraint_mode": constraint_mode,
        "max_examples": max_examples,
        "query_budget": query_budget,
        "sample_path": sample_path,
        "target_text": target_text,
    }


def _build_command(*, runner_config_path: Path, reports_dir: Path) -> list[str]:
    return [
        sys.executable,
        "-m",
        "whitebox_scan_platform.executors.textattack_runner",
        "--config",
        str(runner_config_path),
        "--output-dir",
        str(reports_dir),
    ]


def _run_subprocess(*, command: list[str], cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _copy_if_present(source: Path, destination: Path) -> bool:
    if not source.exists() or not source.is_file():
        return False
    if source.resolve() != destination.resolve():
        shutil.copy2(source, destination)
    return True


def _write_fallback_html(destination: Path, summary: dict[str, Any]) -> None:
    title = "TextAttack Report"
    rows = [
        "<!DOCTYPE html>",
        "<html lang='en'><head><meta charset='utf-8' /><meta name='viewport' content='width=device-width, initial-scale=1' />",
        f"<title>{title}</title>",
        "<style>",
        "/* Bharath Srinivasan | Sentinel Defense TextAttack fallback report presentation. Proprietary material. */",
        ":root { --bg: #07111f; --panel: rgba(11, 23, 39, 0.94); --ink: #eef7ff; --line: rgba(112, 170, 221, 0.16); }",
        "body { margin: 0; font-family: 'Avenir Next', 'Segoe UI', sans-serif; color: var(--ink); background: radial-gradient(circle at top left, rgba(47, 182, 255, 0.16), transparent 24%), linear-gradient(180deg, #040a14 0%, #081323 46%, #0a1729 100%); }",
        ".page { max-width: 1180px; margin: 0 auto; padding: 24px; }",
        ".hero, section { background: var(--panel); border: 1px solid var(--line); border-radius: 18px; box-shadow: 0 22px 54px rgba(2, 7, 15, 0.34); }",
        ".hero { padding: 24px; margin-bottom: 16px; background: linear-gradient(135deg, #071323 0%, #0d233e 38%, #103157 72%, #0a6db3 100%); }",
        "section { padding: 18px; }",
        "pre { white-space: pre-wrap; word-break: break-word; background: rgba(4, 11, 21, 0.96); color: #d8f3dc; border: 1px solid var(--line); border-radius: 12px; padding: 12px; }",
        "</style></head><body><div class='page'>",
        f"<header class='hero'><h1>{html.escape(title)}</h1><p>Status: {html.escape(str(summary.get('status', 'unknown')))}</p><p>Recipe: {html.escape(str(summary.get('recipe', '')))}</p><p>Goal Function: {html.escape(str(summary.get('goal_function', '')))}</p></header>",
        "<section><h2>Raw Result JSON</h2><pre>",
        html.escape(json.dumps(summary, indent=2)),
        "</pre></section></div></body></html>",
        "",
    ]
    destination.write_text("\n".join(rows), encoding="utf-8")


def run_textattack_scan(job_record: dict[str, Any]) -> dict[str, Any]:
    textattack_cache = str((Path(__file__).resolve().parents[1] / "data" / "textattack_cache").resolve())
    matplotlib_cache = str((Path(__file__).resolve().parents[1] / "data" / "matplotlib_cache").resolve())
    os.environ.setdefault("TA_CACHE_DIR", textattack_cache)
    os.environ.setdefault("XDG_CACHE_HOME", textattack_cache)
    os.environ.setdefault("MPLCONFIGDIR", matplotlib_cache)
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

    try:
        import textattack  # noqa: F401
    except Exception as exc:  # pragma: no cover - environment-specific
        raise RuntimeError(f"TextAttack is not available in the active environment: {exc!r}") from exc

    reports_dir = _reports_root(job_record)
    runner_config = _resolve_textattack_options(job_record)
    runner_config_path = reports_dir / "runner_config.json"
    runner_config_path.write_text(json.dumps(runner_config, indent=2) + "\n", encoding="utf-8")

    command = _build_command(runner_config_path=runner_config_path, reports_dir=reports_dir)
    env = os.environ.copy()
    env.setdefault("TA_CACHE_DIR", textattack_cache)
    env.setdefault("XDG_CACHE_HOME", textattack_cache)
    env.setdefault("MPLCONFIGDIR", matplotlib_cache)
    env.setdefault("HF_HUB_OFFLINE", "1")
    env.setdefault("TRANSFORMERS_OFFLINE", "1")
    completed = _run_subprocess(command=command, cwd=Path(__file__).resolve().parents[1], env=env)

    run_log_path = reports_dir / "run_log.txt"
    stdout_text = completed.stdout or ""
    stderr_text = completed.stderr or ""
    run_log_path.write_text(
        "\n".join(
            [
                "$ " + " ".join(command),
                "",
                stdout_text.rstrip(),
                "",
                stderr_text.rstrip(),
                "",
            ]
        ).strip()
        + "\n",
        encoding="utf-8",
    )

    results_json_path = reports_dir / "results.json"
    report_html_path = reports_dir / "report.html"
    if not results_json_path.exists():
        fallback = {
            "framework": "textattack",
            "status": "failed",
            "job_id": runner_config.get("job_id"),
            "job_name": runner_config.get("job_name"),
            "recipe": runner_config.get("recipe"),
            "goal_function": runner_config.get("goal_function"),
            "constraint_mode": runner_config.get("constraint_mode"),
            "max_examples": runner_config.get("max_examples"),
            "query_budget": runner_config.get("query_budget"),
            "model": runner_config.get("model"),
            "generated_at_utc": _now_utc(),
            "error": f"TextAttack exited with code {completed.returncode}.",
        }
        results_json_path.write_text(json.dumps(fallback, indent=2) + "\n", encoding="utf-8")
    results_payload = json.loads(results_json_path.read_text(encoding="utf-8"))

    if not report_html_path.exists():
        _write_fallback_html(report_html_path, results_payload)

    status = str(results_payload.get("status") or ("completed" if completed.returncode == 0 else "failed")).strip().lower()
    if completed.returncode != 0 and status == "completed":
        status = "failed"
    tool_compatibility = framework_run_compatibility(
        "textattack",
        job_record=job_record,
        decisions={
            "executor": "textattack_runner_subprocess",
            "recipe": results_payload.get("recipe") or runner_config.get("recipe"),
            "goal_function": results_payload.get("goal_function") or runner_config.get("goal_function"),
            "constraint_mode": results_payload.get("constraint_mode") or runner_config.get("constraint_mode"),
            "offline_cache_env": {
                "TA_CACHE_DIR": env.get("TA_CACHE_DIR", ""),
                "HF_HUB_OFFLINE": env.get("HF_HUB_OFFLINE", ""),
                "TRANSFORMERS_OFFLINE": env.get("TRANSFORMERS_OFFLINE", ""),
            },
        },
    )
    results_payload["tool_compatibility"] = tool_compatibility
    results_json_path.write_text(json.dumps(results_payload, indent=2) + "\n", encoding="utf-8")

    return {
        "status": status,
        "framework": "textattack",
        "message": "TextAttack run completed." if status == "completed" else "TextAttack run failed.",
        "recipe": results_payload.get("recipe") or runner_config.get("recipe"),
        "goal_function": results_payload.get("goal_function") or runner_config.get("goal_function"),
        "constraint_mode": results_payload.get("constraint_mode") or runner_config.get("constraint_mode"),
        "max_examples": results_payload.get("max_examples") or runner_config.get("max_examples"),
        "query_budget": results_payload.get("query_budget") or runner_config.get("query_budget"),
        "model_name": (results_payload.get("model") or {}).get("model_id") or (runner_config.get("model") or {}).get("model_id"),
        "summary": results_payload.get("summary") or {},
        "tool_compatibility": tool_compatibility,
        "artifacts": {
            "report_html": str(report_html_path),
            "results_json": str(results_json_path),
            "run_log": str(run_log_path),
            "runner_config_json": str(runner_config_path),
        },
        **({"error": f"TextAttack exited with code {completed.returncode}."} if status != "completed" else {}),
    }
