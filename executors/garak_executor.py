from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import html
import importlib.util
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..compatibility import framework_run_compatibility
from .garak_ollama_function import TARGET_ERROR_PREFIX


def _now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _reports_root(job_record: dict[str, Any]) -> Path:
    job_id = str(job_record.get("job_id", "adhoc"))
    root = Path(__file__).resolve().parents[1] / "data" / "garak_runs" / job_id / "reports"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _coerce_json_mapping(value: Any, *, field_name: str) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    raise ValueError(f"Expected '{field_name}' to be a JSON object.")


def _looks_like_ollama_generate_endpoint(endpoint_uri: str) -> bool:
    value = str(endpoint_uri or "").strip().lower()
    if not value:
        return False
    return "/api/generate" in value and ("127.0.0.1:11434" in value or "localhost:11434" in value)


def _garak_rest_generator_available() -> bool:
    return importlib.util.find_spec("garak.generators.rest") is not None


def _use_ollama_function_bridge(job_record: dict[str, Any], endpoint_uri: str) -> bool:
    extra_options = (job_record.get("configuration") or {}).get("extra_options") or {}
    model_type = str(extra_options.get("garak_model_type") or "").strip().lower()
    if model_type:
        return model_type == "function.single"
    return _looks_like_ollama_generate_endpoint(endpoint_uri) and not _garak_rest_generator_available()


def _resolve_cli_generator(job_record: dict[str, Any], endpoint_uri: str) -> tuple[str, str]:
    model = job_record.get("model") or {}
    extra_options = (job_record.get("configuration") or {}).get("extra_options") or {}
    model_type = str(extra_options.get("garak_model_type") or "").strip()
    if _use_ollama_function_bridge(job_record, endpoint_uri):
        return (
            model_type or "function.Single",
            str(extra_options.get("garak_model_name") or "whitebox_scan_platform.executors.garak_ollama_function#generate"),
        )
    return (
        model_type or "rest",
        str(extra_options.get("garak_model_name") or endpoint_uri or model.get("source_value") or model.get("model_id") or ""),
    )


def _apply_ollama_rest_defaults(rest_options: dict[str, Any]) -> None:
    request_template = rest_options.get("req_template_json_object")
    if not isinstance(request_template, dict):
        request_template = {}

    if request_template.get("input") == "$INPUT" and "prompt" not in request_template:
        request_template["prompt"] = request_template.pop("input")
    if "prompt" not in request_template and "input" not in request_template:
        request_template["prompt"] = "$INPUT"
    if "stream" not in request_template:
        request_template["stream"] = False

    rest_options["req_template_json_object"] = request_template
    rest_options["response_json"] = True

    response_field = str(rest_options.get("response_json_field") or "").strip()
    if not response_field or response_field == "text":
        rest_options["response_json_field"] = "response"


def _resolve_generator_options(job_record: dict[str, Any]) -> tuple[dict[str, Any], str]:
    model = job_record.get("model") or {}
    extra_options = (job_record.get("configuration") or {}).get("extra_options") or {}
    model_type = str(extra_options.get("garak_model_type") or "").strip()
    if model_type and not model_type.lower().startswith("rest"):
        model_name = str(extra_options.get("garak_model_name") or model.get("source_value") or model.get("model_id") or "").strip()
        if not model_name:
            raise ValueError("Garak non-REST generator requires garak_model_name or model.source_value.")
        return {}, model_name

    configured = extra_options.get("garak_generator_options")
    if configured is not None:
        configured_map = _coerce_json_mapping(configured, field_name="garak_generator_options")
        if "rest.RestGenerator" in configured_map:
            generator_options = configured_map
        else:
            generator_options = {"rest.RestGenerator": configured_map}
        endpoint_uri = str(
            generator_options["rest.RestGenerator"].get("uri")
            or extra_options.get("garak_endpoint_uri")
            or model.get("source_value")
            or ""
        ).strip()
    else:
        endpoint_uri = str(
            extra_options.get("garak_endpoint_uri")
            or extra_options.get("endpoint_uri")
            or model.get("source_value")
            or ""
        ).strip()
        if not endpoint_uri:
            raise ValueError(
                "Garak requires an endpoint URI. Set model.source_value or configuration.extra_options.garak_endpoint_uri."
            )

        headers = _coerce_json_mapping(extra_options.get("garak_headers"), field_name="garak_headers")
        if not headers:
            headers = {"Content-Type": "application/json"}

        request_template = extra_options.get("garak_request_template_json_object")
        if request_template is None:
            request_template = {"input": "$INPUT"}
        elif not isinstance(request_template, dict):
            raise ValueError("Expected 'garak_request_template_json_object' to be a JSON object.")

        generator_options = {
            "rest.RestGenerator": {
                "name": str(extra_options.get("garak_target_name") or model.get("model_id") or endpoint_uri),
                "uri": endpoint_uri,
                "method": str(extra_options.get("garak_http_method") or "post").lower(),
                "headers": headers,
                "req_template_json_object": request_template,
                "response_json": bool(extra_options.get("garak_response_json", True)),
                "response_json_field": str(extra_options.get("garak_response_json_field") or "text"),
                "response_timeout": int(extra_options.get("garak_response_timeout") or 30),
                "key_env_var": str(extra_options.get("garak_api_key_env_var") or "REST_API_KEY"),
            }
        }

    rest_options = generator_options.get("rest.RestGenerator") or {}
    if not endpoint_uri:
        endpoint_uri = str(rest_options.get("uri") or "").strip()
    if not endpoint_uri:
        raise ValueError("Garak REST generator configuration must include a target URI.")
    if _looks_like_ollama_generate_endpoint(endpoint_uri):
        _apply_ollama_rest_defaults(rest_options)
        generator_options["rest.RestGenerator"] = rest_options
    return generator_options, endpoint_uri


def _resolve_probe_spec(job_record: dict[str, Any]) -> str:
    extra_options = (job_record.get("configuration") or {}).get("extra_options") or {}
    probe_spec = str(extra_options.get("garak_probes") or extra_options.get("garak_probe_spec") or "").strip()
    if probe_spec:
        return probe_spec
    return "test.Blank"


def _build_command(
    *,
    job_record: dict[str, Any],
    generator_option_file: Path,
    report_prefix: Path,
    endpoint_uri: str,
) -> list[str]:
    config = job_record.get("configuration") or {}
    extra_options = config.get("extra_options") or {}
    model_type, model_name = _resolve_cli_generator(job_record, endpoint_uri)
    command = [
        sys.executable,
        "-m",
        "whitebox_scan_platform.executors.garak_runner",
        "--model_type",
        model_type,
        "--model_name",
        model_name,
    ]

    command.extend(
        [
        "--report_prefix",
        str(report_prefix),
        "--probes",
        _resolve_probe_spec(job_record),
        ]
    )

    detectors = str(extra_options.get("garak_detectors") or "").strip()
    if detectors:
        command.extend(["--detectors", detectors])

    generations = int(extra_options.get("garak_generations") or config.get("batch_size") or 1)
    if generations > 0:
        command.extend(["--generations", str(generations)])

    seed_value = extra_options.get("garak_seed")
    if seed_value is not None and str(seed_value).strip():
        command.extend(["--seed", str(seed_value)])

    eval_threshold = extra_options.get("garak_eval_threshold")
    if eval_threshold is not None and str(eval_threshold).strip():
        command.extend(["--eval_threshold", str(eval_threshold)])

    return command


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


def _summarize_jsonl_report(report_path: Path) -> dict[str, Any]:
    entry_counts: Counter[str] = Counter()
    json_decode_errors = 0
    total_entries = 0
    prompt_count = 0
    output_count = 0
    target_error_count = 0

    for raw_line in report_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        total_entries += 1
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            json_decode_errors += 1
            continue
        entry_type = str(payload.get("entry_type") or "unknown")
        entry_counts[entry_type] += 1
        if "prompt" in payload:
            prompt_count += 1
        outputs = payload.get("outputs")
        if isinstance(outputs, list):
            output_count += len(outputs)
            target_error_count += sum(1 for output in outputs if TARGET_ERROR_PREFIX in str(output))
        elif outputs:
            output_count += 1
            if TARGET_ERROR_PREFIX in str(outputs):
                target_error_count += 1

    return {
        "total_entries": total_entries,
        "entry_counts": dict(entry_counts),
        "prompt_count": prompt_count,
        "output_count": output_count,
        "target_error_count": target_error_count,
        "json_decode_errors": json_decode_errors,
    }


def _write_fallback_html(destination: Path, summary: dict[str, Any]) -> None:
    destination.write_text(
        "\n".join(
            [
                "<!DOCTYPE html>",
                "<html lang='en'><head><meta charset='utf-8' /><meta name='viewport' content='width=device-width, initial-scale=1' />",
                "<title>Garak Report</title>",
                "<style>",
                "/* Bharath Srinivasan | Sentinel Defense Garak report presentation. Proprietary material. */",
                ":root { --bg: #07111f; --panel: rgba(11, 23, 39, 0.94); --ink: #eef7ff; --ink-soft: #a9bfd6; --line: rgba(112, 170, 221, 0.16); }",
                "body { margin: 0; font-family: 'Avenir Next', 'Segoe UI', sans-serif; color: var(--ink); background: radial-gradient(circle at top left, rgba(47, 182, 255, 0.16), transparent 24%), linear-gradient(180deg, #040a14 0%, #081323 46%, #0a1729 100%); }",
                ".page { max-width: 1180px; margin: 0 auto; padding: 24px; }",
                ".hero, section { background: var(--panel); border: 1px solid var(--line); border-radius: 18px; box-shadow: 0 22px 54px rgba(2, 7, 15, 0.34); }",
                ".hero { padding: 24px; margin-bottom: 16px; background: linear-gradient(135deg, #071323 0%, #0d233e 38%, #103157 72%, #0a6db3 100%); }",
                "section { padding: 18px; }",
                "pre { white-space: pre-wrap; word-break: break-word; background: rgba(4, 11, 21, 0.96); color: #d8f3dc; border: 1px solid var(--line); border-radius: 12px; padding: 12px; }",
                "</style></head><body><div class='page'>",
                f"<header class='hero'><h1>Garak Report</h1><p>Status: {html.escape(str(summary.get('status', 'unknown')))}</p><p>Target URI: {html.escape(str(summary.get('target_uri', '')))}</p><p>Probe Spec: {html.escape(str(summary.get('probe_spec', '')))}</p></header>",
                "<section><h2>Raw Result JSON</h2><pre>",
                html.escape(json.dumps(summary, indent=2)),
                "</pre></section></div></body></html>",
                "",
            ]
        ),
        encoding="utf-8",
    )


def run_garak_scan(job_record: dict[str, Any]) -> dict[str, Any]:
    try:
        import garak  # noqa: F401
    except Exception as exc:  # pragma: no cover - environment-specific
        raise RuntimeError(f"Garak is not available in the active environment: {exc!r}") from exc

    config = job_record.get("configuration") or {}
    extra_options = config.get("extra_options") or {}
    reports_dir = _reports_root(job_record)
    endpoint_config, endpoint_uri = _resolve_generator_options(job_record)
    generator_option_file = reports_dir / "generator_options.json"
    generator_option_file.write_text(json.dumps(endpoint_config, indent=2) + "\n", encoding="utf-8")

    report_prefix = reports_dir / "garak"
    command = _build_command(
        job_record=job_record,
        generator_option_file=generator_option_file,
        report_prefix=report_prefix,
        endpoint_uri=endpoint_uri,
    )
    cli_generator_type, _ = _resolve_cli_generator(job_record, endpoint_uri)
    used_function_bridge = _use_ollama_function_bridge(job_record, endpoint_uri)

    env = os.environ.copy()
    env.setdefault("PYTHONIOENCODING", "utf-8")
    project_parent = str(Path(__file__).resolve().parents[2])
    env["PYTHONPATH"] = project_parent + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    bridge_endpoint = str(
        extra_options.get("garak_endpoint_uri")
        or extra_options.get("endpoint_uri")
        or (job_record.get("model") or {}).get("source_value")
        or "http://127.0.0.1:11434/api/generate"
    )
    env["GARAK_OLLAMA_ENDPOINT"] = str(
        bridge_endpoint
    )
    env["GARAK_OLLAMA_MODEL"] = str(
        extra_options.get("garak_ollama_model")
        or (job_record.get("model") or {}).get("model_id")
        or "tinyllama:1.1b-chat"
    )
    if extra_options.get("garak_response_timeout"):
        env["GARAK_OLLAMA_TIMEOUT"] = str(extra_options["garak_response_timeout"])
    if extra_options.get("garak_ollama_num_predict"):
        env["GARAK_OLLAMA_NUM_PREDICT"] = str(extra_options["garak_ollama_num_predict"])
    rest_options = endpoint_config.get("rest.RestGenerator") or {}
    api_key_env_var = str(rest_options.get("key_env_var") or "REST_API_KEY")
    api_key_value = extra_options.get("garak_api_key")
    if api_key_value is not None and str(api_key_value).strip():
        env[api_key_env_var] = str(api_key_value)

    completed = _run_subprocess(command=command, cwd=reports_dir, env=env)

    run_log = reports_dir / "run_log.txt"
    combined_log = "\n".join(filter(None, [completed.stdout, completed.stderr])).strip()
    if combined_log:
        run_log.write_text(combined_log + "\n", encoding="utf-8")
    else:
        run_log.write_text("", encoding="utf-8")

    raw_report = reports_dir / "report.jsonl"
    summary_html = reports_dir / "report.html"
    framework_log = reports_dir / "garak.log"

    generated_report = reports_dir / "garak.report.jsonl"
    generated_html = reports_dir / "garak.report.html"
    generated_log = reports_dir / "garak.log"

    _copy_if_present(generated_report, raw_report)
    if generated_log.exists() and generated_log.is_file() and generated_log.resolve() != framework_log.resolve():
        shutil.copy2(generated_log, framework_log)

    summary: dict[str, Any] = {
        "framework": "garak",
        "status": "completed" if completed.returncode == 0 else "failed",
        "job_id": job_record.get("job_id"),
        "job_name": job_record.get("job_name"),
        "target_uri": env["GARAK_OLLAMA_ENDPOINT"] if used_function_bridge else endpoint_uri,
        "generator_type": cli_generator_type,
        "probe_spec": _resolve_probe_spec(job_record),
        "command": command,
        "return_code": completed.returncode,
        "generated_at_utc": _now_utc(),
        "tool_compatibility": framework_run_compatibility(
            "garak",
            job_record=job_record,
            decisions={
                "executor": "garak_cli_runner",
                "generator_type": cli_generator_type,
                "used_ollama_function_bridge": used_function_bridge,
                "unsupported_flags_avoided": ["--generator_option_file", "--narrow_output"],
                "target_error_marker": TARGET_ERROR_PREFIX,
            },
        ),
    }
    if raw_report.exists():
        summary["report_summary"] = _summarize_jsonl_report(raw_report)
    if completed.returncode != 0:
        summary["error"] = f"Garak exited with code {completed.returncode}."
    elif (summary.get("report_summary") or {}).get("target_error_count"):
        summary["warning"] = "One or more target generations returned a structured Garak target error."

    results_json = reports_dir / "results.json"
    results_json.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    _write_fallback_html(summary_html, summary)

    artifacts = {
        "report_html": str(summary_html.resolve()),
        "results_json": str(results_json.resolve()),
        "run_log": str(run_log.resolve()),
        "report_jsonl": str(raw_report.resolve()) if raw_report.exists() else "",
        "generator_option_file": str(generator_option_file.resolve()),
    }
    if generated_html.exists():
        artifacts["native_report_html"] = str(generated_html.resolve())
    if framework_log.exists():
        artifacts["garak_log"] = str(framework_log.resolve())

    payload = {
        "status": summary["status"],
        "framework": "garak",
        "message": "Garak CLI run completed." if completed.returncode == 0 else "Garak CLI run failed.",
        "target_uri": summary["target_uri"],
        "probe_spec": summary["probe_spec"],
        "tool_compatibility": summary["tool_compatibility"],
        "artifacts": {key: value for key, value in artifacts.items() if value},
    }
    if completed.returncode != 0:
        payload["error"] = summary["error"]
    if summary.get("warning"):
        payload["warning"] = summary["warning"]
    return payload
