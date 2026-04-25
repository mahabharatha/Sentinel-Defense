from __future__ import annotations

from pathlib import Path
from typing import Any

from whitebox_scan_platform.contracts import BaseScanAdapter, WrapperCapabilities


class HFVisionClassificationArtAdapter(BaseScanAdapter):
    """Real IBM ART adapter for Hugging Face vision-classification models."""

    def capabilities(self) -> WrapperCapabilities:
        return WrapperCapabilities(
            wrapper_id="hf_vision_classification_art_adapter",
            display_name="HF Vision Classification ART Adapter",
            supports_blackbox=True,
            supports_whitebox=True,
            supports_api_models=False,
            supports_python_process_models=True,
            supports_art=True,
            supports_foolbox=False,
            supports_pyrit=False,
            supports_garak=False,
            supports_giskard=False,
            supports_promptfoo=False,
            supports_textattack=False,
            supports_logits=True,
            supports_gradients=True,
            supported_modalities=["vision"],
            supported_task_families=["vision-classification", "image-classification"],
            supported_frameworks=["art"],
            notes="Runs real IBM ART image attacks against Hugging Face vision classification models.",
        )

    def validate_config(self, config: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        configuration = config.get("configuration", {})
        model = config.get("model", {})
        sample_path = str(configuration.get("sample_path", "")).strip()
        frameworks = set(configuration.get("frameworks", []))
        task_family = str(model.get("task_family", "")).strip().lower()

        if configuration.get("execution_backend") != "python_process_wrapped":
            errors.append("HFVisionClassificationArtAdapter requires the python_process_wrapped backend.")
        if model.get("modality") != "vision":
            errors.append("HFVisionClassificationArtAdapter requires model modality 'vision'.")
        if task_family not in {"vision-classification", "image-classification"}:
            errors.append(
                "HFVisionClassificationArtAdapter requires task family 'vision-classification' or 'image-classification'."
            )
        if "art" not in frameworks:
            errors.append("HFVisionClassificationArtAdapter requires the IBM ART framework to be selected.")
        if not sample_path:
            errors.append("Sample Path must point to an input image file.")
        elif not Path(sample_path).expanduser().exists():
            errors.append(f"Sample image '{sample_path}' was not found.")
        return errors

    def _run_art(self, config: dict[str, Any]) -> dict[str, Any]:
        from whitebox_scan_platform.vendored.hf_vision_art_demo.runner import run_scan

        job_id = config.get("job_id", "adhoc")
        configuration = config.get("configuration", {})
        output_dir = Path(__file__).resolve().parents[1] / "data" / "art_runs" / job_id
        report = run_scan(
            image_path=configuration.get("sample_path") or "data/demo/ocr_sample.png",
            output_dir=str(output_dir),
            model_id=config.get("model", {}).get("source_value") or "microsoft/resnet-18",
            max_iter=int(configuration.get("max_iter") or 5),
        )
        reports_dir = output_dir / "reports"
        return {
            "status": "completed",
            "framework": "art",
            "adapter": self.capabilities().wrapper_id,
            "report": report,
            "artifacts": {
                "results_json": str((reports_dir / "results.json").resolve()),
                "report_html": str((reports_dir / "report.html").resolve()),
                "run_log": str((reports_dir / "run_log.txt").resolve()),
                "whitebox_results_json": str((reports_dir / "whitebox_results.json").resolve()),
                "whitebox_report_html": str((reports_dir / "whitebox_report.html").resolve()),
                "whitebox_run_log": str((reports_dir / "whitebox_run_log.txt").resolve()),
                "blackbox_results_json": str((reports_dir / "blackbox_results.json").resolve()),
                "blackbox_report_html": str((reports_dir / "blackbox_report.html").resolve()),
                "blackbox_run_log": str((reports_dir / "blackbox_run_log.txt").resolve()),
            },
        }

    def _reports_dir(self, config: dict[str, Any]) -> Path:
        job_id = config.get("job_id", "adhoc")
        return Path(__file__).resolve().parents[1] / "data" / "art_runs" / job_id / "reports"

    def run_blackbox_scan(self, config: dict[str, Any]) -> dict[str, Any]:
        artifact = self._run_art(config)
        report = artifact["report"]
        reports_dir = self._reports_dir(config)
        return {
            "status": "completed",
            "mode": "blackbox",
            "adapter": self.capabilities().wrapper_id,
            "message": "Recorded the clean vision-classification baseline used by the ART run.",
            "clean_result": report.get("clean_result"),
            "artifacts": {
                "blackbox_results_json": str((reports_dir / "blackbox_results.json").resolve()),
                "blackbox_report_html": str((reports_dir / "blackbox_report.html").resolve()),
                "blackbox_run_log": str((reports_dir / "blackbox_run_log.txt").resolve()),
            },
        }

    def run_whitebox_scan(self, config: dict[str, Any]) -> dict[str, Any]:
        artifact = self._run_art(config)
        reports_dir = self._reports_dir(config)
        return {
            "status": "completed",
            "mode": "whitebox",
            "framework": "art",
            "adapter": self.capabilities().wrapper_id,
            "report": artifact["report"],
            "artifacts": {
                "whitebox_results_json": str((reports_dir / "whitebox_results.json").resolve()),
                "whitebox_report_html": str((reports_dir / "whitebox_report.html").resolve()),
                "whitebox_run_log": str((reports_dir / "whitebox_run_log.txt").resolve()),
            },
        }

    def run_framework_scan(self, framework: str, config: dict[str, Any]) -> dict[str, Any]:
        if framework != "art":
            raise NotImplementedError(f"HFVisionClassificationArtAdapter does not implement framework '{framework}'.")
        return self._run_art(config)
