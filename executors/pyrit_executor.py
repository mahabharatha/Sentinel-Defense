from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import html
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..compatibility import framework_run_compatibility
from ..storage import resolve_workspace_path


PYRIT_ATTACK_ALIASES = {
    "prompt_sending": "prompt_sending",
    "multi_prompt_sending": "multi_prompt_sending",
    "multi-prompt-sending": "multi_prompt_sending",
    "multi_prompt": "multi_prompt_sending",
    "flip": "flip",
    "flip_attack": "flip",
    "many_shot": "many_shot_jailbreak",
    "many_shot_jailbreak": "many_shot_jailbreak",
    "skeleton_key": "skeleton_key",
    "skeleton_key_attack": "skeleton_key",
    "red_teaming": "red_teaming",
    "red_team": "red_teaming",
    "rta": "red_teaming",
    "crescendo": "crescendo",
}

PYRIT_PROFILE_ALIASES = {
    "": "text",
    "text": "text",
    "llm": "text",
    "multimodal": "multimodal",
    "vision-language": "multimodal",
    "vision_language": "multimodal",
    "vlm": "multimodal",
}

PYRIT_PROFILE_ATTACKS = {
    "text": {
        "prompt_sending",
        "flip",
        "many_shot_jailbreak",
        "skeleton_key",
        "red_teaming",
        "crescendo",
    },
    "multimodal": {
        "prompt_sending",
        "multi_prompt_sending",
    },
}

WORKSPACE_ROOT = Path(__file__).resolve().parents[1]


def _now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _reports_root(job_record: dict[str, Any]) -> Path:
    job_id = str(job_record.get("job_id", "adhoc"))
    root = Path(__file__).resolve().parents[1] / "data" / "pyrit_runs" / job_id / "reports"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _looks_like_local_ollama_endpoint(endpoint_uri: str) -> bool:
    value = str(endpoint_uri or "").strip().lower()
    if not value:
        return False
    return "127.0.0.1:11434" in value or "localhost:11434" in value


def _normalize_openai_chat_endpoint(endpoint_uri: str) -> str:
    value = str(endpoint_uri or "").strip()
    lowered = value.lower()
    if not value:
        raise ValueError("PyRIT requires a target endpoint URI.")
    if not _looks_like_local_ollama_endpoint(lowered):
        return value
    if lowered.endswith("/api/generate"):
        return value.rsplit("/", 1)[0] + "/chat"
    if lowered.endswith("/api/chat"):
        return value
    if lowered.endswith("/v1/chat/completions"):
        base = value.rsplit("/", 3)[0]
        return f"{base}/api/chat"
    return value


def _coerce_non_negative_int(value: Any, *, field_name: str, default: int = 0) -> int:
    if value is None or str(value).strip() == "":
        return default
    try:
        resolved = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Expected '{field_name}' to be an integer.") from exc
    if resolved < 0:
        raise ValueError(f"Expected '{field_name}' to be zero or greater.")
    return resolved


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


def _normalize_attack_type(value: Any) -> str:
    raw_value = str(value or "prompt_sending").strip().lower()
    attack_type = PYRIT_ATTACK_ALIASES.get(raw_value)
    if attack_type:
        return attack_type
    supported = ", ".join(sorted(PYRIT_ATTACK_ALIASES))
    raise ValueError(
        f"Unsupported PyRIT attack type '{raw_value}'. Supported values in this build: {supported}."
    )


def _normalize_attack_types(value: Any) -> list[str]:
    if isinstance(value, (list, tuple, set)):
        raw_values = [str(item or "").strip() for item in value]
    else:
        raw_text = str(value or "").strip()
        raw_values = [item.strip() for item in raw_text.split(",")] if raw_text else []

    normalized: list[str] = []
    seen: set[str] = set()
    for raw_value in raw_values:
        if not raw_value:
            continue
        attack_type = _normalize_attack_type(raw_value)
        if attack_type in seen:
            continue
        seen.add(attack_type)
        normalized.append(attack_type)
    return normalized


def _normalize_objective_scorer_mode(value: Any) -> str:
    raw_value = str(value or "auto").strip().lower()
    aliases = {
        "": "auto",
        "auto": "auto",
        "exact": "exact_literal",
        "exact_literal": "exact_literal",
        "contains_all": "contains_literal",
        "contains_all_literals": "contains_literal",
        "contains": "contains_literal",
        "contains_literal": "contains_literal",
        "contains_any": "contains_any_literal",
        "contains_any_literal": "contains_any_literal",
        "any_literal": "contains_any_literal",
        "ordered": "ordered_literals",
        "ordered_literals": "ordered_literals",
        "disabled": "disabled",
        "off": "disabled",
        "none": "disabled",
    }
    resolved = aliases.get(raw_value)
    if resolved:
        return resolved
    supported = ", ".join(sorted(set(aliases.values())))
    raise ValueError(
        f"Unsupported PyRIT objective scorer mode '{raw_value}'. Supported values in this build: {supported}."
    )


def _normalize_pyrit_profile(value: Any) -> str:
    raw_value = str(value or "text").strip().lower()
    resolved = PYRIT_PROFILE_ALIASES.get(raw_value)
    if resolved:
        return resolved
    supported = ", ".join(sorted(set(PYRIT_PROFILE_ALIASES.values())))
    raise ValueError(
        f"Unsupported PyRIT profile '{raw_value}'. Supported values in this build: {supported}."
    )


def _coerce_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        raw_items = re.split(r"[\n,;]+", value)
    elif isinstance(value, (list, tuple, set)):
        raw_items = [str(item or "") for item in value]
    else:
        raw_items = [str(value)]

    resolved: list[str] = []
    seen: set[str] = set()
    for raw_item in raw_items:
        item = str(raw_item or "").strip()
        if not item:
            continue
        normalized_key = item.casefold()
        if normalized_key in seen:
            continue
        seen.add(normalized_key)
        resolved.append(item)
    return resolved


def _resolve_local_path(path_value: Any) -> str:
    raw_path = str(path_value or "").strip()
    if not raw_path:
        return ""
    return str(resolve_workspace_path(raw_path, field_name="pyrit_local_path"))


def _resolve_pyrit_options(job_record: dict[str, Any]) -> dict[str, Any]:
    model = job_record.get("model") or {}
    config = job_record.get("configuration") or {}
    extra_options = config.get("extra_options") or {}
    profile = _normalize_pyrit_profile(extra_options.get("pyrit_profile") or "text")

    endpoint_uri = str(
        extra_options.get("pyrit_endpoint_uri")
        or extra_options.get("endpoint_uri")
        or model.get("source_value")
        or ""
    ).strip()
    if not endpoint_uri:
        raise ValueError("PyRIT requires an endpoint URI. Set model.source_value or configuration.extra_options.pyrit_endpoint_uri.")
    endpoint_uri = _normalize_openai_chat_endpoint(endpoint_uri)

    attack_types = _normalize_attack_types(
        extra_options.get("pyrit_attack_types")
        or extra_options.get("pyrit_attack_type")
        or "prompt_sending"
    )
    if not attack_types:
        attack_types = ["prompt_sending"]
    attack_type = attack_types[0]
    unsupported_attacks = [
        declared_attack for declared_attack in attack_types if declared_attack not in PYRIT_PROFILE_ATTACKS[profile]
    ]
    if unsupported_attacks:
        supported_for_profile = ", ".join(sorted(PYRIT_PROFILE_ATTACKS[profile]))
        raise ValueError(
            f"PyRIT profile '{profile}' does not support attack(s): {', '.join(unsupported_attacks)}. "
            f"Supported attacks for this profile in the current build: {supported_for_profile}."
        )

    seed_text = str(extra_options.get("pyrit_seed_text") or "").strip()
    objective = str(
        extra_options.get("pyrit_objective")
        or config.get("target_text")
        or (seed_text if profile == "multimodal" else "")
        or "Return the exact string PYRIT_SMOKE_TEST."
    ).strip()
    if not objective:
        raise ValueError("PyRIT requires a non-empty objective prompt.")

    model_name = str(
        extra_options.get("pyrit_model_name")
        or extra_options.get("pyrit_runtime_model")
        or model.get("model_id")
        or "unknown-model"
    ).strip()
    if not model_name:
        raise ValueError("PyRIT requires a model name. Set model.model_id or configuration.extra_options.pyrit_model_name.")

    max_attempts_on_failure = _coerce_non_negative_int(
        extra_options.get("pyrit_max_attempts_on_failure"),
        field_name="pyrit_max_attempts_on_failure",
        default=0,
    )
    request_timeout_sec = _coerce_positive_int(
        extra_options.get("pyrit_request_timeout") or extra_options.get("pyrit_response_timeout"),
        field_name="pyrit_request_timeout",
        default=120,
    )
    many_shot_example_count = _coerce_positive_int(
        extra_options.get("pyrit_many_shot_example_count"),
        field_name="pyrit_many_shot_example_count",
        default=25,
    )
    max_turns = _coerce_positive_int(
        extra_options.get("pyrit_max_turns"),
        field_name="pyrit_max_turns",
        default=10,
    )
    max_backtracks = _coerce_non_negative_int(
        extra_options.get("pyrit_max_backtracks"),
        field_name="pyrit_max_backtracks",
        default=10,
    )
    skeleton_key_prompt = str(
        extra_options.get("pyrit_skeleton_key_prompt")
        or ""
    ).strip()
    adversarial_endpoint_uri = str(
        extra_options.get("pyrit_adversarial_endpoint_uri")
        or endpoint_uri
    ).strip()
    if not adversarial_endpoint_uri:
        adversarial_endpoint_uri = endpoint_uri
    adversarial_endpoint_uri = _normalize_openai_chat_endpoint(adversarial_endpoint_uri)
    adversarial_model_name = str(
        extra_options.get("pyrit_adversarial_model_name")
        or model_name
    ).strip()
    if not adversarial_model_name:
        adversarial_model_name = model_name
    objective_scorer_mode = _normalize_objective_scorer_mode(
        extra_options.get("pyrit_objective_scorer_mode") or "auto"
    )
    expected_response = str(
        extra_options.get("pyrit_expected_response")
        or extra_options.get("pyrit_expected_literal")
        or ""
    ).strip()
    expected_responses = _coerce_string_list(
        extra_options.get("pyrit_expected_responses")
        or extra_options.get("pyrit_required_literals")
    )
    if not expected_responses and expected_response and objective_scorer_mode == "contains_literal":
        parsed_expected_responses = _coerce_string_list(expected_response)
        if len(parsed_expected_responses) > 1:
            expected_responses = parsed_expected_responses
    if not expected_responses and expected_response:
        expected_responses = [expected_response]
    if expected_responses:
        expected_response = expected_responses[0]
    if expected_responses and not expected_response:
        expected_response = expected_responses[0]
    explicit_seed_image_path = str(extra_options.get("pyrit_seed_image_path") or "").strip()
    sample_path_seed_image = str(config.get("sample_path") or "").strip() if profile == "multimodal" else ""
    seed_image_path = explicit_seed_image_path or sample_path_seed_image or ""
    if explicit_seed_image_path:
        seed_image_source = "pyrit_seed_image_path"
    elif sample_path_seed_image:
        seed_image_source = "sample_path_fallback"
    else:
        seed_image_source = ""
    resolved_seed_image_path = _resolve_local_path(seed_image_path) if seed_image_path else ""
    follow_up_text = str(
        extra_options.get("pyrit_follow_up_text")
        or extra_options.get("pyrit_multimodal_follow_up_text")
        or ""
    ).strip()
    forbidden_literals = _coerce_string_list(
        extra_options.get("pyrit_forbidden_literals")
        or extra_options.get("pyrit_forbidden_response_literals")
    )
    expected_max_words = _coerce_optional_positive_int(
        extra_options.get("pyrit_expected_max_words") or extra_options.get("pyrit_max_words"),
        field_name="pyrit_expected_max_words",
    )
    expected_max_sentences = _coerce_optional_positive_int(
        extra_options.get("pyrit_expected_max_sentences") or extra_options.get("pyrit_max_sentences"),
        field_name="pyrit_expected_max_sentences",
    )

    return {
        "job_id": job_record.get("job_id"),
        "job_name": job_record.get("job_name"),
        "framework": "pyrit",
        "profile": profile,
        "target_uri": endpoint_uri,
        "original_target_uri": str(model.get("source_value") or ""),
        "model_name": model_name,
        "attack_type": attack_type,
        "attack_types": attack_types,
        "objective": objective,
        "max_attempts_on_failure": max_attempts_on_failure,
        "request_timeout_sec": request_timeout_sec,
        "many_shot_example_count": many_shot_example_count,
        "max_turns": max_turns,
        "max_backtracks": max_backtracks,
        "skeleton_key_prompt": skeleton_key_prompt,
        "adversarial_target_uri": adversarial_endpoint_uri,
        "adversarial_model_name": adversarial_model_name,
        "expected_response": expected_response,
        "expected_responses": expected_responses,
        "forbidden_literals": forbidden_literals,
        "expected_max_words": expected_max_words,
        "expected_max_sentences": expected_max_sentences,
        "objective_scorer_mode": objective_scorer_mode,
        "seed_text": seed_text,
        "configured_seed_image_path": explicit_seed_image_path,
        "seed_image_path": resolved_seed_image_path,
        "seed_image_source": seed_image_source,
        "follow_up_text": follow_up_text,
        "api_key_env_var": str(extra_options.get("pyrit_api_key_env_var") or "OPENAI_CHAT_KEY"),
        "endpoint_env_var": str(extra_options.get("pyrit_endpoint_env_var") or "OPENAI_CHAT_ENDPOINT"),
        "model_env_var": str(extra_options.get("pyrit_model_env_var") or "OPENAI_CHAT_MODEL"),
    }


def _build_command(
    *,
    runner_config_path: Path,
    results_json_path: Path,
    report_html_path: Path,
    run_log_path: Path,
) -> list[str]:
    return [
        sys.executable,
        "-m",
        "whitebox_scan_platform.executors.pyrit_runner",
        "--config",
        str(runner_config_path),
        "--results-json",
        str(results_json_path),
        "--report-html",
        str(report_html_path),
        "--run-log",
        str(run_log_path),
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


def _write_fallback_html(destination: Path, summary: dict[str, Any]) -> None:
    title = "PyRIT Report"
    destination.write_text(
        "\n".join(
            [
                "<!DOCTYPE html>",
                "<html lang='en'><head><meta charset='utf-8' /><meta name='viewport' content='width=device-width, initial-scale=1' />",
                f"<title>{title}</title>",
                "<style>",
                "/* Bharath Srinivasan | Sentinel Defense PyRIT aggregate report presentation. Proprietary material. */",
                ":root { --bg: #07111f; --panel: rgba(11, 23, 39, 0.94); --ink: #eef7ff; --ink-soft: #a9bfd6; --line: rgba(112, 170, 221, 0.16); --accent: #2fb6ff; }",
                "body { margin: 0; font-family: 'Avenir Next', 'Segoe UI', sans-serif; color: var(--ink); background: radial-gradient(circle at top left, rgba(47, 182, 255, 0.16), transparent 24%), linear-gradient(180deg, #040a14 0%, #081323 46%, #0a1729 100%); }",
                ".page { max-width: 1180px; margin: 0 auto; padding: 24px; }",
                ".hero, section { background: var(--panel); border: 1px solid var(--line); border-radius: 18px; box-shadow: 0 22px 54px rgba(2, 7, 15, 0.34); }",
                ".hero { padding: 24px; margin-bottom: 16px; background: linear-gradient(135deg, #071323 0%, #0d233e 38%, #103157 72%, #0a6db3 100%); }",
                "section { padding: 18px; }",
                "pre { white-space: pre-wrap; word-break: break-word; background: rgba(4, 11, 21, 0.96); color: #d8f3dc; border: 1px solid var(--line); border-radius: 12px; padding: 12px; }",
                "</style></head><body><div class='page'>",
                f"<header class='hero'><h1>{html.escape(title)}</h1><p>Status: {html.escape(str(summary.get('status', 'unknown')))}</p><p>Target URI: {html.escape(str(summary.get('target_uri', '')))}</p><p>Attack Type: {html.escape(str(summary.get('attack_type', '')))}</p><p>Objective: {html.escape(str(summary.get('objective', '')))}</p></header>",
                "<section><h2>Raw Result JSON</h2><pre>",
                html.escape(json.dumps(summary, indent=2)),
                "</pre></section></div></body></html>",
                "",
            ]
        ),
        encoding="utf-8",
    )


def _attack_slug(attack_type: str, index: int) -> str:
    safe = "".join(ch if ch.isalnum() else "_" for ch in str(attack_type or "attack").strip().lower()).strip("_")
    return f"{index + 1:02d}_{safe or 'attack'}"


def _build_aggregate_html(summary: dict[str, Any]) -> str:
    attack_runs = summary.get("attack_runs") or []
    rows = []
    for attack_run in attack_runs:
        if not isinstance(attack_run, dict):
            continue
        rows.append(
            "<tr>"
            f"<td>{attack_run.get('attack_type', '-')}</td>"
            f"<td>{attack_run.get('status', '-')}</td>"
            f"<td>{(attack_run.get('result_metadata') or {}).get('outcome', '-')}</td>"
            f"<td>{(attack_run.get('platform_evaluation') or {}).get('verdict', '-')}</td>"
            f"<td>{(attack_run.get('platform_evaluation') or {}).get('severity', '-')}</td>"
            f"<td>{attack_run.get('target_uri', '-')}</td>"
            "</tr>"
        )
    table_html = (
        "<table border='1' cellspacing='0' cellpadding='6'>"
        "<thead><tr><th>Attack</th><th>Status</th><th>Raw Outcome</th><th>Platform Verdict</th><th>Severity</th><th>Target URI</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
        if rows
        else "<p>No PyRIT attack runs were recorded.</p>"
    )
    return "\n".join(
        [
            "<!DOCTYPE html>",
            "<html lang='en'><head><meta charset='utf-8' /><meta name='viewport' content='width=device-width, initial-scale=1' />",
            "<title>PyRIT Report</title>",
            "<style>",
            "/* Bharath Srinivasan | Sentinel Defense PyRIT aggregate report presentation. Proprietary material. */",
            ":root { --bg: #07111f; --panel: rgba(11, 23, 39, 0.94); --ink: #eef7ff; --ink-soft: #a9bfd6; --line: rgba(112, 170, 221, 0.16); --accent: #2fb6ff; }",
            "body { margin: 0; font-family: 'Avenir Next', 'Segoe UI', sans-serif; color: var(--ink); background: radial-gradient(circle at top left, rgba(47, 182, 255, 0.16), transparent 24%), linear-gradient(180deg, #040a14 0%, #081323 46%, #0a1729 100%); }",
            ".page { max-width: 1180px; margin: 0 auto; padding: 24px; }",
            ".hero, section { background: var(--panel); border: 1px solid var(--line); border-radius: 18px; box-shadow: 0 22px 54px rgba(2, 7, 15, 0.34); }",
            ".hero { padding: 24px; margin-bottom: 16px; background: linear-gradient(135deg, #071323 0%, #0d233e 38%, #103157 72%, #0a6db3 100%); }",
            "section { padding: 18px; margin-bottom: 16px; }",
            "table { width: 100%; border-collapse: collapse; font-size: 14px; background: rgba(8, 18, 31, 0.34); border-radius: 14px; overflow: hidden; }",
            "th, td { border-bottom: 1px solid var(--line); padding: 10px 12px; text-align: left; vertical-align: top; }",
            "th { background: rgba(16, 35, 58, 0.92); text-transform: uppercase; font-size: 12px; letter-spacing: 0.05em; color: var(--ink-soft); }",
            "pre { white-space: pre-wrap; word-break: break-word; background: rgba(4, 11, 21, 0.96); color: #d8f3dc; border: 1px solid var(--line); border-radius: 12px; padding: 12px; }",
            "</style></head><body><div class='page'>",
            f"<header class='hero'><h1>PyRIT Report</h1><p>Status: {html.escape(str(summary.get('status', 'unknown')))}</p><p>Profile: {html.escape(str(summary.get('profile', 'text')))}</p><p>Target URI: {html.escape(str(summary.get('target_uri', '')))}</p><p>Attacks Requested: {html.escape(', '.join(summary.get('attack_types') or []) or '-')}</p><p>Objective: {html.escape(str(summary.get('objective', '')))}</p></header>",
            f"<section><h2>Attack Runs</h2>{table_html}</section>",
            "<section><h2>Raw Result JSON</h2><pre>",
            html.escape(json.dumps(summary, indent=2)),
            "</pre></section></div></body></html>",
            "",
        ]
    )


def run_pyrit_scan(job_record: dict[str, Any]) -> dict[str, Any]:
    try:
        import pyrit  # noqa: F401
    except Exception as exc:  # pragma: no cover - environment-specific
        raise RuntimeError(f"PyRIT is not available in the active environment: {exc!r}") from exc

    config = job_record.get("configuration") or {}
    extra_options = config.get("extra_options") or {}
    reports_dir = _reports_root(job_record)
    runner_config = _resolve_pyrit_options(job_record)

    aggregate_runner_config_path = reports_dir / "runner_config.json"
    aggregate_runner_config_path.write_text(json.dumps(runner_config, indent=2) + "\n", encoding="utf-8")

    results_json_path = reports_dir / "results.json"
    report_html_path = reports_dir / "report.html"
    run_log_path = reports_dir / "run_log.txt"

    env = os.environ.copy()
    env.setdefault("PYTHONIOENCODING", "utf-8")
    # The PyRIT subprocess runs with cwd=attack_dir (a nested per-attack
    # output folder). That cwd does NOT put the repo root on sys.path, so
    # `-m whitebox_scan_platform.executors.pyrit_runner` fails with
    # ModuleNotFoundError. Inject the repo root into PYTHONPATH so the
    # shim package (and the split sentinel/ package) are both resolvable.
    repo_root = str(Path(__file__).resolve().parents[1])
    existing_pythonpath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (repo_root + (os.pathsep + existing_pythonpath if existing_pythonpath else ""))
    env[runner_config["endpoint_env_var"]] = runner_config["target_uri"]
    env[runner_config["model_env_var"]] = runner_config["model_name"]

    api_key_env_var = runner_config["api_key_env_var"]
    api_key_value = extra_options.get("pyrit_api_key")
    if api_key_value is not None and str(api_key_value).strip():
        env[api_key_env_var] = str(api_key_value)
    elif _looks_like_local_ollama_endpoint(runner_config["target_uri"]):
        env.setdefault(api_key_env_var, "ollama")

    attack_runs: list[dict[str, Any]] = []
    aggregate_logs: list[str] = []
    any_failed = False

    for index, attack_type in enumerate(runner_config.get("attack_types") or [runner_config["attack_type"]]):
        attack_dir = reports_dir / _attack_slug(attack_type, index)
        attack_dir.mkdir(parents=True, exist_ok=True)
        attack_config = dict(runner_config)
        attack_config["attack_type"] = attack_type
        attack_config_path = attack_dir / "runner_config.json"
        attack_results_json_path = attack_dir / "results.json"
        attack_report_html_path = attack_dir / "report.html"
        attack_run_log_path = attack_dir / "run_log.txt"
        attack_config_path.write_text(json.dumps(attack_config, indent=2) + "\n", encoding="utf-8")
        command = _build_command(
            runner_config_path=attack_config_path,
            results_json_path=attack_results_json_path,
            report_html_path=attack_report_html_path,
            run_log_path=attack_run_log_path,
        )
        completed = _run_subprocess(command=command, cwd=attack_dir, env=env)
        if completed.returncode != 0 and not attack_run_log_path.exists():
            combined_log = "\n".join(filter(None, [completed.stdout, completed.stderr])).strip()
            attack_run_log_path.write_text(combined_log + ("\n" if combined_log else ""), encoding="utf-8")

        if attack_results_json_path.exists():
            attack_summary = json.loads(attack_results_json_path.read_text(encoding="utf-8"))
        else:
            attack_summary = {
                "framework": "pyrit",
                "status": "failed" if completed.returncode else "completed",
                "job_id": job_record.get("job_id"),
                "job_name": job_record.get("job_name"),
                "target_uri": attack_config["target_uri"],
                "attack_type": attack_type,
                "objective": attack_config["objective"],
                "model_name": attack_config["model_name"],
                "generated_at_utc": _now_utc(),
            }
        attack_summary["return_code"] = completed.returncode
        attack_summary.setdefault("artifacts", {})
        attack_summary["artifacts"].update(
            {
                "report_html": str(attack_report_html_path.resolve()),
                "results_json": str(attack_results_json_path.resolve()),
                "run_log": str(attack_run_log_path.resolve()),
                "runner_config_json": str(attack_config_path.resolve()),
            }
        )
        if completed.returncode != 0:
            any_failed = True
            attack_summary["status"] = "failed"
            attack_summary["error"] = attack_summary.get("error") or f"PyRIT exited with code {completed.returncode}."
            attack_results_json_path.write_text(json.dumps(attack_summary, indent=2) + "\n", encoding="utf-8")
        if not attack_report_html_path.exists():
            _write_fallback_html(attack_report_html_path, attack_summary)
        if attack_run_log_path.exists():
            aggregate_logs.append(f"=== {attack_type} ===\n" + attack_run_log_path.read_text(encoding="utf-8", errors="replace").strip())
        attack_runs.append(attack_summary)

    summary: dict[str, Any] = {
        "framework": "pyrit",
        "profile": runner_config["profile"],
        "status": "failed" if any_failed else "completed",
        "job_id": job_record.get("job_id"),
        "job_name": job_record.get("job_name"),
        "target_uri": runner_config["target_uri"],
        "attack_type": runner_config["attack_type"],
        "attack_types": runner_config.get("attack_types") or [runner_config["attack_type"]],
        "objective": runner_config["objective"],
        "model_name": runner_config["model_name"],
        "max_attempts_on_failure": runner_config["max_attempts_on_failure"],
        "request_timeout_sec": runner_config["request_timeout_sec"],
        "many_shot_example_count": runner_config["many_shot_example_count"],
        "max_turns": runner_config["max_turns"],
        "max_backtracks": runner_config["max_backtracks"],
        "skeleton_key_prompt": runner_config["skeleton_key_prompt"],
        "adversarial_target_uri": runner_config["adversarial_target_uri"],
        "adversarial_model_name": runner_config["adversarial_model_name"],
        "expected_response": runner_config["expected_response"],
        "expected_responses": runner_config.get("expected_responses") or [],
        "forbidden_literals": runner_config.get("forbidden_literals") or [],
        "expected_max_words": runner_config.get("expected_max_words"),
        "expected_max_sentences": runner_config.get("expected_max_sentences"),
        "objective_scorer_mode": runner_config["objective_scorer_mode"],
        "seed_text": runner_config.get("seed_text") or "",
        "configured_seed_image_path": runner_config.get("configured_seed_image_path") or "",
        "seed_image_path": runner_config.get("seed_image_path") or "",
        "seed_image_source": runner_config.get("seed_image_source") or "",
        "follow_up_text": runner_config.get("follow_up_text") or "",
        "generated_at_utc": _now_utc(),
        "attack_runs": attack_runs,
    }
    primary_run = next((run for run in attack_runs if str(run.get("status")) == "completed"), attack_runs[0] if attack_runs else {})
    for key in (
        "conversation_id",
        "turn_count",
        "transcript",
        "printer_output",
        "result_metadata",
        "platform_evaluation",
        "outcome",
        "outcome_reason",
    ):
        if key in primary_run:
            summary[key] = primary_run.get(key)
    summary["return_code"] = 1 if any_failed else 0
    if any_failed:
        summary["error"] = "One or more PyRIT attacks failed."
    summary["tool_compatibility"] = framework_run_compatibility(
        "pyrit",
        job_record=job_record,
        decisions={
            "executor": "pyrit_runner_subprocess",
            "profile": runner_config["profile"],
            "attack_types": runner_config.get("attack_types") or [runner_config["attack_type"]],
            "target_endpoint_normalized": runner_config["target_uri"],
            "objective_scorer_mode": runner_config["objective_scorer_mode"],
        },
    )

    results_json_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    run_log_path.write_text("\n\n".join(part for part in aggregate_logs if part).strip() + ("\n" if aggregate_logs else ""), encoding="utf-8")
    report_html_path.write_text(_build_aggregate_html(summary), encoding="utf-8")

    artifacts = {
        "report_html": str(report_html_path.resolve()),
        "results_json": str(results_json_path.resolve()),
        "run_log": str(run_log_path.resolve()),
        "runner_config_json": str(aggregate_runner_config_path.resolve()),
    }
    for attack_run in attack_runs:
        attack_name = str(attack_run.get("attack_type") or "attack")
        attack_artifacts = attack_run.get("artifacts") or {}
        for artifact_key, artifact_value in attack_artifacts.items():
            artifacts[f"{attack_name}_{artifact_key}"] = artifact_value

    payload = {
        "status": summary.get("status", "unknown"),
        "framework": "pyrit",
        "profile": summary.get("profile", runner_config["profile"]),
        "message": "PyRIT run completed." if not any_failed else "PyRIT run failed.",
        "target_uri": summary.get("target_uri") or runner_config["target_uri"],
        "attack_type": summary.get("attack_type") or runner_config["attack_type"],
        "attack_types": summary.get("attack_types") or runner_config.get("attack_types") or [runner_config["attack_type"]],
        "objective": summary.get("objective") or runner_config["objective"],
        "model_name": summary.get("model_name") or runner_config["model_name"],
        "max_attempts_on_failure": summary.get("max_attempts_on_failure", runner_config["max_attempts_on_failure"]),
        "request_timeout_sec": summary.get("request_timeout_sec", runner_config["request_timeout_sec"]),
        "many_shot_example_count": summary.get("many_shot_example_count", runner_config["many_shot_example_count"]),
        "max_turns": summary.get("max_turns", runner_config["max_turns"]),
        "max_backtracks": summary.get("max_backtracks", runner_config["max_backtracks"]),
        "skeleton_key_prompt": summary.get("skeleton_key_prompt", runner_config["skeleton_key_prompt"]),
        "adversarial_target_uri": summary.get("adversarial_target_uri", runner_config["adversarial_target_uri"]),
        "adversarial_model_name": summary.get("adversarial_model_name", runner_config["adversarial_model_name"]),
        "expected_response": summary.get("expected_response", runner_config["expected_response"]),
        "expected_responses": summary.get("expected_responses", runner_config.get("expected_responses") or []),
        "forbidden_literals": summary.get("forbidden_literals", runner_config.get("forbidden_literals") or []),
        "expected_max_words": summary.get("expected_max_words", runner_config.get("expected_max_words")),
        "expected_max_sentences": summary.get("expected_max_sentences", runner_config.get("expected_max_sentences")),
        "objective_scorer_mode": summary.get("objective_scorer_mode", runner_config["objective_scorer_mode"]),
        "seed_text": summary.get("seed_text", runner_config.get("seed_text") or ""),
        "configured_seed_image_path": summary.get("configured_seed_image_path", runner_config.get("configured_seed_image_path") or ""),
        "seed_image_path": summary.get("seed_image_path", runner_config.get("seed_image_path") or ""),
        "seed_image_source": summary.get("seed_image_source", runner_config.get("seed_image_source") or ""),
        "follow_up_text": summary.get("follow_up_text", runner_config.get("follow_up_text") or ""),
        "conversation_id": summary.get("conversation_id"),
        "turn_count": summary.get("turn_count"),
        "outcome": (summary.get("result_metadata") or {}).get("outcome"),
        "outcome_reason": (summary.get("result_metadata") or {}).get("outcome_reason"),
        "platform_verdict": (summary.get("platform_evaluation") or {}).get("verdict"),
        "platform_severity": (summary.get("platform_evaluation") or {}).get("severity"),
        "tool_compatibility": summary["tool_compatibility"],
        "attack_runs": [
            {
                "attack_type": attack_run.get("attack_type"),
                "status": attack_run.get("status"),
                "target_uri": attack_run.get("target_uri"),
                "platform_verdict": (attack_run.get("platform_evaluation") or {}).get("verdict"),
                "platform_severity": (attack_run.get("platform_evaluation") or {}).get("severity"),
                "outcome": (attack_run.get("result_metadata") or {}).get("outcome"),
                "outcome_reason": (attack_run.get("result_metadata") or {}).get("outcome_reason"),
                "artifacts": attack_run.get("artifacts") or {},
            }
            for attack_run in attack_runs
        ],
        "artifacts": artifacts,
    }
    if any_failed:
        payload["error"] = summary.get("error") or "One or more PyRIT attacks failed."
    return payload
