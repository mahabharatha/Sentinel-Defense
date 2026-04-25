"""Preflight checks — environment probing, platform support, runtime readiness.

Extracted from executor.py during the responsibility split (Task 7). Call sites
that still import from sentinel.executor keep working via a re-export shim at
the bottom of executor.py.
"""
from __future__ import annotations

import importlib.util
import json
import mimetypes
import sys
from pathlib import Path
from typing import Any
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request

from .compatibility import framework_compatibility_inventory, framework_runtime_specs
from .framework_registry import (
    FRAMEWORK_CAPABILITY_FLAGS,
    FRAMEWORK_SUPPORT_MATRIX,
    default_framework_order,
    framework_supported,
)
from .schemas import ScanJobCreate
from .storage import ensure_dirs


def framework_runtime_inventory() -> dict[str, Any]:
    """Lazy accessor for executor.framework_runtime_inventory().

    preflight.py is imported by executor.py, so we can't import the function
    at module load time — we'd circular-import. Calling this helper at
    function-body time is safe because executor.py has finished loading by
    then.
    """
    from .executor import framework_runtime_inventory as _impl
    return _impl()


def normalize_task_family(value: str) -> str:
    from .executor import normalize_task_family as _impl
    return _impl(value)


def list_wrappers() -> list[dict[str, Any]]:
    from .jobs import list_wrappers as _impl
    return _impl()


def build_execution_plan(*args, **kwargs):
    from .jobs import build_execution_plan as _impl
    return _impl(*args, **kwargs)


def _load_adapter(wrapper_id: str):
    from .executor import _load_adapter as _impl
    return _impl(wrapper_id)


def model_dump(payload: Any) -> dict[str, Any]:
    from .executor import model_dump as _impl
    return _impl(payload)


def _path_matches_job(path_spec: dict[str, Any], job: ScanJobCreate) -> bool:
    from .executor import _path_matches_job as _impl
    return _impl(path_spec, job)


# Re-derived from executor.FRAMEWORK_RUNTIME_SPECS — preflight needs read access.
FRAMEWORK_RUNTIME_SPECS = framework_runtime_specs()



LOCAL_OLLAMA_HOST_MARKERS = ("127.0.0.1:11434", "localhost:11434")


LOCAL_OLLAMA_DEFAULT_TAGS_URL = "http://127.0.0.1:11434/api/tags"


def python_runtime_summary() -> dict[str, Any]:
    pyrit_python_ok = (3, 10) <= sys.version_info[:2] < (3, 14)
    return {
        "python_executable": sys.executable,
        "python_version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "pyrit_supported_python": pyrit_python_ok,
        "workspace_root": str(Path(__file__).resolve().parent),
    }


def _looks_like_local_ollama_endpoint(endpoint_uri: str) -> bool:
    lowered = str(endpoint_uri or "").strip().lower()
    if not lowered:
        return False
    return any(marker in lowered for marker in LOCAL_OLLAMA_HOST_MARKERS)


def _ollama_tags_url(endpoint_uri: str) -> str:
    value = str(endpoint_uri or "").strip() or LOCAL_OLLAMA_DEFAULT_TAGS_URL
    if not _looks_like_local_ollama_endpoint(value):
        return LOCAL_OLLAMA_DEFAULT_TAGS_URL
    parsed = urllib_parse.urlparse(value)
    scheme = parsed.scheme or "http"
    netloc = parsed.netloc or LOCAL_OLLAMA_DEFAULT_TAGS_URL.removeprefix("http://").split("/", 1)[0]
    return f"{scheme}://{netloc}/api/tags"


def _probe_ollama_tags(endpoint_uri: str, timeout_sec: float = 0.5) -> dict[str, Any]:
    tags_url = _ollama_tags_url(endpoint_uri)
    try:
        with urllib_request.urlopen(tags_url, timeout=timeout_sec) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib_error.URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
        return {
            "service": "ollama",
            "reachable": False,
            "endpoint": tags_url,
            "status": "unreachable",
            "model_count": 0,
            "models": [],
            "error": str(exc),
        }

    models = []
    for row in payload.get("models") or []:
        if not isinstance(row, dict):
            continue
        model_name = str(row.get("name") or row.get("model") or "").strip()
        if model_name:
            models.append(model_name)

    unique_models = sorted({model_name for model_name in models})
    return {
        "service": "ollama",
        "reachable": True,
        "endpoint": tags_url,
        "status": "reachable",
        "model_count": len(unique_models),
        "models": unique_models,
        "error": "",
    }


def local_service_inventory() -> dict[str, dict[str, Any]]:
    return {"ollama": _probe_ollama_tags(LOCAL_OLLAMA_DEFAULT_TAGS_URL)}


def _model_available_in_ollama(service_status: dict[str, Any], model_name: str) -> bool:
    requested = str(model_name or "").strip().casefold()
    if not requested:
        return True
    return requested in {str(row).strip().casefold() for row in (service_status.get("models") or [])}


def _frameworks_requiring_wrapper(job: ScanJobCreate) -> list[str]:
    required: list[str] = []
    for framework in job.configuration.frameworks:
        path_specs = FRAMEWORK_SUPPORT_MATRIX.get(framework) or []
        matching_paths = [path_spec for path_spec in path_specs if _path_matches_job(path_spec, job)]
        supports_wrapperless = any(not path_spec.get("requires_wrapper", True) for path_spec in matching_paths)
        if not supports_wrapperless:
            required.append(framework)
    return required


def evaluate_platform_support(job: ScanJobCreate) -> dict[str, Any]:
    supported: list[dict[str, Any]] = []
    blockers: list[str] = []
    warnings: list[str] = []
    wrapper_selected = bool(job.wrapper_id)
    runtime_inventory = framework_runtime_inventory()

    for framework in job.configuration.frameworks:
        path_specs = FRAMEWORK_SUPPORT_MATRIX.get(framework) or []
        matching_paths = [path_spec for path_spec in path_specs if _path_matches_job(path_spec, job)]
        implemented_paths = [path_spec for path_spec in matching_paths if path_spec.get("implemented")]
        planned_paths = [path_spec for path_spec in matching_paths if not path_spec.get("implemented")]

        if implemented_paths:
            runtime_status = runtime_inventory.get(framework) or {}
            if not runtime_status.get("installed", True):
                blockers.append(
                    f"Framework '{framework}' matches an implemented path, but its runtime dependency "
                    f"'{runtime_status.get('package_name', framework)}' is not installed in the current platform environment."
                )
            supported.append(
                {
                    "framework": framework,
                    "status": "implemented" if runtime_status.get("installed", True) else "implemented_missing_runtime",
                    "paths": implemented_paths,
                    "runtime": runtime_status,
                }
            )
            continue

        if planned_paths:
            message = f"Framework '{framework}' matches a planned path for this model shape, but no built-in executor is implemented yet."
            if wrapper_selected:
                warnings.append(f"{message} The selected wrapper must provide the concrete execution path.")
            else:
                blockers.append(message)
            warnings.extend(path_spec.get("summary", "") for path_spec in planned_paths if path_spec.get("summary"))
            supported.append(
                {
                    "framework": framework,
                    "status": "planned_only" if not wrapper_selected else "wrapper_defined",
                    "paths": planned_paths,
                    "runtime": runtime_inventory.get(framework) or {},
                }
            )
            continue

        message = (
            "Framework "
            f"'{framework}' does not currently expose a real path for backend='{job.configuration.execution_backend}', "
            f"modality='{job.model.modality}', task_family='{normalize_task_family(job.model.task_family)}', "
            f"and scan_modes='{', '.join(job.configuration.scan_modes)}'."
        )
        if wrapper_selected:
            warnings.append(f"{message} Proceeding only because a wrapper is explicitly selected.")
        else:
            blockers.append(message)

    if job.configuration.frameworks and not job.wrapper_id:
        frameworks_requiring_wrapper = _frameworks_requiring_wrapper(job)
        if frameworks_requiring_wrapper:
            blockers.append(
                "Select a wrapper to execute framework(s): "
                + ", ".join(sorted(frameworks_requiring_wrapper))
                + ". Without a wrapper the platform only stores a plan for those frameworks."
            )

    return {
        "supported_frameworks": supported,
        "blockers": blockers,
        "warnings": warnings,
        "runtime_inventory": runtime_inventory,
    }


def evaluate_wrapper_compatibility(wrapper_meta: dict[str, Any], job: ScanJobCreate) -> dict[str, Any]:
    capabilities = wrapper_meta.get("capabilities", {})
    config = job.configuration
    model = job.model
    reasons: list[str] = []
    warnings: list[str] = []

    if config.execution_backend == "api_based" and not capabilities.get("supports_api_models", False):
        reasons.append("Wrapper does not advertise support for API-based models.")
    if config.execution_backend == "python_process_wrapped" and not capabilities.get("supports_python_process_models", False):
        reasons.append("Wrapper does not advertise support for python-process-wrapped models.")

    supported_modalities = set(capabilities.get("supported_modalities") or [])
    if supported_modalities and model.modality not in supported_modalities:
        reasons.append(f"Wrapper does not advertise support for modality '{model.modality}'.")
    supported_task_families = {normalize_task_family(value) for value in (capabilities.get("supported_task_families") or [])}
    if supported_task_families and normalize_task_family(model.task_family) not in supported_task_families:
        reasons.append(f"Wrapper does not advertise support for task family '{model.task_family}'.")

    if "blackbox" in config.scan_modes and not capabilities.get("supports_blackbox", False):
        reasons.append("Wrapper does not support black-box scanning.")
    if "whitebox" in config.scan_modes and not capabilities.get("supports_whitebox", False):
        reasons.append("Wrapper does not support white-box scanning.")

    unsupported_frameworks = [framework for framework in config.frameworks if not framework_supported(capabilities, framework)]
    if unsupported_frameworks:
        reasons.append(f"Wrapper does not support framework(s): {', '.join(sorted(unsupported_frameworks))}.")

    if config.execution_backend == "api_based" and "whitebox" in config.scan_modes:
        warnings.append("API-based white-box scans usually need a richer custom adapter boundary than a plain hosted endpoint.")

    if "whitebox" in config.scan_modes and any(framework in {"art", "foolbox"} for framework in config.frameworks):
        if not capabilities.get("supports_gradients", False):
            warnings.append("Selected white-box frameworks often need gradients; this wrapper does not advertise gradient support.")
        if not capabilities.get("supports_logits", False):
            warnings.append("Some white-box workflows benefit from logits; this wrapper does not advertise logit support.")

    return {
        "wrapper_id": wrapper_meta.get("wrapper_id"),
        "display_name": wrapper_meta.get("display_name"),
        "compatible": not reasons,
        "reasons": reasons,
        "warnings": warnings,
    }


def report_expectations(job: ScanJobCreate) -> list[dict[str, str]]:
    expectations: list[dict[str, str]] = []
    for report in job.configuration.reports:
        if report in {"json", "html", "txt_log"}:
            expectations.append(
                {
                    "report": report,
                    "decision": "LIKELY_AVAILABLE",
                    "reason": "This report type is part of the current practical baseline for implemented paths.",
                }
            )
        else:
            expectations.append(
                {
                    "report": report,
                    "decision": "PATH_DEPENDENT",
                    "reason": "This report type depends on the selected execution path and is not universally implemented in the current scaffold.",
                }
            )
    return expectations


def evaluate_runtime_readiness(job: ScanJobCreate) -> dict[str, Any]:
    config = job.configuration
    extra_options = config.extra_options or {}
    frameworks = set(config.frameworks)
    blockers: list[str] = []
    warnings: list[str] = []
    checks: list[dict[str, Any]] = []
    endpoint_cache: dict[str, dict[str, Any]] = {}

    def ensure_local_ollama_ready(framework: str, endpoint_uri: str, model_name: str) -> None:
        endpoint = str(endpoint_uri or "").strip()
        if not _looks_like_local_ollama_endpoint(endpoint):
            return
        service_status = endpoint_cache.get(endpoint)
        if service_status is None:
            service_status = _probe_ollama_tags(endpoint)
            endpoint_cache[endpoint] = service_status
        checks.append(
            {
                "check": "local_ollama",
                "framework": framework,
                "endpoint": endpoint,
                "reachable": service_status.get("reachable", False),
                "model_name": model_name,
                "models": service_status.get("models", []),
            }
        )
        if not service_status.get("reachable", False):
            blockers.append(
                f"Local Ollama endpoint '{endpoint}' is not reachable for framework '{framework}'. "
                "Start Ollama and verify the API is listening before launching this job."
            )
            return
        if model_name and not _model_available_in_ollama(service_status, model_name):
            blockers.append(
                f"Requested local Ollama model '{model_name}' is not currently available at '{endpoint}'. "
                "Pull the model first or change the selected runtime model."
            )

    if "pyrit" in frameworks:
        pyrit_endpoint = str(extra_options.get("pyrit_endpoint_uri") or job.model.source_value or "").strip()
        pyrit_model_name = str(extra_options.get("pyrit_model_name") or job.model.model_id or "").strip()
        ensure_local_ollama_ready("pyrit", pyrit_endpoint, pyrit_model_name)

        pyrit_profile = str(extra_options.get("pyrit_profile") or "text").strip().lower()
        if pyrit_profile == "multimodal":
            configured_seed_image = str(extra_options.get("pyrit_seed_image_path") or "").strip()
            seed_image_path = configured_seed_image or str(config.sample_path or "").strip()
            seed_image_source = "pyrit_seed_image_path" if configured_seed_image else "sample_path_fallback"
            if not seed_image_path:
                blockers.append("PyRIT multimodal profile requires a Seed Image Path or Sample Path before launch.")
            else:
                resolved_seed_path = Path(seed_image_path).expanduser()
                checks.append(
                    {
                        "check": "pyrit_multimodal_seed_image",
                        "path": str(resolved_seed_path),
                        "source": seed_image_source,
                        "exists": resolved_seed_path.exists(),
                    }
                )
                if not resolved_seed_path.exists() or not resolved_seed_path.is_file():
                    blockers.append(f"PyRIT multimodal seed image was not found: {resolved_seed_path}")
                else:
                    media_type = mimetypes.guess_type(str(resolved_seed_path))[0] or ""
                    if media_type and not media_type.startswith("image/"):
                        warnings.append(
                            f"PyRIT multimodal seed path '{resolved_seed_path}' does not look like an image file ({media_type})."
                        )

    if "garak" in frameworks:
        garak_model_type = str(extra_options.get("garak_model_type") or "rest").strip().lower()
        if garak_model_type and not garak_model_type.startswith("rest"):
            checks.append(
                {
                    "check": "garak_generator",
                    "framework": "garak",
                    "model_type": garak_model_type,
                    "requires_local_ollama": False,
                }
            )
        else:
            garak_endpoint = str(extra_options.get("garak_endpoint_uri") or job.model.source_value or "").strip()
            request_template = extra_options.get("garak_request_template_json_object") or {}
            garak_model_name = ""
            if isinstance(request_template, dict):
                garak_model_name = str(request_template.get("model") or "").strip()
            garak_model_name = garak_model_name or str(job.model.model_id or "").strip()
            ensure_local_ollama_ready("garak", garak_endpoint, garak_model_name)

    if "textattack" in frameworks:
        runtime_inventory = framework_runtime_inventory()
        textattack_runtime = runtime_inventory.get("textattack") or {}
        textattack_goal_function = str(
            extra_options.get("textattack_goal_function") or "untargeted-classification"
        ).strip().lower()
        textattack_constraint_mode = str(extra_options.get("textattack_constraint_mode") or "default").strip().lower()
        checks.append(
            {
                "check": "textattack_scope",
                "framework": "textattack",
                "backend": config.execution_backend,
                "source_type": job.model.source_type,
                "task_family": normalize_task_family(job.model.task_family),
                "modality": str(job.model.modality or "").strip().lower(),
                "scan_modes": list(config.scan_modes),
                "runtime_installed": textattack_runtime.get("installed", False),
                "goal_function": textattack_goal_function,
                "constraint_mode": textattack_constraint_mode,
            }
        )
        if config.execution_backend != "python_process_wrapped":
            blockers.append(
                "TextAttack first landing only supports the 'python_process_wrapped' backend. "
                "API-based TextAttack runs are out of scope for the first landing."
            )
        if str(job.model.source_type or "").strip().lower() == "api":
            blockers.append(
                "TextAttack first landing requires an in-process Hugging Face or local text-classification model, not an API endpoint."
            )
        if normalize_task_family(job.model.task_family) != "text-classification":
            blockers.append(
                "TextAttack first landing is limited to the 'text-classification' task family."
            )
        if str(job.model.modality or "").strip().lower() != "text":
            blockers.append("TextAttack first landing is limited to text modality.")
        if "whitebox" in set(config.scan_modes):
            blockers.append(
                "TextAttack first landing is intentionally blackbox-only in this platform. White-box TextAttack support is deferred to a later phase."
            )
        if textattack_goal_function != "untargeted-classification":
            blockers.append(
                "TextAttack first landing currently supports only the 'untargeted-classification' goal function."
            )
        if textattack_constraint_mode != "default":
            blockers.append(
                "TextAttack first landing currently supports only the 'default' constraint mode preset."
            )
        if not textattack_runtime.get("installed", False):
            blockers.append(
                "TextAttack runtime dependency 'textattack' is not installed in the current environment."
            )
        if not str(config.sample_path or "").strip() and not str(config.target_text or "").strip():
            warnings.append(
                "Provide a Sample Path or Target Text for future TextAttack smoke runs so the first executor landing has attack input ready."
            )

    return {
        "blockers": blockers,
        "warnings": warnings,
        "checks": checks,
        "services": endpoint_cache,
    }


def build_preflight(payload: ScanJobCreate) -> dict[str, Any]:
    wrappers = list_wrappers()
    wrapper_checks = [evaluate_wrapper_compatibility(wrapper, payload) for wrapper in wrappers]
    wrapper_map = {wrapper["wrapper_id"]: wrapper for wrapper in wrappers}
    selected_wrapper = wrapper_map.get(payload.wrapper_id) if payload.wrapper_id else None
    selected_wrapper_check = next((row for row in wrapper_checks if row["wrapper_id"] == payload.wrapper_id), None)

    validation_messages: list[str] = []
    platform_support = evaluate_platform_support(payload)
    runtime_readiness = evaluate_runtime_readiness(payload)
    if payload.wrapper_id:
        if selected_wrapper is None:
            validation_messages.append(f"Selected wrapper '{payload.wrapper_id}' is not registered.")
        else:
            try:
                adapter = _load_adapter(payload.wrapper_id)
                validation_messages.extend(adapter.validate_config(model_dump(payload)))
            except Exception as exc:  # pragma: no cover - defensive for preflight only
                validation_messages.append(f"Wrapper validation failed during preflight: {exc!r}")

    plan = build_execution_plan(payload, selected_wrapper)
    blockers = list(platform_support["blockers"]) + list(runtime_readiness["blockers"]) + list(validation_messages)
    if selected_wrapper_check and not selected_wrapper_check["compatible"]:
        blockers.extend(selected_wrapper_check["reasons"])

    compatible_wrappers = [row for row in wrapper_checks if row["compatible"]]
    incompatible_wrappers = [row for row in wrapper_checks if not row["compatible"]]

    return {
        "status": "ready" if not blockers else "needs_changes",
        "selected_wrapper": selected_wrapper_check,
        "compatible_wrappers": compatible_wrappers,
        "incompatible_wrappers": incompatible_wrappers,
        "execution_plan": plan,
        "platform_support": platform_support,
        "runtime_readiness": runtime_readiness,
        "validation_messages": validation_messages,
        "warnings": plan.get("warnings", []) + platform_support["warnings"] + runtime_readiness["warnings"],
        "blockers": blockers,
        "report_expectations": report_expectations(payload),
    }
