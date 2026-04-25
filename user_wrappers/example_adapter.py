from __future__ import annotations

from whitebox_scan_platform.contracts import BaseScanAdapter, WrapperCapabilities


class ExampleAdapter(BaseScanAdapter):
    def capabilities(self) -> WrapperCapabilities:
        return WrapperCapabilities(
            wrapper_id="example_adapter",
            display_name="Example Adapter",
            supports_blackbox=True,
            supports_whitebox=True,
            supports_api_models=True,
            supports_python_process_models=True,
            supports_art=True,
            supports_foolbox=True,
            supports_pyrit=True,
            supports_garak=True,
            supports_textattack=True,
            supports_logits=True,
            supports_gradients=True,
            supported_modalities=["audio", "vision", "multimodal"],
            supported_frameworks=["art", "foolbox", "pyrit", "garak", "textattack"],
            notes="Example scaffold adapter for trusted local development.",
        )

    def run_blackbox_scan(self, config: dict):
        return {
            "status": "planned",
            "message": "Replace with real black-box scan execution.",
            "frameworks": config["configuration"]["frameworks"],
        }

    def run_whitebox_scan(self, config: dict):
        return {
            "status": "planned",
            "message": "Replace with real white-box ART/Foolbox execution.",
            "frameworks": config["configuration"]["frameworks"],
        }

    def run_framework_scan(self, framework: str, config: dict):
        return {
            "status": "planned",
            "framework": framework,
            "message": f"Replace with real {framework} executor integration.",
        }
