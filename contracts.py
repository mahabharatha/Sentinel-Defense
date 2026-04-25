from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class WrapperCapabilities:
    wrapper_id: str
    display_name: str
    supports_blackbox: bool = True
    supports_whitebox: bool = False
    supports_api_models: bool = True
    supports_python_process_models: bool = True
    supports_art: bool = False
    supports_foolbox: bool = False
    supports_pyrit: bool = False
    supports_garak: bool = False
    supports_giskard: bool = False
    supports_promptfoo: bool = False
    supports_textattack: bool = False
    supports_logits: bool = False
    supports_gradients: bool = False
    supported_modalities: list[str] = field(default_factory=list)
    supported_task_families: list[str] = field(default_factory=list)
    supported_frameworks: list[str] = field(default_factory=list)
    notes: str = ""


class BaseScanAdapter(ABC):
    """Contract for user-provided wrappers/adapters."""

    @abstractmethod
    def capabilities(self) -> WrapperCapabilities:
        raise NotImplementedError

    def validate_config(self, config: dict[str, Any]) -> list[str]:
        return []

    def run_blackbox_scan(self, config: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError("Black-box scan is not implemented by this adapter.")

    def run_whitebox_scan(self, config: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError("White-box scan is not implemented by this adapter.")

    def run_framework_scan(self, framework: str, config: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError(f"Framework-specific scan '{framework}' is not implemented by this adapter.")

    def run_scan(self, config: dict[str, Any]) -> dict[str, Any]:
        modes = set(config.get("scan_modes", []))
        frameworks = list(config.get("frameworks", []))
        result: dict[str, Any] = {"blackbox": None, "whitebox": None, "framework_runs": {}}
        if "blackbox" in modes:
            result["blackbox"] = self.run_blackbox_scan(config)
        if "whitebox" in modes:
            result["whitebox"] = self.run_whitebox_scan(config)
        for framework in frameworks:
            try:
                result["framework_runs"][framework] = self.run_framework_scan(framework, config)
            except NotImplementedError:
                continue
        return result
