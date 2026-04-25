"""Job lifecycle + wrapper management + artifact collection.

Extracted from executor.py during the responsibility split (Task 7). Call sites
that still import from sentinel.executor keep working via a re-export shim at
the bottom of executor.py.

Notes on circular imports:
  - execute_job_record (the core orchestrator) stays in executor.py and calls
    back into this module's primitives via lazy lookup.
  - This module imports BUILTIN_WRAPPERS, _load_adapter, now_utc, model_dump,
    framework_runtime_inventory, default_options, and the reporting-layer
    orchestrators from executor.py lazily inside function bodies so module
    load never triggers a cycle.
"""
from __future__ import annotations

import importlib.util
import json
import mimetypes
import re
import shutil
import threading
import traceback
import uuid
from pathlib import Path
from typing import Any, Optional

from .compatibility import framework_compatibility_inventory
from .contracts import BaseScanAdapter
from .executors.art_executor import run_art_scan
from .executors.foolbox_executor import run_foolbox_scan
from .executors.garak_executor import run_garak_scan
from .executors.pyrit_executor import run_pyrit_scan
from .executors.textattack_executor import run_textattack_scan
from .framework_registry import (
    FRAMEWORK_CAPABILITY_FLAGS,
    default_framework_order,
    framework_supported,
)
from .reporting.normalized import (
    _build_normalized_severity_payload,
    _normalized_severity_paths,
    _write_normalized_severity_artifacts,
)
from .schemas import ScanJobCreate, ScanJobRecord, WrapperRegistration
from .storage import (
    JOB_WRITE_LOCK,
    JOBS_DIR,
    WRAPPERS_DIR,
    ensure_dirs,
    load_job,
    load_wrapper_code,
    load_wrapper_index,
    read_json,
    save_job,
    save_wrapper_file,
    save_wrapper_index,
)


def now_utc() -> str:
    """Local helper — mirrors executor.now_utc so jobs.py doesn't depend on
    executor at module import time (executor imports us via the facade shim)."""
    from time import gmtime, strftime
    return strftime("%Y-%m-%dT%H:%M:%SZ", gmtime())


def model_dump(data: Any) -> dict[str, Any]:
    if hasattr(data, "model_dump"):
        return data.model_dump()
    if hasattr(data, "dict"):
        return data.dict()
    if isinstance(data, dict):
        return data
    raise TypeError(f"Cannot dump payload of type {type(data).__name__}")


# Lazy accessors for executor.py-resident helpers. executor.py imports us via
# the re-export shim at its bottom, so doing `from .executor import X` at
# module load here would create a cycle. Calling these at function-body time
# is safe because executor.py has finished loading by then.
def _executor_attr(name: str):
    from . import executor
    return getattr(executor, name)


def execute_job_record(job_record: dict[str, Any]) -> dict[str, Any]:
    return _executor_attr("execute_job_record")(job_record)


def _mode_reports_dir(job_id: str) -> Path:
    return _executor_attr("_mode_reports_dir")(job_id)


def _mode_summary_paths(job_id: str, mode: str) -> dict[str, Path]:
    return _executor_attr("_mode_summary_paths")(job_id, mode)


def _write_mode_summary_reports(*args, **kwargs):
    return _executor_attr("_write_mode_summary_reports")(*args, **kwargs)


def framework_runtime_inventory() -> dict[str, Any]:
    return _executor_attr("framework_runtime_inventory")()


def _load_adapter(wrapper_id: str):
    return _executor_attr("_load_adapter")(wrapper_id)


# TASK_FAMILY_ALIASES is a module-level constant in executor.py. We access
# it via a property-like callable that dereferences on every call.
def _task_family_aliases() -> dict[str, str]:
    return _executor_attr("TASK_FAMILY_ALIASES")


# Task 8: module-level cache for sync_builtin_wrappers() lives here now.
_WRAPPER_CACHE: list[dict[str, Any]] | None = None
_WRAPPER_CACHE_LOCK = threading.Lock()


def _now_utc() -> str:
    from time import gmtime, strftime
    return strftime("%Y-%m-%dT%H:%M:%SZ", gmtime())


def _dump(payload: Any) -> dict[str, Any]:
    if hasattr(payload, "model_dump"):
        return payload.model_dump()
    if hasattr(payload, "dict"):
        return payload.dict()
    if isinstance(payload, dict):
        return payload
    raise TypeError(f"Cannot dump payload of type {type(payload).__name__}")



def _valid_wrapper_record(row: dict[str, Any]) -> bool:
    wrapper_id = str(row.get("wrapper_id", "")).strip()
    display_name = str(row.get("display_name", "")).strip()
    class_name = str(row.get("class_name", "")).strip()
    file_path = str(row.get("file_path", "")).strip()
    return all([wrapper_id, display_name, class_name, file_path])


def _invalidate_wrapper_cache() -> None:
    global _WRAPPER_CACHE
    with _WRAPPER_CACHE_LOCK:
        _WRAPPER_CACHE = None


def register_wrapper(payload: WrapperRegistration) -> dict[str, Any]:
    ensure_dirs()
    wrapper_id = payload.wrapper_id.strip()
    display_name = payload.display_name.strip()
    class_name = payload.class_name.strip()
    path = save_wrapper_file(wrapper_id, payload.code)
    index = load_wrapper_index()
    wrappers = [row for row in index.get("wrappers", []) if row.get("wrapper_id") != wrapper_id]
    capabilities = {
        "supports_blackbox": payload.supports_blackbox,
        "supports_whitebox": payload.supports_whitebox,
        "supports_api_models": payload.supports_api_models,
        "supports_python_process_models": payload.supports_python_process_models,
        "supports_art": payload.supports_art,
        "supports_foolbox": payload.supports_foolbox,
        "supports_pyrit": payload.supports_pyrit,
        "supports_garak": payload.supports_garak,
        "supports_textattack": payload.supports_textattack,
        "supports_logits": payload.supports_logits,
        "supports_gradients": payload.supports_gradients,
        "supported_modalities": payload.supported_modalities,
        "supported_task_families": payload.supported_task_families,
        "supported_frameworks": payload.supported_frameworks,
        "notes": payload.notes,
    }
    wrappers.append(
        {
            "wrapper_id": wrapper_id,
            "display_name": display_name,
            "class_name": class_name,
            "file_path": str(path),
            "capabilities": capabilities,
        }
    )
    save_wrapper_index({"wrappers": wrappers})
    _invalidate_wrapper_cache()  # Task 8: force resync on next list_wrappers()
    return wrappers[-1]


def sync_builtin_wrappers(*, force: bool = False) -> list[dict[str, Any]]:
    global _WRAPPER_CACHE
    if not force:
        with _WRAPPER_CACHE_LOCK:
            if _WRAPPER_CACHE is not None:
                return list(_WRAPPER_CACHE)
    # Task 7: BUILTIN_WRAPPERS still lives in executor.py; import lazily so we
    # don't create a circular import at module load time (executor imports jobs,
    # jobs imports back from executor only when this function is actually called).
    from .executor import BUILTIN_WRAPPERS
    ensure_dirs()
    index = load_wrapper_index()
    wrappers = [row for row in index.get("wrappers", []) if _valid_wrapper_record(row)]
    wrapper_map = {row["wrapper_id"]: row for row in wrappers}

    for row in BUILTIN_WRAPPERS:
        if row["wrapper_id"] in wrapper_map:
            continue
        path = Path(row["file_path"])
        if not path.exists():
            continue
        spec = importlib.util.spec_from_file_location(f"builtin_wrapper_{row['wrapper_id']}", path)
        if spec is None or spec.loader is None:
            continue
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        cls = getattr(module, row["class_name"])
        instance = cls()
        capabilities = instance.capabilities()
        wrappers.append(
            {
                "wrapper_id": capabilities.wrapper_id,
                "display_name": capabilities.display_name,
                "class_name": row["class_name"],
                "file_path": str(path),
                "capabilities": {
                    "supports_blackbox": capabilities.supports_blackbox,
                    "supports_whitebox": capabilities.supports_whitebox,
                    "supports_api_models": capabilities.supports_api_models,
                    "supports_python_process_models": capabilities.supports_python_process_models,
                    "supports_art": capabilities.supports_art,
                    "supports_foolbox": capabilities.supports_foolbox,
                    "supports_pyrit": capabilities.supports_pyrit,
                    "supports_garak": capabilities.supports_garak,
                    "supports_textattack": capabilities.supports_textattack,
                    "supports_logits": capabilities.supports_logits,
                    "supports_gradients": capabilities.supports_gradients,
                    "supported_modalities": capabilities.supported_modalities,
                    "supported_task_families": capabilities.supported_task_families,
                    "supported_frameworks": capabilities.supported_frameworks,
                    "notes": capabilities.notes,
                    "builtin": True,
                },
            }
        )
    save_wrapper_index({"wrappers": wrappers})
    with _WRAPPER_CACHE_LOCK:
        # Store a deep-ish copy: callers mutate rows for response shaping
        # (e.g. adding installed_versions), so the cache must not be aliased.
        _WRAPPER_CACHE = [dict(row) for row in wrappers]
        return list(_WRAPPER_CACHE)


def list_wrappers() -> list[dict[str, Any]]:
    ensure_dirs()
    wrappers = sync_builtin_wrappers()
    # Task 1: decorate each wrapper record with installed_versions so the UI's
    # Version column can resolve "Not Installed" vs a real version per framework.
    # We compute lazily (once per call) from the compatibility inventory so the
    # on-disk wrapper index stays stable/portable — version data is derived, not
    # stored.
    compat = framework_compatibility_inventory(default_framework_order())
    decorated: list[dict[str, Any]] = []
    for row in wrappers:
        if not _valid_wrapper_record(row):
            continue
        enriched = dict(row)
        capabilities = dict(enriched.get("capabilities") or {})
        frameworks = list(capabilities.get("supported_frameworks") or [])
        versions: dict[str, str] = {}
        for fw in frameworks:
            installed_ver = str((compat.get(fw) or {}).get("installed_version") or "")
            versions[fw] = installed_ver
        enriched["installed_versions"] = versions
        # Convenience scalar for single-framework wrappers / legacy UI bindings.
        if len(frameworks) == 1:
            enriched["installed_version"] = versions.get(frameworks[0], "")
        else:
            enriched["installed_version"] = ""
        decorated.append(enriched)
    return decorated


def build_execution_plan(job: ScanJobCreate, wrapper_meta: Optional[dict[str, Any]]) -> dict[str, Any]:
    config = job.configuration
    modes = set(config.scan_modes)
    frameworks = set(config.frameworks)
    backend = config.execution_backend
    plan: list[str] = []
    warnings: list[str] = []

    if "whitebox" in modes and backend == "api_based" and not job.wrapper_id:
        warnings.append("White-box over a plain API backend requires a custom wrapper/adapter or a local model plugin.")

    if "art" in frameworks:
        plan.append("Inventory all ART attacks and classify them as RUN / skipped / blocked based on adapter capabilities.")
    if "foolbox" in frameworks:
        plan.append("Prepare Foolbox model boundary if the adapter exposes logits/gradients or a native model object.")
    if "pyrit" in frameworks:
        plan.append("Run PyRIT attacks through the built-in OpenAI-compatible chat target path when the selected endpoint matches the supported conversational boundary.")
    if "garak" in frameworks:
        plan.append("Run Garak probe suites through the built-in API-target executor when the selected endpoint matches the supported conversational path.")
    if "textattack" in frameworks:
        plan.append("Run the built-in TextAttack path for python-process-wrapped text-classification models using the narrow certified recipe set for the first landing.")

    if backend == "api_based":
        plan.append("Use the configured API-compatible model route for black-box inference.")
    else:
        plan.append("Use the configured Python-process wrapper for in-process model loading and advanced white-box access.")

    if wrapper_meta:
        plan.append(f"Use wrapper '{wrapper_meta['wrapper_id']}' with saved capability metadata.")

    return {
        "execution_backend": backend,
        "scan_modes": sorted(modes),
        "frameworks": sorted(frameworks),
        "steps": plan,
        "warnings": warnings,
    }


def normalize_task_family(task_family: str) -> str:
    cleaned = str(task_family or "").strip().lower()
    return _task_family_aliases().get(cleaned, cleaned)


def _path_matches_job(path_spec: dict[str, Any], job: ScanJobCreate) -> bool:
    config = job.configuration
    model = job.model
    requested_modes = set(config.scan_modes)
    supported_modes = set(path_spec.get("scan_modes") or [])
    supported_modalities = {str(value).strip().lower() for value in (path_spec.get("modalities") or [])}
    supported_task_families = {normalize_task_family(value) for value in (path_spec.get("task_families") or [])}
    requested_modality = str(model.modality or "").strip().lower()
    requested_task_family = normalize_task_family(model.task_family)
    return (
        config.execution_backend == path_spec.get("backend")
        and requested_modes.issubset(supported_modes)
        and (not supported_modalities or requested_modality in supported_modalities)
        and (not supported_task_families or requested_task_family in supported_task_families)
    )


def _mirror_mode_runtime_artifacts(job_record: dict[str, Any], mode: str, mode_result: dict[str, Any]) -> dict[str, str]:
    job_id = str(job_record.get("job_id", "unknown"))
    reports_dir = _mode_reports_dir(job_id)
    reports_dir.mkdir(parents=True, exist_ok=True)

    artifacts = dict(mode_result.get("artifacts") or {})
    candidates = [
        ("source_report_html", artifacts.get(f"{mode}_report_html") or artifacts.get("report_html"), reports_dir / f"{mode}_source_report.html"),
        ("source_results_json", artifacts.get(f"{mode}_results_json") or artifacts.get("results_json"), reports_dir / f"{mode}_source_results.json"),
        ("source_run_log", artifacts.get(f"{mode}_run_log") or artifacts.get("run_log"), reports_dir / f"{mode}_source_run_log.txt"),
    ]

    mirrored: dict[str, str] = {}
    for key, source_path, target_path in candidates:
        if not source_path:
            continue
        source = Path(str(source_path)).expanduser()
        if not source.exists() or not source.is_file():
            continue
        target = target_path.resolve()
        if source.resolve() != target:
            shutil.copy2(source, target)
        mirrored[key] = str(target)
    return mirrored


def _attach_mode_summary_artifacts(job_record: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    for mode in ("blackbox", "whitebox"):
        mode_result = result.get(mode)
        if not isinstance(mode_result, dict):
            continue
        normalized_payload = _build_normalized_severity_payload(job_record, result, mode, mode_result)
        mode_result["normalized_severity"] = normalized_payload
        mirrored = _mirror_mode_runtime_artifacts(job_record, mode, mode_result)
        summary_paths = _mode_summary_paths(str(job_record.get("job_id", "unknown")), mode)
        normalized_paths = _normalized_severity_paths(str(job_record.get("job_id", "unknown")), mode)
        original_artifacts = dict(mode_result.get("artifacts") or {})
        artifacts: dict[str, str] = {
            key: str(path.resolve())
            for key, path in summary_paths.items()
        }
        artifacts.update(mirrored)
        artifacts.update(_write_normalized_severity_artifacts(job_record, mode, normalized_payload, normalized_paths))
        for key, value in original_artifacts.items():
            if key in {"report_html", "results_json", "run_log"}:
                continue
            artifacts.setdefault(key, value)
        mode_result["artifacts"] = artifacts
        _write_mode_summary_reports(job_record, result, mode, mode_result, summary_paths)
    return result


def _artifact_name_for_path(path: Path, source_group: str) -> str:
    filename = path.name
    if source_group == "job_reports":
        summary_names = {
            "blackbox_source_report.html": "source_report_html",
            "blackbox_source_results.json": "source_results_json",
            "blackbox_source_run_log.txt": "source_run_log",
            "blackbox_summary_report.html": "summary_report_html",
            "blackbox_summary_results.json": "summary_results_json",
            "blackbox_summary_run_log.txt": "summary_run_log",
            "blackbox_normalized_severity.html": "normalized_severity_report_html",
            "blackbox_normalized_severity.json": "normalized_severity_results_json",
            "blackbox_normalized_severity_log.txt": "normalized_severity_run_log",
            "whitebox_source_report.html": "source_report_html",
            "whitebox_source_results.json": "source_results_json",
            "whitebox_source_run_log.txt": "source_run_log",
            "whitebox_summary_report.html": "summary_report_html",
            "whitebox_summary_results.json": "summary_results_json",
            "whitebox_summary_run_log.txt": "summary_run_log",
            "whitebox_normalized_severity.html": "normalized_severity_report_html",
            "whitebox_normalized_severity.json": "normalized_severity_results_json",
            "whitebox_normalized_severity_log.txt": "normalized_severity_run_log",
        }
        if filename in summary_names:
            return summary_names[filename]
    common = {
        "report.html": "report_html",
        "results.json": "results_json",
        "run_log.txt": "run_log",
        "blackbox_report.html": "report_html",
        "blackbox_results.json": "results_json",
        "blackbox_run_log.txt": "run_log",
        "whitebox_report.html": "report_html",
        "whitebox_results.json": "results_json",
        "whitebox_run_log.txt": "run_log",
    }
    if filename in common:
        return common[filename]
    if path.suffix.lower() == ".html":
        return f"{path.stem}_html"
    if path.suffix.lower() == ".json":
        return f"{path.stem}_json"
    return path.stem


def _artifact_group_for_path(path: Path, source_group: str) -> str:
    filename = path.name
    if filename.startswith("blackbox_"):
        return "blackbox"
    if filename.startswith("whitebox_"):
        return "whitebox"
    if source_group == "art_runs":
        return "framework:art"
    if source_group == "foolbox_runs":
        return "framework:foolbox"
    if source_group == "garak_runs":
        return "framework:garak"
    if source_group == "pyrit_runs":
        return "framework:pyrit"
    if source_group == "textattack_runs":
        return "framework:textattack"
    if source_group == "ocr_runs":
        return "ocr"
    if source_group == "test_runs":
        return "framework:test"
    return "job"


def _normalize_artifact_name(group: str, name: str, path: Path) -> str:
    try:
        resolved = path.resolve()
    except OSError:
        resolved = path
    path_text = str(resolved)
    if "/data/job_reports/" in path_text and group in {"blackbox", "whitebox"}:
        if path.name.endswith("_summary_report.html") and name == "report_html":
            return "summary_report_html"
        if path.name.endswith("_summary_results.json") and name == "results_json":
            return "summary_results_json"
        if path.name.endswith("_summary_run_log.txt") and name == "run_log":
            return "summary_run_log"
    return name


def _discover_artifacts_from_filesystem(job_id: str, seen_paths: set[str]) -> list[dict[str, Any]]:
    base_dir = Path(__file__).resolve().parent / "data"
    candidates = [
        ("job_reports", base_dir / "job_reports" / job_id / "reports"),
        ("art_runs", base_dir / "art_runs" / job_id / "reports"),
        ("foolbox_runs", base_dir / "foolbox_runs" / job_id / "reports"),
        ("garak_runs", base_dir / "garak_runs" / job_id / "reports"),
        ("pyrit_runs", base_dir / "pyrit_runs" / job_id / "reports"),
        ("textattack_runs", base_dir / "textattack_runs" / job_id / "reports"),
        ("ocr_runs", base_dir / "ocr_runs" / job_id / "reports"),
        ("test_runs", base_dir / "test_runs" / job_id),
    ]
    discovered: list[dict[str, Any]] = []
    for source_group, reports_dir in candidates:
        if not reports_dir.exists() or not reports_dir.is_dir():
            continue
        for path in sorted(reports_dir.glob("*")):
            if not path.is_file():
                continue
            if source_group == "art_runs" and path.name.startswith(("blackbox_", "whitebox_")):
                mirrored_path = base_dir / "job_reports" / job_id / "reports" / path.name
                if mirrored_path.exists():
                    continue
            resolved = str(path.resolve())
            if resolved in seen_paths:
                continue
            seen_paths.add(resolved)
            discovered.append(
                {
                    "group": _artifact_group_for_path(path, source_group),
                    "name": _artifact_name_for_path(path, source_group),
                    "path": resolved,
                    "exists": True,
                    "size_bytes": path.stat().st_size,
                }
            )
    return discovered


def collect_job_artifacts(job_record: dict[str, Any]) -> list[dict[str, Any]]:
    artifacts: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    seen_paths: set[str] = set()
    result = job_record.get("result") or {}

    def add_artifacts(group: str, payload: dict[str, Any]) -> None:
        for name, path in (payload or {}).items():
            if not path:
                continue
            key = (group, str(path))
            if key in seen:
                continue
            seen.add(key)
            resolved = Path(path).expanduser()
            exists = resolved.exists()
            resolved_str = str(resolved.resolve()) if exists else str(resolved)
            seen_paths.add(resolved_str)
            normalized_name = _normalize_artifact_name(group, str(name), resolved)
            artifacts.append(
                {
                    "group": group,
                    "name": normalized_name,
                    "path": resolved_str,
                    "exists": exists,
                    "size_bytes": resolved.stat().st_size if exists and resolved.is_file() else None,
                }
            )

    add_artifacts("job", result.get("artifacts") or {})
    add_artifacts("blackbox", (result.get("blackbox") or {}).get("artifacts") or {})
    add_artifacts("whitebox", (result.get("whitebox") or {}).get("artifacts") or {})
    for framework, framework_run in (result.get("framework_runs") or {}).items():
        add_artifacts(f"framework:{framework}", framework_run.get("artifacts") or {})
    artifacts.extend(_discover_artifacts_from_filesystem(str(job_record.get("job_id") or ""), seen_paths))

    artifacts.sort(key=lambda row: (row["group"], row["name"], row["path"]))
    return artifacts


def _read_terminal_text(path: Path, max_chars: int = 60_000) -> tuple[str, bool]:
    content = path.read_text(encoding="utf-8", errors="replace")
    truncated = False
    if len(content) > max_chars:
        content = "[truncated to most recent output]\n\n" + content[-max_chars:]
        truncated = True
    return content, truncated


def build_job_terminal_view(job_record: dict[str, Any]) -> dict[str, Any]:
    artifacts = collect_job_artifacts(job_record)
    result = job_record.get("result") or {}
    framework_runs = result.get("framework_runs") or {}
    errors = job_record.get("errors") or []
    notes = result.get("notes") or []

    preferred_artifact = next(
        (
            artifact
            for artifact in artifacts
            if artifact.get("exists")
            and artifact.get("name") in {"run_log", "txt_log", "stdout", "stderr"}
        ),
        None,
    )

    lines: list[str] = [
        f"$ job_id={job_record.get('job_id', '')}",
        f"$ job_name={job_record.get('job_name', '')}",
        f"$ status={job_record.get('status', 'unknown')}",
        f"$ wrapper={job_record.get('wrapper_id') or 'None'}",
        f"$ backend={(job_record.get('configuration') or {}).get('execution_backend', '')}",
        f"$ frameworks={', '.join((job_record.get('configuration') or {}).get('frameworks') or []) or '-'}",
        f"$ updated_at_utc={job_record.get('updated_at_utc') or job_record.get('created_at_utc') or ''}",
        "",
    ]

    if result.get("blackbox") is not None:
        lines.append(f"[blackbox] {result['blackbox']}")
    if result.get("whitebox") is not None:
        lines.append(f"[whitebox] {result['whitebox']}")
    for framework, payload in framework_runs.items():
        lines.append(f"[framework:{framework}] {payload}")
    if notes:
        lines.append("")
        lines.append("[notes]")
        for note in notes:
            lines.append(str(note))
    if errors:
        lines.append("")
        lines.append("[errors]")
        for error in errors:
            lines.append(str(error.get("message") or error))
            if error.get("traceback"):
                lines.append(str(error["traceback"]))

    synthesized_content = "\n".join(lines).strip() + "\n"

    if preferred_artifact is None:
        return {
            "job_id": job_record.get("job_id"),
            "status": job_record.get("status", "unknown"),
            "log_source": "synthesized",
            "truncated": False,
            "content": synthesized_content + "\n[info] No text log artifact was recorded for this job.\n",
            "artifact_path": None,
        }

    target = Path(str(preferred_artifact["path"])).expanduser().resolve()
    content, truncated = _read_terminal_text(target)
    return {
        "job_id": job_record.get("job_id"),
        "status": job_record.get("status", "unknown"),
        "log_source": preferred_artifact["name"],
        "truncated": truncated,
        "content": synthesized_content + "\n--- artifact log ---\n\n" + content,
        "artifact_path": str(target),
    }


def _run_builtin_framework_scan(framework: str, job_record: dict[str, Any]) -> dict[str, Any]:
    if framework == "garak":
        return run_garak_scan(job_record)
    if framework == "pyrit":
        return run_pyrit_scan(job_record)
    if framework == "textattack":
        return run_textattack_scan(job_record)
    raise NotImplementedError(f"No built-in framework executor is implemented for '{framework}'.")


def _run_adapter_framework_scan(framework: str, adapter: BaseScanAdapter, job_record: dict[str, Any]) -> dict[str, Any]:
    if framework == "art":
        return run_art_scan(adapter, job_record)
    if framework == "foolbox":
        return run_foolbox_scan(adapter, job_record)
    return adapter.run_framework_scan(framework, job_record)


def _project_framework_run_to_blackbox(framework: str, framework_run: dict[str, Any]) -> dict[str, Any]:
    artifacts = dict(framework_run.get("artifacts") or {})
    projected_artifacts = {
        key: artifacts[key]
        for key in ("report_html", "results_json", "run_log", "report_jsonl", "runner_config_json")
        if key in artifacts
    }
    return {
        "status": framework_run.get("status", "unknown"),
        "framework": framework,
        "message": framework_run.get("message") or f"{framework} black-box framework run",
        "target_uri": framework_run.get("target_uri"),
        "probe_spec": framework_run.get("probe_spec"),
        "attack_type": framework_run.get("attack_type"),
        "attack_types": framework_run.get("attack_types"),
        "objective": framework_run.get("objective"),
        "model_name": framework_run.get("model_name"),
        "recipe": framework_run.get("recipe"),
        "goal_function": framework_run.get("goal_function"),
        "constraint_mode": framework_run.get("constraint_mode"),
        "max_examples": framework_run.get("max_examples"),
        "query_budget": framework_run.get("query_budget"),
        "summary": framework_run.get("summary"),
        "attack_runs": framework_run.get("attack_runs"),
        "tool_compatibility": framework_run.get("tool_compatibility"),
        "artifacts": projected_artifacts,
        **({"error": framework_run.get("error")} if framework_run.get("error") else {}),
    }


def build_execution_plan_object(job_record: dict[str, Any]) -> dict[str, Any]:
    wrapper_meta = None
    if job_record.get("wrapper_id"):
        wrapper_map = {row["wrapper_id"]: row for row in list_wrappers()}
        wrapper_meta = wrapper_map.get(job_record["wrapper_id"])
    job = ScanJobCreate(**{
        "job_name": job_record["job_name"],
        "model": job_record["model"],
        "configuration": job_record["configuration"],
        "wrapper_id": job_record.get("wrapper_id"),
    })
    return build_execution_plan(job, wrapper_meta)


def create_job(payload: ScanJobCreate) -> dict[str, Any]:
    ensure_dirs()
    # Task 11: full-length uuid4().hex (32 chars) to eliminate collision risk.
    # Pre-existing 12-char job ids on disk continue to work since lookup is by filename.
    job_id = uuid.uuid4().hex
    record = ScanJobRecord(
        job_id=job_id,
        job_name=payload.job_name,
        status="queued",
        created_at_utc=now_utc(),
        updated_at_utc=now_utc(),
        wrapper_id=payload.wrapper_id,
        model=model_dump(payload.model),
        configuration=model_dump(payload.configuration),
        result=None,
        errors=[],
    )
    job_payload = model_dump(record)
    save_job(job_id, job_payload)
    return job_payload


def run_job(job_id: str) -> dict[str, Any]:
    payload = load_job(job_id)
    if payload is None:
        raise KeyError(f"Job '{job_id}' not found.")
    payload["status"] = "running"
    payload["updated_at_utc"] = now_utc()
    save_job(job_id, payload)
    try:
        payload["result"] = execute_job_record(payload)
        payload["status"] = "completed"
    except Exception as exc:  # pragma: no cover - defensive capture
        payload["status"] = "failed"
        payload.setdefault("errors", []).append(
            {
                "message": repr(exc),
                "traceback": traceback.format_exc(),
            }
        )
    payload["updated_at_utc"] = now_utc()
    save_job(job_id, payload)
    return payload


def list_jobs() -> list[dict[str, Any]]:
    ensure_dirs()
    jobs = []
    for path in sorted(JOBS_DIR.glob("*.json")):
        jobs.append(read_json(path))
    jobs.sort(key=lambda row: (row.get("updated_at_utc") or row.get("created_at_utc") or "", row.get("job_id") or ""), reverse=True)
    return jobs


def reconcile_job_statuses() -> list[dict[str, Any]]:
    # Task 10: hold JOB_WRITE_LOCK across the whole read-modify-write loop so a
    # concurrent save_job cannot re-promote a job to "running" between our read
    # and our save (or vice-versa). RLock allows save_job to re-acquire.
    reconciled: list[dict[str, Any]] = []
    with JOB_WRITE_LOCK:
        for job in list_jobs():
            if job.get("status") != "running":
                continue
            job["status"] = "failed"
            job["updated_at_utc"] = now_utc()
            job.setdefault("errors", []).append(
                {
                    "message": "Job was left in a running state and was reconciled after an interrupted process or restart.",
                    "traceback": "",
                }
            )
            save_job(str(job["job_id"]), job)
            reconciled.append(job)
    return reconciled
