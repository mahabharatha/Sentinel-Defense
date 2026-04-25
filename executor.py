from __future__ import annotations

import base64
import html
import importlib.util
import json
import mimetypes
import re
import shutil
import sys
import traceback
import uuid
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Optional
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request

from .compatibility import framework_compatibility_inventory
from .compatibility import framework_runtime_specs
from .contracts import BaseScanAdapter
from .executors.art_executor import run_art_scan
from .executors.foolbox_executor import run_foolbox_scan
from .executors.garak_executor import run_garak_scan
from .executors.pyrit_executor import run_pyrit_scan
from .executors.textattack_executor import run_textattack_scan
from .framework_registry import FRAMEWORK_CAPABILITY_FLAGS
from .framework_registry import FRAMEWORK_SUPPORT_MATRIX
from .framework_registry import default_framework_order
from .framework_registry import framework_supported
from .schemas import ScanJobCreate, ScanJobRecord, WrapperRegistration
from .storage import (
    JOB_WRITE_LOCK,
    JOBS_DIR,
    TEMPLATE_INDEX,
    WRAPPERS_DIR,
    ensure_dirs,
    load_job,
    load_template_index,
    load_wrapper_code,
    load_wrapper_index,
    read_json,
    save_job,
    save_template_index,
    save_wrapper_file,
    save_wrapper_index,
)

# Task 5: reporting layer extracted to sentinel/reporting/. We re-import every
# moved symbol here so the old `from sentinel.executor import <name>` contract
# (used by app.py, tests, and the whitebox_scan_platform shim) keeps working.
# New code should prefer `from sentinel.reporting.<module> import <name>`.
from .reporting.utils import (
    _RawHtml,
    _first_present,
    _html_scalar,
    _html_table,
    _resolve_mode_framework_payload,
)
from .reporting.normalized import (
    NORMALIZED_SEVERITY_ENGINE_VERSION,
    NORMALIZED_SEVERITY_RULESET_VERSION,
    NORMALIZED_SEVERITY_SCHEMA_VERSION,
    _SEVERITY_LABELS,
    _SEVERITY_RANK,
    _build_normalized_severity_payload,
    _clamp_score,
    _collect_art_non_scored_attacks,
    _collect_mode_source_artifacts,
    _evidence_ref,
    _normalize_art_findings,
    _normalize_foolbox_findings,
    _normalize_garak_findings,
    _normalize_pyrit_findings,
    _normalize_textattack_findings,
    _normalized_behavior_family,
    _normalized_severity_paths,
    _pyrit_behavior_classification_rows,
    _render_normalized_severity_html,
    _safe_float,
    _severity_confidence_label,
    _severity_dimension_rows,
    _severity_from_dimensions,
    _tool_behavior_family,
    _write_normalized_severity_artifacts,
)
from .reporting.pyrit import (
    _html_block,
    _render_local_image_preview_html,
    _render_pyrit_attack_runs_html,
    _render_pyrit_console_output_html,
    _render_pyrit_conversation_topology_html,
    _render_pyrit_exchange_html,
    _render_pyrit_media_block,
    _render_pyrit_multimodal_context_html,
    _render_pyrit_multimodal_summary_html,
    _render_pyrit_outcome_html,
    _render_pyrit_transcript_html,
)
from .reporting.garak import _render_garak_attempt_samples_html
from .reporting.textattack import (
    _render_textattack_examples_html,
    _render_textattack_outcome_html,
)
from .reporting.foolbox import _render_foolbox_attack_results_html
from .reporting.art import _render_art_attack_results_html



BUILTIN_WRAPPERS = [
    {
        "wrapper_id": "hf_speech_to_text_art_adapter",
        "display_name": "HF Speech-to-Text ART Adapter",
        "class_name": "HFSpeechToTextArtAdapter",
        "file_path": str((WRAPPERS_DIR / "hf_speech_to_text_art_adapter.py").resolve()),
    },
    {
        "wrapper_id": "hf_ocr_art_adapter",
        "display_name": "HF OCR ART Adapter",
        "class_name": "HFOcrArtAdapter",
        "file_path": str((WRAPPERS_DIR / "hf_ocr_art_adapter.py").resolve()),
    },
    {
        "wrapper_id": "hf_vision_classification_art_adapter",
        "display_name": "HF Vision Classification ART Adapter",
        "class_name": "HFVisionClassificationArtAdapter",
        "file_path": str((WRAPPERS_DIR / "hf_vision_classification_art_adapter.py").resolve()),
    },
    {
        "wrapper_id": "whisper_tiny_art_adapter",
        "display_name": "Whisper Tiny ART Adapter",
        "class_name": "WhisperTinyArtAdapter",
        "file_path": str((WRAPPERS_DIR / "whisper_tiny_art_adapter.py").resolve()),
    },
    {
        "wrapper_id": "trocr_small_art_adapter",
        "display_name": "TrOCR Small ART Adapter",
        "class_name": "TrOCRSmallArtAdapter",
        "file_path": str((WRAPPERS_DIR / "trocr_small_art_adapter.py").resolve()),
    },
    {
        "wrapper_id": "hf_vision_foolbox_adapter",
        "display_name": "HF Vision Foolbox Adapter",
        "class_name": "HFVisionClassificationFoolboxAdapter",
        "file_path": str((WRAPPERS_DIR / "hf_vision_foolbox_adapter.py").resolve()),
    },
]

# Task 6: BUILTIN_TEMPLATES now lives in data/builtin_templates.json so
# template data can be edited without touching code. Helpers that constructed
# the list (_slug_template_token, _builtin_template_modes_label,
# _make_builtin_template) have been retired; any additions should be made to
# the JSON file directly with the same template_id convention.
def _load_builtin_templates() -> list[dict[str, Any]]:
    path = Path(__file__).resolve().parent / "data" / "builtin_templates.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    return data if isinstance(data, list) else []


BUILTIN_TEMPLATES: list[dict[str, Any]] = _load_builtin_templates()





TASK_FAMILY_ALIASES = {
    "image-classification": "vision-classification",
    "vision-classification": "vision-classification",
    "ocr": "ocr",
    "captioning": "captioning",
    "vqa": "vqa",
    "chat": "multimodal-chat",
    "text-chat": "multimodal-chat",
    "text-generation": "text-generation",
    "speech-to-text": "speech-to-text",
    "audio-classification": "audio-classification",
    "multimodal-chat": "multimodal-chat",
    "audio-language": "audio-language",
    "text-classification": "text-classification",
}




def now_utc() -> str:
    from time import gmtime, strftime

    return strftime("%Y-%m-%dT%H:%M:%SZ", gmtime())


def model_dump(data: Any) -> dict[str, Any]:
    if hasattr(data, "model_dump"):
        return data.model_dump()
    if hasattr(data, "dict"):
        return data.dict()
    if is_dataclass(data):
        return asdict(data)
    return dict(data)


# Task 7: FRAMEWORK_RUNTIME_SPECS now lives in preflight.py (single source of
# truth). It is re-imported via the shim at the bottom of this file so existing
# references like `FRAMEWORK_RUNTIME_SPECS.get(framework, {})` inside function
# bodies continue to work — those function bodies run lazily, after module load.












def framework_runtime_inventory() -> dict[str, dict[str, Any]]:
    compatibility = framework_compatibility_inventory(default_framework_order())
    inventory: dict[str, dict[str, Any]] = {}
    runtime_summary = python_runtime_summary()
    for framework in default_framework_order():
        spec = FRAMEWORK_RUNTIME_SPECS.get(framework, {})
        import_name = spec.get("import_name")
        installed = True if not import_name else importlib.util.find_spec(str(import_name)) is not None
        implemented_paths = [
            path_spec for path_spec in (FRAMEWORK_SUPPORT_MATRIX.get(framework) or []) if path_spec.get("implemented")
        ]
        compat_row = compatibility.get(framework, {}) or {}
        inventory[framework] = {
            "framework": framework,
            "package_name": spec.get("package_name") or framework,
            "import_name": import_name,
            "installed": installed,
            # Task 1: surface installed_version at the top level so UI consumers
            # don't need to dig into compatibility_layer. Falls back to "" when
            # the package isn't importable.
            "installed_version": str(compat_row.get("installed_version") or ""),
            "minimum_version": str(compat_row.get("minimum_version") or ""),
            "version_ok": bool(compat_row.get("version_ok", False)),
            "delivery": spec.get("delivery", "unknown"),
            "implemented": bool(implemented_paths),
            "implemented_path_count": len(implemented_paths),
            "python_requirement": spec.get("python_requirement", ""),
            "python_compatible": runtime_summary["pyrit_supported_python"] if framework == "pyrit" else True,
            "notes": spec.get("notes", ""),
            "compatibility_layer": compat_row,
        }
    return inventory


def default_options() -> dict[str, Any]:
    return {
        "execution_backends": ["api_based", "python_process_wrapped"],
        "scan_modes": ["blackbox", "whitebox"],
        "frameworks": default_framework_order(),
        "reports": ["json", "html", "pdf", "xlsx", "txt_log"],
        "model_sources": ["hf", "local", "url", "s3", "api"],
        "task_families": [
            "ocr",
            "vision-classification",
            "captioning",
            "vqa",
            "speech-to-text",
            "audio-classification",
            "multimodal-chat",
            "audio-language",
            "text-classification",
            "text-generation",
        ],
        "support_matrix": FRAMEWORK_SUPPORT_MATRIX,
        "framework_runtime": framework_runtime_inventory(),
        "tool_compatibility": framework_compatibility_inventory(default_framework_order()),
        "runtime_environment": python_runtime_summary(),
        "local_services": local_service_inventory(),
        "runtime_notes": {
            "local_model_servers": "Local inference servers such as Ollama remain external infrastructure even when the scan framework itself is bundled in the platform environment.",
            "deployment_bootstrap": "For supported deployments, install framework packages during the normal environment bootstrap and use preflight to confirm local model-server reachability before running jobs.",
        },
    }


























def _load_adapter(wrapper_id: str) -> BaseScanAdapter:
    wrapper_map = {row["wrapper_id"]: row for row in list_wrappers()}
    if wrapper_id not in wrapper_map:
        raise KeyError(f"Wrapper '{wrapper_id}' is not registered.")
    info = wrapper_map[wrapper_id]
    path = Path(info["file_path"]).resolve()
    wrapper_root = WRAPPERS_DIR.resolve()
    if wrapper_root != path and wrapper_root not in path.parents:
        raise PermissionError(f"Wrapper '{wrapper_id}' points outside the allowed wrapper directory.")
    spec = importlib.util.spec_from_file_location(f"user_wrapper_{wrapper_id}", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load wrapper spec from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    cls = getattr(module, info["class_name"])
    instance = cls()
    base_names = {cls.__name__ for cls in type(instance).__mro__}
    if "BaseScanAdapter" not in base_names:
        raise TypeError(f"Wrapper '{wrapper_id}' must inherit from BaseScanAdapter.")
    return instance




















def _mode_reports_dir(job_id: str) -> Path:
    return Path(__file__).resolve().parent / "data" / "job_reports" / job_id / "reports"


def _build_mode_summary_payload(job_record: dict[str, Any], mode: str, mode_result: dict[str, Any]) -> dict[str, Any]:
    return {
        "job_id": job_record.get("job_id"),
        "job_name": job_record.get("job_name"),
        "wrapper_id": job_record.get("wrapper_id"),
        "mode": mode,
        "status": mode_result.get("status", "unknown"),
        "model": job_record.get("model"),
        "configuration": job_record.get("configuration"),
        "result": mode_result,
    }


def _mode_summary_paths(job_id: str, mode: str) -> dict[str, Path]:
    reports_dir = _mode_reports_dir(job_id)
    reports_dir.mkdir(parents=True, exist_ok=True)
    return {
        "report_html": reports_dir / f"{mode}_report.html",
        "results_json": reports_dir / f"{mode}_results.json",
        "run_log": reports_dir / f"{mode}_run_log.txt",
        "summary_report_html": reports_dir / f"{mode}_summary_report.html",
        "summary_results_json": reports_dir / f"{mode}_summary_results.json",
        "summary_run_log": reports_dir / f"{mode}_summary_run_log.txt",
    }





















































def _load_garak_attempt_samples(
    mode_result: dict[str, Any],
    framework_payload: dict[str, Any] | None = None,
    *,
    limit: int = 10,
) -> dict[str, Any] | None:
    artifacts = dict((framework_payload or {}).get("artifacts") or {})
    artifacts.update(mode_result.get("artifacts") or {})
    report_jsonl_path = artifacts.get("report_jsonl")
    if not report_jsonl_path:
        return None

    report_path = Path(str(report_jsonl_path)).expanduser()
    if not report_path.exists() or not report_path.is_file():
        return None

    total_attempts = 0
    json_decode_errors = 0
    samples: list[dict[str, Any]] = []

    for raw_line in report_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            json_decode_errors += 1
            continue
        if payload.get("entry_type") != "attempt":
            continue

        total_attempts += 1
        if len(samples) >= limit:
            continue

        outputs = payload.get("outputs")
        if isinstance(outputs, list):
            output_text = "\n\n".join(str(item) for item in outputs if str(item).strip())
        elif outputs is None:
            output_text = ""
        else:
            output_text = str(outputs)

        notes = payload.get("notes")
        trigger = notes.get("trigger") if isinstance(notes, dict) else None

        samples.append(
            {
                "seq": payload.get("seq"),
                "goal": payload.get("goal") or "-",
                "trigger": trigger or "-",
                "prompt": payload.get("prompt") or "",
                "output": output_text,
                "detector_results": payload.get("detector_results") or {},
            }
        )

    return {
        "path": str(report_path),
        "total_attempts": total_attempts,
        "json_decode_errors": json_decode_errors,
        "displayed_attempts": len(samples),
        "samples": samples,
    }


def _load_textattack_samples(
    mode_result: dict[str, Any],
    framework_payload: dict[str, Any] | None = None,
    *,
    limit: int = 20,
) -> dict[str, Any] | None:
    framework_artifacts = dict((framework_payload or {}).get("artifacts") or {})
    mode_artifacts = dict(mode_result.get("artifacts") or {})
    candidate_paths = [
        mode_artifacts.get("source_results_json"),
        framework_artifacts.get("results_json"),
        mode_artifacts.get("results_json"),
    ]

    payload: dict[str, Any] | None = None
    results_path: Path | None = None
    seen_paths: set[str] = set()
    for candidate_path in candidate_paths:
        if not candidate_path:
            continue
        path = Path(str(candidate_path)).expanduser()
        resolved = str(path.resolve()) if path.exists() else str(path)
        if resolved in seen_paths:
            continue
        seen_paths.add(resolved)
        if not path.exists() or not path.is_file():
            continue
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(loaded, dict):
            payload = loaded
            results_path = path
            break

    if payload is None:
        return None

    examples = payload.get("examples")
    if not isinstance(examples, list):
        examples = []

    return {
        "path": str(results_path) if results_path else "",
        "recipe": payload.get("recipe") or "-",
        "goal_function": payload.get("goal_function") or "-",
        "constraint_mode": payload.get("constraint_mode") or "-",
        "max_examples": payload.get("max_examples") or "-",
        "query_budget": payload.get("query_budget") if payload.get("query_budget") is not None else "-",
        "model_name": (payload.get("model") or {}).get("model_id") or "-",
        "input_source": payload.get("input_source") or "-",
        "input_preview": payload.get("input_preview") or "",
        "summary": payload.get("summary") or {},
        "total_examples": len(examples),
        "displayed_examples": min(len(examples), limit),
        "examples": examples[:limit],
    }


def _load_pyrit_transcript_samples(
    mode_result: dict[str, Any],
    framework_payload: dict[str, Any] | None = None,
    *,
    limit: int = 20,
) -> dict[str, Any] | None:
    framework_artifacts = dict((framework_payload or {}).get("artifacts") or {})
    mode_artifacts = dict(mode_result.get("artifacts") or {})
    candidate_paths = [
        mode_artifacts.get("source_results_json"),
        framework_artifacts.get("results_json"),
        mode_artifacts.get("results_json"),
    ]
    payload: dict[str, Any] | None = None
    results_path: Path | None = None
    selected_payload: dict[str, Any] | None = None
    attack_runs: list[Any] | None = None
    transcript: list[Any] | None = None

    seen_paths: set[str] = set()
    for candidate_path in candidate_paths:
        if not candidate_path:
            continue
        resolved_path = Path(str(candidate_path)).expanduser()
        resolved_key = str(resolved_path.resolve()) if resolved_path.exists() else str(resolved_path)
        if resolved_key in seen_paths:
            continue
        seen_paths.add(resolved_key)
        if not resolved_path.exists() or not resolved_path.is_file():
            continue

        current_payload = json.loads(resolved_path.read_text(encoding="utf-8"))
        current_attack_runs = current_payload.get("attack_runs")
        if isinstance(current_attack_runs, list) and current_attack_runs:
            current_selected_payload = next(
                (
                    item
                    for item in current_attack_runs
                    if isinstance(item, dict) and str(item.get("status") or "").strip().lower() == "completed"
                ),
                next((item for item in current_attack_runs if isinstance(item, dict)), current_payload),
            )
        else:
            current_selected_payload = current_payload

        current_transcript = current_selected_payload.get("transcript")
        if payload is None:
            payload = current_payload
            results_path = resolved_path
            selected_payload = current_selected_payload
            attack_runs = current_attack_runs if isinstance(current_attack_runs, list) else []
            transcript = current_transcript if isinstance(current_transcript, list) else []

        if isinstance(current_transcript, list):
            payload = current_payload
            results_path = resolved_path
            selected_payload = current_selected_payload
            attack_runs = current_attack_runs if isinstance(current_attack_runs, list) else []
            transcript = current_transcript
            break

    if payload is None or results_path is None or selected_payload is None:
        return None

    if attack_runs is None:
        attack_runs = []
    if transcript is None:
        transcript = []

    def _strip_ansi(text: str) -> str:
        return re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", text or "")

    def _parse_printer_output_transcript(printer_output: str) -> list[dict[str, Any]]:
        cleaned = _strip_ansi(printer_output)
        parsed_samples: list[dict[str, Any]] = []
        current_role: str | None = None
        current_sequence: int | None = None
        buffer: list[str] = []
        seen_pairs: set[tuple[str, str]] = set()

        def flush_current() -> None:
            nonlocal current_role, current_sequence, buffer
            if current_role is None:
                return
            text = "\n".join(line for line in buffer if line.strip()).strip()
            key = (current_role, text)
            if text and key not in seen_pairs:
                parsed_samples.append(
                    {
                        "sequence": current_sequence if current_sequence is not None else len(parsed_samples),
                        "role": current_role,
                        "text": text,
                        "response_error": "",
                        "metadata": {},
                    }
                )
                seen_pairs.add(key)
            current_role = None
            current_sequence = None
            buffer = []

        for raw_line in cleaned.splitlines():
            line = raw_line.rstrip()
            stripped = line.strip()
            turn_match = re.match(r"^[^A-Za-z0-9]*Turn\s+(\d+)\s*-\s*(USER|ASSISTANT)\s*$", stripped, flags=re.IGNORECASE)
            if turn_match:
                flush_current()
                current_sequence = int(turn_match.group(1)) - 1
                current_role = turn_match.group(2).lower()
                continue
            if re.search(r"\b(USER|ASSISTANT)\b", stripped, flags=re.IGNORECASE) and "Turn " not in stripped:
                role_match = re.search(r"\b(USER|ASSISTANT)\b", stripped, flags=re.IGNORECASE)
                if role_match is not None:
                    flush_current()
                    current_role = role_match.group(1).lower()
                    current_sequence = len(parsed_samples)
                    continue
            if stripped in {"ASSISTANT", "USER"}:
                flush_current()
                current_role = stripped.lower()
                current_sequence = len(parsed_samples)
                continue
            if current_role is not None:
                if set(stripped) <= {"─", "═"}:
                    continue
                if stripped.startswith("Report generated at:"):
                    flush_current()
                    continue
                buffer.append(stripped)

        flush_current()
        return [sample for sample in parsed_samples if sample.get("text")]

    samples: list[dict[str, Any]] = []
    for turn in transcript[:limit]:
        if not isinstance(turn, dict):
            continue
        samples.append(
            {
                "sequence": turn.get("sequence"),
                "role": turn.get("role") or "unknown",
                "text": turn.get("text") or "",
                "media": turn.get("media") or [],
                "response_error": turn.get("response_error") or "",
                "metadata": turn.get("metadata") or {},
            }
        )

    printer_output = str(selected_payload.get("printer_output") or "")
    source_turn_count = len(transcript)
    if samples and not any(str(sample.get("text") or "").strip() for sample in samples) and printer_output:
        fallback_samples = _parse_printer_output_transcript(printer_output)
        if fallback_samples:
            samples = fallback_samples[:limit]
            source_turn_count = len(fallback_samples)

    exchanges: list[dict[str, Any]] = []
    current_exchange: dict[str, Any] | None = None
    for index, turn in enumerate(samples):
        role = str(turn.get("role") or "unknown").strip().lower()
        text = str(turn.get("text") or "")
        media = turn.get("media") or []
        response_error = str(turn.get("response_error") or "")
        metadata = turn.get("metadata") or {}

        if role == "assistant":
            if current_exchange is None:
                current_exchange = {
                    "index": len(exchanges) + 1,
                    "user_prompt": "",
                    "user_media": [],
                    "assistant_response": text,
                    "response_error": response_error,
                    "assistant_metadata": metadata,
                }
            else:
                existing = str(current_exchange.get("assistant_response") or "")
                current_exchange["assistant_response"] = f"{existing}\n\n{text}".strip() if existing and text else existing or text
                if response_error and not current_exchange.get("response_error"):
                    current_exchange["response_error"] = response_error
                if metadata and not current_exchange.get("assistant_metadata"):
                    current_exchange["assistant_metadata"] = metadata
            exchanges.append(current_exchange)
            current_exchange = None
            continue

        labeled_text = text
        if role and role not in {"user", "unknown"}:
            labeled_text = f"[{role}] {text}".strip()

        if current_exchange is None:
            current_exchange = {
                "index": len(exchanges) + 1,
                "user_prompt": labeled_text,
                "user_media": list(media) if isinstance(media, list) else [],
                "assistant_response": "",
                "response_error": response_error,
                "assistant_metadata": {},
            }
        else:
            existing = str(current_exchange.get("user_prompt") or "")
            current_exchange["user_prompt"] = f"{existing}\n\n{labeled_text}".strip() if existing and labeled_text else existing or labeled_text
            existing_media = current_exchange.get("user_media") or []
            if isinstance(existing_media, list) and isinstance(media, list):
                current_exchange["user_media"] = [*existing_media, *media]
            if response_error and not current_exchange.get("response_error"):
                current_exchange["response_error"] = response_error

        if index == len(samples) - 1:
            exchanges.append(current_exchange)

    deduped_exchanges: list[dict[str, Any]] = []
    seen_exchange_keys: set[tuple[str, str, str, str]] = set()
    for exchange in exchanges:
        key = (
            str(exchange.get("user_prompt") or ""),
            json.dumps(exchange.get("user_media") or [], sort_keys=True),
            str(exchange.get("assistant_response") or ""),
            str(exchange.get("response_error") or ""),
        )
        if key in seen_exchange_keys:
            continue
        seen_exchange_keys.add(key)
        deduped_exchanges.append({**exchange, "index": len(deduped_exchanges) + 1})

    payload_exchanges = payload.get("exchanges")
    if isinstance(payload_exchanges, list) and payload_exchanges:
        normalized_payload_exchanges: list[dict[str, Any]] = []
        for exchange in payload_exchanges[:limit]:
            if not isinstance(exchange, dict):
                continue
            normalized_payload_exchanges.append(
                {
                    "index": exchange.get("index") or len(normalized_payload_exchanges) + 1,
                    "user_prompt": exchange.get("user_prompt") or "",
                    "user_media": exchange.get("user_media") or [],
                    "assistant_response": exchange.get("assistant_response") or "",
                    "response_error": exchange.get("response_error") or "",
                    "assistant_metadata": exchange.get("assistant_metadata") or {},
                }
            )
        if normalized_payload_exchanges:
            deduped_exchanges = normalized_payload_exchanges

    total_turns = payload.get("total_turns")
    if not isinstance(total_turns, int) or total_turns < 0:
        total_turns = source_turn_count
    total_exchanges = payload.get("total_exchanges")
    if not isinstance(total_exchanges, int) or total_exchanges < 0:
        total_exchanges = len(deduped_exchanges)

    return {
        "path": str(results_path),
        "status": payload.get("status") or mode_result.get("status") or "-",
        "conversation_id": selected_payload.get("conversation_id") or payload.get("conversation_id") or "-",
        "profile": selected_payload.get("profile") or payload.get("profile") or mode_result.get("profile") or "text",
        "target_uri": selected_payload.get("target_uri") or payload.get("target_uri") or mode_result.get("target_uri") or "-",
        "model_name": selected_payload.get("model_name") or payload.get("model_name") or mode_result.get("model_name") or "-",
        "attack_type": selected_payload.get("attack_type") or payload.get("attack_type") or mode_result.get("attack_type") or "-",
        "attack_types": payload.get("attack_types") or mode_result.get("attack_types") or [],
        "attack_run_count": len(attack_runs) if isinstance(attack_runs, list) else 0,
        "attack_runs": attack_runs if isinstance(attack_runs, list) else [],
        "selected_attack_type": selected_payload.get("attack_type") or "-",
        "objective": selected_payload.get("objective") or payload.get("objective") or mode_result.get("objective") or "-",
        "max_turns": selected_payload.get("max_turns") or payload.get("max_turns") or mode_result.get("max_turns") or "-",
        "max_backtracks": selected_payload.get("max_backtracks") or payload.get("max_backtracks") or mode_result.get("max_backtracks") or "-",
        "adversarial_target_uri": selected_payload.get("adversarial_target_uri") or payload.get("adversarial_target_uri") or mode_result.get("adversarial_target_uri") or "-",
        "adversarial_model_name": selected_payload.get("adversarial_model_name") or payload.get("adversarial_model_name") or mode_result.get("adversarial_model_name") or "-",
        "skeleton_key_prompt": selected_payload.get("skeleton_key_prompt") or payload.get("skeleton_key_prompt") or mode_result.get("skeleton_key_prompt") or "",
        "expected_response": selected_payload.get("expected_response") or payload.get("expected_response") or mode_result.get("expected_response") or "-",
        "expected_responses": selected_payload.get("expected_responses") or payload.get("expected_responses") or mode_result.get("expected_responses") or [],
        "forbidden_literals": selected_payload.get("forbidden_literals") or payload.get("forbidden_literals") or mode_result.get("forbidden_literals") or [],
        "expected_max_words": selected_payload.get("expected_max_words") or payload.get("expected_max_words") or mode_result.get("expected_max_words"),
        "expected_max_sentences": selected_payload.get("expected_max_sentences") or payload.get("expected_max_sentences") or mode_result.get("expected_max_sentences"),
        "seed_text": selected_payload.get("seed_text") or payload.get("seed_text") or mode_result.get("seed_text") or "",
        "configured_seed_image_path": selected_payload.get("configured_seed_image_path") or payload.get("configured_seed_image_path") or mode_result.get("configured_seed_image_path") or "",
        "seed_image_path": selected_payload.get("seed_image_path") or payload.get("seed_image_path") or mode_result.get("seed_image_path") or "",
        "seed_image_source": selected_payload.get("seed_image_source") or payload.get("seed_image_source") or mode_result.get("seed_image_source") or "",
        "follow_up_text": selected_payload.get("follow_up_text") or payload.get("follow_up_text") or mode_result.get("follow_up_text") or "",
        "max_attempts_on_failure": selected_payload.get("max_attempts_on_failure") or payload.get("max_attempts_on_failure") or mode_result.get("max_attempts_on_failure") or 0,
        "request_timeout_sec": selected_payload.get("request_timeout_sec") or payload.get("request_timeout_sec") or mode_result.get("request_timeout_sec") or "-",
        "many_shot_example_count": selected_payload.get("many_shot_example_count") or payload.get("many_shot_example_count") or mode_result.get("many_shot_example_count") or "-",
        "objective_scorer_mode": selected_payload.get("objective_scorer_mode") or payload.get("objective_scorer_mode") or mode_result.get("objective_scorer_mode") or "auto",
        "printer_output": printer_output,
        "result_metadata": selected_payload.get("result_metadata") or payload.get("result_metadata") or {},
        "platform_evaluation": selected_payload.get("platform_evaluation") or payload.get("platform_evaluation") or {},
        "total_turns": total_turns,
        "displayed_turns": len(samples),
        "samples": samples,
        "total_exchanges": total_exchanges,
        "displayed_exchanges": len(deduped_exchanges[:limit]),
        "exchanges": deduped_exchanges[:limit],
    }


































def _mode_overview_rows(job_record: dict[str, Any], mode: str, mode_result: dict[str, Any]) -> list[list[Any]]:
    config = job_record.get("configuration") or {}
    return [
        ["Mode", mode],
        ["Status", mode_result.get("status", "unknown")],
        ["Backend", config.get("execution_backend")],
        ["Wrapper", job_record.get("wrapper_id") or "None"],
        ["Frameworks Requested", config.get("frameworks") or []],
        ["Reports Requested", config.get("reports") or []],
        ["Sample Path", config.get("sample_path") or "-"],
        ["Target Text", config.get("target_text") or "-"],
        ["Message", mode_result.get("message") or "-"],
        ["Error", mode_result.get("error") or "-"],
    ]


def _mode_specific_rows(
    job_record: dict[str, Any],
    full_result: dict[str, Any],
    mode: str,
    mode_result: dict[str, Any],
) -> list[list[Any]]:
    config = job_record.get("configuration") or {}
    framework_payload = _resolve_mode_framework_payload(full_result, mode_result)
    framework_name = str(_first_present(mode_result.get("framework"), framework_payload.get("framework"), "") or "").strip()
    explicit_art_mode = bool(mode_result.get("report")) or str(mode_result.get("framework") or "").strip().lower() == "art"
    if framework_name == "art":
        if not explicit_art_mode:
            clean_result = mode_result.get("clean_result") or {}
            clean_summary = json.dumps(clean_result, sort_keys=True) if clean_result else "-"
            return [
                ["Framework", _first_present(mode_result.get("framework"), framework_payload.get("framework"), "-")],
                ["Mode Role", "baseline only"],
                ["Message", mode_result.get("message") or "-"],
                ["Clean Result", clean_summary],
                ["Max Iter", config.get("max_iter")],
                ["Batch Size", config.get("batch_size")],
                ["Include All Applicable Attacks", config.get("include_all_applicable_attacks")],
            ]
        report = framework_payload.get("report") or {}
        per_attack_results = report.get("per_attack_results") or []
        attack_inventory = report.get("attack_inventory") or []
        changed_count = sum(
            1
            for attack in per_attack_results
            if isinstance(attack, dict) and (attack.get("prediction_changed") or attack.get("transcript_changed"))
        )
        target_matched_count = sum(
            1 for attack in per_attack_results if isinstance(attack, dict) and attack.get("target_matched")
        )
        return [
            ["Framework", _first_present(mode_result.get("framework"), framework_payload.get("framework"), "-")],
            ["Attack Count", len(per_attack_results)],
            ["Attack Inventory Count", len(attack_inventory)],
            ["Changed Output Count", changed_count],
            ["Target Matched Count", target_matched_count],
            ["Max Iter", config.get("max_iter")],
            ["Batch Size", config.get("batch_size")],
            ["Include All Applicable Attacks", config.get("include_all_applicable_attacks")],
        ]
    if framework_name == "foolbox":
        attack_rows = mode_result.get("attack_results") or framework_payload.get("attack_results") or []
        attack_names = [
            str(attack.get("attack_name") or f"attack_{index}")
            for index, attack in enumerate(attack_rows, start=1)
            if isinstance(attack, dict)
        ]
        attack_count = mode_result.get("attack_count")
        if attack_count is None:
            attack_count = len(attack_rows)
        successful_attack_count = mode_result.get("successful_attack_count")
        if successful_attack_count is None:
            successful_attack_count = sum(1 for attack in attack_rows if isinstance(attack, dict) and attack.get("success"))
        base_rows = [
            ["Framework", _first_present(mode_result.get("framework"), framework_payload.get("framework"), "-")],
            ["Attack Count", attack_count],
            ["Successful Attack Count", successful_attack_count],
            ["Attack Names", ", ".join(attack_names) or "-"],
        ]
        if mode == "blackbox":
            return base_rows + [
                ["Clean Label", ((mode_result.get("clean_prediction") or framework_payload.get("clean_prediction") or {}).get("label_name")) or "-"],
                ["Min Samples", config.get("min_samples")],
                ["Batch Size", config.get("batch_size")],
            ]
        return base_rows + [
            ["Max Iter", config.get("max_iter")],
            ["Batch Size", config.get("batch_size")],
            ["Include All Applicable Attacks", config.get("include_all_applicable_attacks")],
        ]
    if mode == "blackbox":
        if framework_name == "pyrit":
            profile = str(_first_present(mode_result.get("profile"), framework_payload.get("profile"), "text") or "text").strip().lower() or "text"
            is_multimodal = profile == "multimodal"
            seed_image_source = str(_first_present(mode_result.get("seed_image_source"), framework_payload.get("seed_image_source"), "") or "").strip()
            if seed_image_source == "sample_path_fallback":
                seed_image_source_display = "Sample Path fallback"
            elif seed_image_source == "pyrit_seed_image_path":
                seed_image_source_display = "PyRIT Seed Image Path"
            else:
                seed_image_source_display = seed_image_source or "-"
            return [
                ["Framework", _first_present(mode_result.get("framework"), framework_payload.get("framework"), "-")],
                ["Profile", profile],
                ["Target URI", _first_present(mode_result.get("target_uri"), framework_payload.get("target_uri"), "-")],
                ["Attack Type", _first_present(mode_result.get("attack_type"), framework_payload.get("attack_type"), "-")],
                ["Attack List", ", ".join(_first_present(mode_result.get("attack_types"), framework_payload.get("attack_types"), []) or []) or "-"],
                *_pyrit_behavior_classification_rows(mode_result, framework_payload),
                ["Objective", _first_present(mode_result.get("objective"), framework_payload.get("objective"), "-")],
                ["Seed Text", _first_present(mode_result.get("seed_text"), framework_payload.get("seed_text"), "-") or "-"],
                ["Configured Seed Image Path", _first_present(mode_result.get("configured_seed_image_path"), framework_payload.get("configured_seed_image_path"), "-") or "-"],
                ["Seed Image Path", _first_present(mode_result.get("seed_image_path"), framework_payload.get("seed_image_path"), "-") or "-"],
                ["Seed Image Source", seed_image_source_display],
                ["Follow-up Text", _first_present(mode_result.get("follow_up_text"), framework_payload.get("follow_up_text"), "-") or "-"],
                ["Max Turns", _first_present(mode_result.get("max_turns"), framework_payload.get("max_turns"), "-")],
                ["Primary Required Word / Phrase" if is_multimodal else "Expected Response", _first_present(mode_result.get("expected_response"), framework_payload.get("expected_response"), "-")],
                ["Required Words / Phrases" if is_multimodal else "Required Literals", ", ".join(_first_present(mode_result.get("expected_responses"), framework_payload.get("expected_responses"), []) or []) or "-"],
                ["Forbidden Words / Phrases" if is_multimodal else "Forbidden Literals", ", ".join(_first_present(mode_result.get("forbidden_literals"), framework_payload.get("forbidden_literals"), []) or []) or "-"],
                ["Model Name", _first_present(mode_result.get("model_name"), framework_payload.get("model_name"), "-")],
                ["Objective Scorer Mode", _first_present(mode_result.get("objective_scorer_mode"), framework_payload.get("objective_scorer_mode"), "auto")],
                ["Max Words Allowed", _first_present(mode_result.get("expected_max_words"), framework_payload.get("expected_max_words"), "-")],
                ["Max Sentences Allowed", _first_present(mode_result.get("expected_max_sentences"), framework_payload.get("expected_max_sentences"), "-")],
                ["Request Timeout (sec)", _first_present(mode_result.get("request_timeout_sec"), framework_payload.get("request_timeout_sec"), "-")],
                ["Retry Attempts on Failure", _first_present(mode_result.get("max_attempts_on_failure"), framework_payload.get("max_attempts_on_failure"), 0)],
                ["Platform Verdict", _first_present(mode_result.get("platform_verdict"), framework_payload.get("platform_verdict"), "-")],
                ["Platform Severity", _first_present(mode_result.get("platform_severity"), framework_payload.get("platform_severity"), "-")],
                ["Min Samples", config.get("min_samples")],
                ["Batch Size", config.get("batch_size")],
            ] + (
                []
                if is_multimodal
                else [
                    ["Max Backtracks", _first_present(mode_result.get("max_backtracks"), framework_payload.get("max_backtracks"), "-")],
                    ["Adversarial Target URI", _first_present(mode_result.get("adversarial_target_uri"), framework_payload.get("adversarial_target_uri"), "-")],
                    ["Adversarial Model Name", _first_present(mode_result.get("adversarial_model_name"), framework_payload.get("adversarial_model_name"), "-")],
                    ["Skeleton Key Prompt Override", _first_present(mode_result.get("skeleton_key_prompt"), framework_payload.get("skeleton_key_prompt"), "-")],
                ]
            )
        if framework_name == "textattack":
            summary_payload = _first_present(mode_result.get("summary"), framework_payload.get("summary"), {}) or {}
            return [
                ["Framework", _first_present(mode_result.get("framework"), framework_payload.get("framework"), "-")],
                ["Recipe", _first_present(mode_result.get("recipe"), framework_payload.get("recipe"), "-")],
                ["Goal Function", _first_present(mode_result.get("goal_function"), framework_payload.get("goal_function"), "-")],
                ["Constraint Mode", _first_present(mode_result.get("constraint_mode"), framework_payload.get("constraint_mode"), "-")],
                ["Max Examples", _first_present(mode_result.get("max_examples"), framework_payload.get("max_examples"), "-")],
                ["Query Budget", _first_present(mode_result.get("query_budget"), framework_payload.get("query_budget"), "-")],
                ["Successful Examples", summary_payload.get("successful", "-") if isinstance(summary_payload, dict) else "-"],
                ["Failed Examples", summary_payload.get("failed", "-") if isinstance(summary_payload, dict) else "-"],
                ["Skipped Examples", summary_payload.get("skipped", "-") if isinstance(summary_payload, dict) else "-"],
                ["Success Rate", summary_payload.get("success_rate", "-") if isinstance(summary_payload, dict) else "-"],
                ["Average Queries", summary_payload.get("average_queries", "-") if isinstance(summary_payload, dict) else "-"],
                ["Average Words Changed", summary_payload.get("average_word_changes", "-") if isinstance(summary_payload, dict) else "-"],
                ["Label Flips", summary_payload.get("label_flip_count", "-") if isinstance(summary_payload, dict) else "-"],
                ["Min Samples", config.get("min_samples")],
                ["Batch Size", config.get("batch_size")],
            ]
        return [
            ["Framework", _first_present(mode_result.get("framework"), framework_payload.get("framework"), "-")],
            ["Target URI", _first_present(mode_result.get("target_uri"), framework_payload.get("target_uri"), "-")],
            ["Probe Spec", _first_present(mode_result.get("probe_spec"), framework_payload.get("probe_spec"), "-")],
            ["Min Samples", config.get("min_samples")],
            ["Batch Size", config.get("batch_size")],
        ]
    return [
        ["Framework", _first_present(mode_result.get("framework"), framework_payload.get("framework"), "-")],
        ["Max Iter", config.get("max_iter")],
        ["Batch Size", config.get("batch_size")],
        ["Include All Applicable Attacks", config.get("include_all_applicable_attacks")],
    ]


def _framework_run_rows(framework_runs: dict[str, Any]) -> list[list[Any]]:
    rows: list[list[Any]] = []
    for framework, payload in sorted(framework_runs.items()):
        if not isinstance(payload, dict):
            rows.append([framework, "unknown", "-", "-", "-"])
            continue
        details = []
        if payload.get("target_uri"):
            details.append(f"target={payload['target_uri']}")
        if payload.get("probe_spec"):
            details.append(f"probes={payload['probe_spec']}")
        if payload.get("attack_type"):
            details.append(f"attack={payload['attack_type']}")
        if payload.get("recipe"):
            details.append(f"recipe={payload['recipe']}")
        if payload.get("turn_count") is not None:
            details.append(f"turns={payload['turn_count']}")
        rows.append(
            [
                framework,
                payload.get("status", "unknown"),
                payload.get("message") or "-",
                payload.get("error") or "-",
                "; ".join(details) or "-",
            ]
        )
    return rows


def _artifact_rows(artifacts: dict[str, Any]) -> list[list[Any]]:
    rows: list[list[Any]] = []
    for key, value in sorted((artifacts or {}).items()):
        if not value:
            continue
        path = Path(str(value)).expanduser()
        rows.append([key, path.name, str(path)])
    return rows


def _note_rows(notes: list[Any]) -> list[list[Any]]:
    rows: list[list[Any]] = []
    for note in notes:
        if isinstance(note, dict):
            rows.append([note.get("type", "note"), json.dumps(note, sort_keys=True)])
        else:
            rows.append(["note", str(note)])
    return rows


def _render_mode_summary_html(
    job_record: dict[str, Any],
    full_result: dict[str, Any],
    mode: str,
    mode_result: dict[str, Any],
) -> str:
    config = job_record.get("configuration") or {}
    model = job_record.get("model") or {}
    framework_runs = full_result.get("framework_runs") or {}
    notes = full_result.get("notes") or []
    framework_payload = _resolve_mode_framework_payload(full_result, mode_result)
    framework_name = str(_first_present(mode_result.get("framework"), framework_payload.get("framework"), "") or "").strip()
    explicit_art_mode = bool(mode_result.get("report")) or str(mode_result.get("framework") or "").strip().lower() == "art"
    title = f"{mode.title()} Scan Report"
    status = str(mode_result.get("status", "unknown")).lower()
    status_class = {
        "completed": "ok",
        "failed": "error",
        "running": "warn",
    }.get(status, "muted")
    mode_detail_title = "Probe Details" if mode == "blackbox" else "Attack Details"

    sections = [
        (
            "Run Overview",
            _html_table(["Field", "Value"], _mode_overview_rows(job_record, mode, mode_result)),
        ),
        (
            "Model",
            _html_table(
                ["Field", "Value"],
                [
                    ["Model ID", model.get("model_id")],
                    ["Source Type", model.get("source_type")],
                    ["Source Value", model.get("source_value")],
                    ["Task Family", model.get("task_family")],
                    ["Modality", model.get("modality")],
                ],
            ),
        ),
        (
            mode_detail_title,
            _html_table(["Field", "Value"], _mode_specific_rows(job_record, full_result, mode, mode_result)),
        ),
    ]
    if mode == "blackbox" and framework_name == "garak":
        sections.append(
            (
                "Prompt / Response Samples",
                _render_garak_attempt_samples_html(_load_garak_attempt_samples(mode_result, framework_payload)),
            ),
        )
    if mode == "blackbox" and framework_name == "textattack":
        textattack_bundle = _load_textattack_samples(mode_result, framework_payload)
        sections.append(
            (
                "TextAttack Outcome",
                _render_textattack_outcome_html(textattack_bundle),
            ),
        )
        sections.append(
            (
                "TextAttack Examples",
                _render_textattack_examples_html(textattack_bundle),
            ),
        )
    if mode == "blackbox" and framework_name == "pyrit":
        pyrit_bundle = _load_pyrit_transcript_samples(mode_result, framework_payload)
        sections.append(
            (
                "PyRIT Multimodal Summary",
                _render_pyrit_multimodal_summary_html(pyrit_bundle),
            ),
        )
        sections.append(
            (
                "PyRIT Multimodal Context",
                _render_pyrit_multimodal_context_html(pyrit_bundle),
            ),
        )
        sections.append(
            (
                "PyRIT Outcome",
                _render_pyrit_outcome_html(pyrit_bundle),
            ),
        )
        sections.append(
            (
                "PyRIT Attack Runs",
                _render_pyrit_attack_runs_html(pyrit_bundle),
            ),
        )
        sections.append(
            (
                "PyRIT Conversation Topology",
                _render_pyrit_conversation_topology_html(pyrit_bundle),
            ),
        )
        sections.append(
            (
                "PyRIT Console Output",
                _render_pyrit_console_output_html(pyrit_bundle),
            ),
        )
        sections.append(
            (
                "PyRIT Exchanges",
                _render_pyrit_exchange_html(pyrit_bundle),
            ),
        )
        sections.append(
            (
                "PyRIT Transcript",
                _render_pyrit_transcript_html(pyrit_bundle),
            ),
        )
    if framework_name == "foolbox":
        sections.append(
            (
                "Foolbox Attack Results",
                _render_foolbox_attack_results_html(mode_result, framework_payload),
            ),
        )
    if framework_name == "art" and explicit_art_mode:
        sections.append(
            (
                "ART Attack Results",
                _render_art_attack_results_html(framework_payload),
            ),
        )
    sections.extend(
        [
            (
                "Framework Runs",
                _html_table(
                    ["Framework", "Status", "Message", "Error", "Details"],
                    _framework_run_rows(framework_runs),
                ),
            ),
            (
                "Original Artefacts",
                _html_table(["Artifact", "File", "Path"], _artifact_rows(mode_result.get("artifacts") or {})),
            ),
        ]
    )
    if notes:
        sections.append(("Notes", _html_table(["Type", "Details"], _note_rows(notes))))

    sections_html = "".join(
        f"<section><h2>{html.escape(section_title)}</h2>{section_body}</section>"
        for section_title, section_body in sections
    )

    raw_payload = _build_mode_summary_payload(job_record, mode, mode_result)
    return "\n".join(
        [
            "<!DOCTYPE html>",
            "<html lang='en'>",
            "<head>",
            "<meta charset='utf-8' />",
            "<meta name='viewport' content='width=device-width, initial-scale=1' />",
            f"<title>{html.escape(title)}</title>",
            "<style>",
            "/* Bharath Srinivasan | Sentinel Adversarial Orchestrator report presentation. Proprietary material. */",
            ":root { --bg: #07111f; --bg-accent: #10243d; --panel: rgba(11, 23, 39, 0.94); --panel-strong: #10233a; --ink: #eef7ff; --ink-soft: #a9bfd6; --line: rgba(112, 170, 221, 0.16); --line-strong: rgba(112, 170, 221, 0.28); --accent: #2fb6ff; --accent-strong: #1a8cff; --accent-soft: rgba(47, 182, 255, 0.14); --success: #23c788; --success-soft: rgba(35, 199, 136, 0.16); --warn: #ffb347; --warn-soft: rgba(255, 179, 71, 0.18); --danger: #ff6a7c; --danger-soft: rgba(255, 106, 124, 0.16); }",
            "* { box-sizing: border-box; }",
            "body { margin: 0; font-family: 'Avenir Next', 'Segoe UI', sans-serif; color: var(--ink); background: radial-gradient(circle at top left, rgba(47, 182, 255, 0.16), transparent 24%), radial-gradient(circle at top right, rgba(0, 120, 255, 0.14), transparent 30%), linear-gradient(180deg, #040a14 0%, #081323 46%, #0a1729 100%); }",
            ".page { max-width: 1180px; margin: 0 auto; padding: 24px; }",
            ".hero { background: radial-gradient(circle at top right, rgba(94, 204, 255, 0.24), transparent 32%), linear-gradient(135deg, rgba(255,255,255,0.08), transparent 34%), linear-gradient(135deg, #071323 0%, #0d233e 38%, #103157 72%, #0a6db3 100%); color: white; border: 1px solid rgba(122, 191, 255, 0.18); border-radius: 24px; padding: 28px; margin-bottom: 18px; box-shadow: 0 24px 72px rgba(0, 0, 0, 0.32); }",
            ".hero h1 { margin: 0 0 8px; font-size: 30px; }",
            ".hero-meta { display: flex; gap: 12px; flex-wrap: wrap; color: rgba(238, 247, 255, 0.78); font-size: 14px; }",
            ".status { display: inline-block; margin-top: 12px; padding: 8px 14px; border-radius: 999px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em; font-size: 12px; border: 1px solid transparent; }",
            ".status.ok { background: var(--success-soft); color: var(--success); border-color: rgba(35, 199, 136, 0.28); }",
            ".status.warn { background: var(--warn-soft); color: var(--warn); border-color: rgba(255, 179, 71, 0.28); }",
            ".status.error { background: var(--danger-soft); color: var(--danger); border-color: rgba(255, 106, 124, 0.28); }",
            ".status.muted { background: var(--accent-soft); color: var(--ink-soft); border-color: rgba(47, 182, 255, 0.2); }",
            "section, details { background: var(--panel); border: 1px solid var(--line); border-radius: 18px; padding: 18px; margin-bottom: 16px; box-shadow: 0 22px 54px rgba(2, 7, 15, 0.34); backdrop-filter: blur(10px); }",
            "h2 { margin: 0 0 14px; font-size: 18px; color: var(--ink); }",
            "table { width: 100%; table-layout: fixed; border-collapse: collapse; font-size: 14px; background: rgba(8, 18, 31, 0.34); border-radius: 14px; overflow: hidden; }",
            "th, td { border-bottom: 1px solid var(--line); padding: 10px 12px; vertical-align: top; text-align: left; overflow-wrap: anywhere; word-break: break-word; }",
            "th { width: 24%; color: var(--ink-soft); font-size: 12px; text-transform: uppercase; letter-spacing: 0.06em; background: rgba(16, 35, 58, 0.92); }",
            "td { color: var(--ink); }",
            "td code { white-space: pre-wrap; overflow-wrap: anywhere; word-break: break-word; }",
            ".cell-block { white-space: pre-wrap; word-break: break-word; max-height: 320px; overflow: auto; background: rgba(6, 17, 31, 0.92); border: 1px solid var(--line); border-radius: 12px; padding: 10px; font-family: ui-monospace, 'SFMono-Regular', Menlo, monospace; font-size: 12px; color: #d8e9fb; }",
            ".image-preview { margin-top: 10px; }",
            ".image-preview img { display: block; max-width: min(100%, 360px); max-height: 240px; border: 1px solid var(--line-strong); border-radius: 14px; background: rgba(4, 11, 21, 0.94); object-fit: contain; box-shadow: 0 14px 32px rgba(0, 0, 0, 0.34); }",
            ".section-note, .muted { color: var(--ink-soft); }",
            "summary { cursor: pointer; font-weight: 700; color: var(--accent); }",
            "pre { white-space: pre-wrap; word-break: break-word; background: rgba(4, 11, 21, 0.96); color: #d8f3dc; border: 1px solid var(--line); border-radius: 14px; padding: 16px; overflow: auto; }",
            "a { color: var(--accent); }",
            "</style>",
            "</head>",
            "<body>",
            "<div class='page'>",
            "<header class='hero'>",
            f"<h1>{html.escape(title)}</h1>",
            f"<div class='hero-meta'><span>Job: {html.escape(str(job_record.get('job_name') or job_record.get('job_id') or 'unknown'))}</span><span>Mode: {html.escape(mode)}</span><span>Backend: {html.escape(str(config.get('execution_backend') or '-'))}</span><span>Wrapper: {html.escape(str(job_record.get('wrapper_id') or 'None'))}</span></div>",
            f"<div class='status {status_class}'>{html.escape(str(mode_result.get('status', 'unknown')))}</div>",
            "</header>",
            sections_html,
            "<details><summary>Raw Mode JSON</summary>",
            "<pre>",
            html.escape(json.dumps(raw_payload, indent=2)),
            "</pre></details>",
            "</div></body></html>",
            "",
        ]
    )


def _write_mode_summary_reports(
    job_record: dict[str, Any],
    full_result: dict[str, Any],
    mode: str,
    mode_result: dict[str, Any],
    paths: dict[str, Path],
) -> dict[str, str]:
    job_id = str(job_record.get("job_id", "unknown"))
    payload = _build_mode_summary_payload(job_record, mode, mode_result)
    json_text = json.dumps(payload, indent=2) + "\n"
    html_text = _render_mode_summary_html(job_record, full_result, mode, mode_result)
    log_text = "\n".join(
        [
            f"job_id={job_id}",
            f"job_name={job_record.get('job_name', '')}",
            f"mode={mode}",
            f"wrapper={job_record.get('wrapper_id') or 'None'}",
            f"status={mode_result.get('status', 'unknown')}",
            f"backend={(job_record.get('configuration') or {}).get('execution_backend', '')}",
            f"frameworks={', '.join((job_record.get('configuration') or {}).get('frameworks') or []) or '-'}",
            "",
            json.dumps(payload, indent=2),
            "",
        ]
    )

    for key in ("results_json", "summary_results_json"):
        paths[key].write_text(json_text, encoding="utf-8")
    for key in ("report_html", "summary_report_html"):
        paths[key].write_text(html_text, encoding="utf-8")
    for key in ("run_log", "summary_run_log"):
        paths[key].write_text(log_text, encoding="utf-8")

    return {
        key: str(path.resolve())
        for key, path in paths.items()
    }


























def execute_job_record(job_record: dict[str, Any]) -> dict[str, Any]:
    wrapper_id = job_record.get("wrapper_id")
    config = job_record["configuration"]
    result: dict[str, Any] = {
        "execution_plan": build_execution_plan_object(job_record),
        "blackbox": None,
        "whitebox": None,
        "artifacts": {},
        "notes": [],
    }

    framework_runs: dict[str, Any] = {}
    if wrapper_id:
        adapter = _load_adapter(wrapper_id)
        capabilities = model_dump(adapter.capabilities())
        validation_errors = adapter.validate_config(job_record)
        if validation_errors:
            result["notes"].append({"type": "validation", "messages": validation_errors})

        scan_modes = set(config.get("scan_modes", []))
        supported_frameworks = [framework for framework in config.get("frameworks", []) if framework_supported(capabilities, framework)]
        wrapper_driven_scan = bool(supported_frameworks)
        if "blackbox" in scan_modes and wrapper_driven_scan:
            try:
                result["blackbox"] = adapter.run_blackbox_scan(job_record)
            except NotImplementedError as exc:
                result["notes"].append({"type": "blackbox_not_implemented", "message": str(exc)})
            except Exception as exc:
                result["blackbox"] = {
                    "status": "failed",
                    "error": repr(exc),
                }
                result["notes"].append({"type": "blackbox_failed", "message": repr(exc)})
        if "whitebox" in scan_modes and wrapper_driven_scan:
            try:
                result["whitebox"] = adapter.run_whitebox_scan(job_record)
            except NotImplementedError as exc:
                result["notes"].append({"type": "whitebox_not_implemented", "message": str(exc)})
            except Exception as exc:
                result["whitebox"] = {
                    "status": "failed",
                    "error": repr(exc),
                }
                result["notes"].append({"type": "whitebox_failed", "message": repr(exc)})
        for framework in config.get("frameworks", []):
            try:
                if framework_supported(capabilities, framework):
                    framework_runs[framework] = _run_adapter_framework_scan(framework, adapter, job_record)
                elif framework in {"pyrit", "garak", "textattack"}:
                    framework_runs[framework] = _run_builtin_framework_scan(framework, job_record)
                    result["notes"].append(
                        {
                            "type": f"{framework}_wrapper_ignored",
                            "message": f"Wrapper '{wrapper_id}' does not support framework '{framework}', so the built-in executor was used.",
                        }
                    )
                else:
                    framework_runs[framework] = _run_adapter_framework_scan(framework, adapter, job_record)
            except NotImplementedError as exc:
                result["notes"].append({"type": f"{framework}_not_implemented", "message": str(exc)})
            except Exception as exc:
                framework_runs[framework] = {
                    "status": "failed",
                    "framework": framework,
                    "error": repr(exc),
                }
                result["notes"].append({"type": f"{framework}_failed", "message": repr(exc)})
    else:
        for framework in config.get("frameworks", []):
            try:
                framework_runs[framework] = _run_builtin_framework_scan(framework, job_record)
            except NotImplementedError as exc:
                result["notes"].append({"type": f"{framework}_not_implemented", "message": str(exc)})
            except Exception as exc:
                framework_runs[framework] = {
                    "status": "failed",
                    "framework": framework,
                    "error": repr(exc),
                }
                result["notes"].append({"type": f"{framework}_failed", "message": repr(exc)})
        if not framework_runs:
            result["notes"].append(
                {
                    "type": "planned_only",
                    "message": "No wrapper was provided, so the backend stored the full execution plan but did not perform in-process white-box execution.",
                }
            )

    if framework_runs:
        result["framework_runs"] = framework_runs
        if len(framework_runs) == 1:
            _, framework_payload = next(iter(framework_runs.items()))
            if isinstance(framework_payload, dict) and framework_payload.get("tool_compatibility"):
                for mode in ("blackbox", "whitebox"):
                    mode_payload = result.get(mode)
                    if isinstance(mode_payload, dict) and not mode_payload.get("tool_compatibility"):
                        mode_payload["tool_compatibility"] = framework_payload["tool_compatibility"]

    if result["blackbox"] is None and "blackbox" in set(config.get("scan_modes", [])):
        if len(framework_runs) == 1:
            framework_name, framework_payload = next(iter(framework_runs.items()))
            if framework_name in {"garak", "pyrit", "textattack"} and isinstance(framework_payload, dict):
                result["blackbox"] = _project_framework_run_to_blackbox(framework_name, framework_payload)

    return _attach_mode_summary_artifacts(job_record, result)


# Task 7: job lifecycle / preflight / templates extracted to sibling modules.
# Re-export for backward compatibility — the old contract
#   `from sentinel.executor import create_job`
# still works. New code should prefer the direct import:
#   `from sentinel.jobs import create_job`.
#
# IMPORTANT: this shim lives at the bottom of the file so that every top-level
# name in executor.py (BUILTIN_WRAPPERS, FRAMEWORK_RUNTIME_SPECS, now_utc,
# model_dump, default_options, framework_runtime_inventory, _load_adapter,
# _write_mode_summary_reports, etc.) is already bound by the time the new
# modules' function bodies do lazy `from .executor import ...` lookups.
from .templates import (
    create_template,
    delete_template,
    export_template,
    import_template,
    list_templates,
    save_template,
    sync_builtin_templates,
    update_template,
)
from .preflight import (
    FRAMEWORK_RUNTIME_SPECS,
    LOCAL_OLLAMA_DEFAULT_TAGS_URL,
    LOCAL_OLLAMA_HOST_MARKERS,
    _frameworks_requiring_wrapper,
    _looks_like_local_ollama_endpoint,
    _model_available_in_ollama,
    _ollama_tags_url,
    _probe_ollama_tags,
    build_preflight,
    evaluate_platform_support,
    evaluate_runtime_readiness,
    evaluate_wrapper_compatibility,
    local_service_inventory,
    python_runtime_summary,
    report_expectations,
)
from .jobs import (
    _artifact_group_for_path,
    _artifact_name_for_path,
    _attach_mode_summary_artifacts,
    _discover_artifacts_from_filesystem,
    _invalidate_wrapper_cache,
    _mirror_mode_runtime_artifacts,
    _normalize_artifact_name,
    _path_matches_job,
    _project_framework_run_to_blackbox,
    _read_terminal_text,
    _run_adapter_framework_scan,
    _run_builtin_framework_scan,
    _valid_wrapper_record,
    build_execution_plan,
    build_execution_plan_object,
    build_job_terminal_view,
    collect_job_artifacts,
    create_job,
    list_jobs,
    list_wrappers,
    normalize_task_family,
    reconcile_job_statuses,
    register_wrapper,
    run_job,
    sync_builtin_wrappers,
)
