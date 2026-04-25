from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .executors.art_executor import run_art_scan
from .executors.foolbox_executor import run_foolbox_scan
from .executors.garak_executor import run_garak_scan
from .executors.pyrit_executor import run_pyrit_scan
from .executors.textattack_executor import run_textattack_scan


AdapterRunner = Callable[[Any, dict[str, Any]], dict[str, Any]]
BuiltinRunner = Callable[[dict[str, Any]], dict[str, Any]]


@dataclass(frozen=True)
class FrameworkDescriptor:
    name: str
    capability_flag: str
    support_paths: list[dict[str, Any]]
    adapter_runner: AdapterRunner | None = None
    builtin_runner: BuiltinRunner | None = None


_ART_SUPPORT_PATHS = [
    {
        "implemented": True,
        "backend": "python_process_wrapped",
        "modalities": ["audio"],
        "task_families": ["speech-to-text"],
        "scan_modes": ["blackbox", "whitebox"],
        "wrappers": ["hf_speech_to_text_art_adapter", "whisper_tiny_art_adapter"],
        "summary": "Real IBM ART speech-to-text path via the generalized HF adapter and the Whisper Tiny reference adapter.",
    },
    {
        "implemented": True,
        "backend": "python_process_wrapped",
        "modalities": ["vision"],
        "task_families": ["ocr"],
        "scan_modes": ["blackbox", "whitebox"],
        "wrappers": ["hf_ocr_art_adapter", "trocr_small_art_adapter"],
        "summary": "Real IBM ART OCR path via the generic HF OCR adapter and the pinned TrOCR reference adapter.",
    },
    {
        "implemented": True,
        "backend": "python_process_wrapped",
        "modalities": ["vision"],
        "task_families": ["vision-classification"],
        "scan_modes": ["blackbox", "whitebox"],
        "wrappers": ["hf_vision_classification_art_adapter"],
        "summary": "Real IBM ART vision-classification path for Hugging Face image classifiers.",
    },
]

_FOOLBOX_SUPPORT_PATHS = [
    {
        "implemented": True,
        "backend": "python_process_wrapped",
        "modalities": ["vision"],
        "task_families": ["vision-classification"],
        "scan_modes": ["blackbox", "whitebox"],
        "wrappers": ["hf_vision_foolbox_adapter"],
        "summary": "Real Foolbox path for Hugging Face vision classification models.",
    },
    {
        "implemented": False,
        "backend": "python_process_wrapped",
        "modalities": ["audio"],
        "task_families": ["audio-classification"],
        "scan_modes": ["blackbox", "whitebox"],
        "wrappers": [],
        "summary": "Planned next Foolbox path for audio classification.",
    },
]

_PYRIT_SUPPORT_PATHS = [
    {
        "implemented": True,
        "backend": "api_based",
        "modalities": ["text", "multimodal"],
        "task_families": ["multimodal-chat", "text-generation"],
        "scan_modes": ["blackbox"],
        "wrappers": [],
        "requires_wrapper": False,
        "summary": "Real PyRIT black-box path for text and Vision-Language OpenAI-compatible chat endpoints via the built-in executor.",
    }
]

_GARAK_SUPPORT_PATHS = [
    {
        "implemented": True,
        "backend": "api_based",
        "modalities": ["text"],
        "task_families": ["multimodal-chat", "text-generation"],
        "scan_modes": ["blackbox"],
        "wrappers": [],
        "requires_wrapper": False,
        "summary": "Real Garak black-box probe path for conversational API targets via the built-in REST generator flow.",
    },
    {
        "implemented": True,
        "backend": "python_process_wrapped",
        "modalities": ["text"],
        "task_families": ["text-generation"],
        "scan_modes": ["blackbox"],
        "wrappers": [],
        "requires_wrapper": False,
        "summary": "Built-in Garak local generator smoke path for validating Garak probes when REST support is unavailable in the installed Garak version.",
    },
]

_TEXTATTACK_SUPPORT_PATHS = [
    {
        "implemented": True,
        "backend": "python_process_wrapped",
        "modalities": ["text"],
        "task_families": ["text-classification"],
        "scan_modes": ["blackbox"],
        "requires_wrapper": False,
        "wrappers": [],
        "summary": "Real built-in TextAttack first-landing path for in-process text-classification only. API targets, multimodal, text-generation, and white-box execution remain intentionally out of scope.",
    }
]


FRAMEWORK_DESCRIPTORS: dict[str, FrameworkDescriptor] = {
    "art": FrameworkDescriptor(
        name="art",
        capability_flag="supports_art",
        support_paths=_ART_SUPPORT_PATHS,
        adapter_runner=run_art_scan,
    ),
    "foolbox": FrameworkDescriptor(
        name="foolbox",
        capability_flag="supports_foolbox",
        support_paths=_FOOLBOX_SUPPORT_PATHS,
        adapter_runner=run_foolbox_scan,
    ),
    "pyrit": FrameworkDescriptor(
        name="pyrit",
        capability_flag="supports_pyrit",
        support_paths=_PYRIT_SUPPORT_PATHS,
        builtin_runner=run_pyrit_scan,
    ),
    "garak": FrameworkDescriptor(
        name="garak",
        capability_flag="supports_garak",
        support_paths=_GARAK_SUPPORT_PATHS,
        builtin_runner=run_garak_scan,
    ),
    "textattack": FrameworkDescriptor(
        name="textattack",
        capability_flag="supports_textattack",
        support_paths=_TEXTATTACK_SUPPORT_PATHS,
        builtin_runner=run_textattack_scan,
    ),
}

FRAMEWORK_CAPABILITY_FLAGS = {
    framework: descriptor.capability_flag
    for framework, descriptor in FRAMEWORK_DESCRIPTORS.items()
}

FRAMEWORK_SUPPORT_MATRIX = {
    framework: descriptor.support_paths
    for framework, descriptor in FRAMEWORK_DESCRIPTORS.items()
}


def default_framework_order() -> list[str]:
    return list(FRAMEWORK_DESCRIPTORS)


def framework_supported(capabilities: dict[str, Any], framework: str) -> bool:
    supported_frameworks = set(capabilities.get("supported_frameworks") or [])
    flag_name = FRAMEWORK_CAPABILITY_FLAGS.get(framework)
    flag_value = bool(capabilities.get(flag_name, False)) if flag_name else False
    if supported_frameworks:
        return framework in supported_frameworks or flag_value
    return flag_value


def run_builtin_framework_scan(framework: str, job_record: dict[str, Any]) -> dict[str, Any]:
    descriptor = FRAMEWORK_DESCRIPTORS.get(framework)
    if descriptor is None or descriptor.builtin_runner is None:
        raise NotImplementedError(f"No built-in framework executor is implemented for '{framework}'.")
    return descriptor.builtin_runner(job_record)


def run_adapter_framework_scan(framework: str, adapter: Any, job_record: dict[str, Any]) -> dict[str, Any]:
    descriptor = FRAMEWORK_DESCRIPTORS.get(framework)
    if descriptor is not None and descriptor.adapter_runner is not None:
        return descriptor.adapter_runner(adapter, job_record)
    return adapter.run_framework_scan(framework, job_record)
