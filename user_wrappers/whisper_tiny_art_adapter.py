from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from whitebox_scan_platform.contracts import BaseScanAdapter, WrapperCapabilities


class WhisperTinyArtAdapter(BaseScanAdapter):
    """Real ART-backed adapter using the existing Whisper Tiny demo harness."""

    def capabilities(self) -> WrapperCapabilities:
        return WrapperCapabilities(
            wrapper_id="whisper_tiny_art_adapter",
            display_name="Whisper Tiny ART Adapter",
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
            supports_logits=False,
            supports_gradients=True,
            supported_modalities=["audio"],
            supported_task_families=["speech-to-text"],
            supported_frameworks=["art"],
            notes="Runs the real IBM ART Whisper Tiny harness in-process via the shared demo module.",
        )

    def validate_config(self, config: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        frameworks = set(config.get("configuration", {}).get("frameworks", []))
        if "art" not in frameworks:
            errors.append("WhisperTinyArtAdapter is only meaningful when the ART framework is selected.")
        if config.get("configuration", {}).get("execution_backend") != "python_process_wrapped":
            errors.append("WhisperTinyArtAdapter requires the python_process_wrapped backend.")
        return errors

    def run_blackbox_scan(self, config: dict[str, Any]) -> dict[str, Any]:
        return {
            "status": "delegated_to_art",
            "message": "The current real integration path is the ART harness; black-box-only logic is not separated in this adapter.",
        }

    def run_whitebox_scan(self, config: dict[str, Any]) -> dict[str, Any]:
        return {
            "status": "delegated_to_framework",
            "framework": "art",
            "message": "Use the ART framework execution path for the real white-box run.",
        }

    def run_framework_scan(self, framework: str, config: dict[str, Any]) -> dict[str, Any]:
        if framework != "art":
            raise NotImplementedError(f"WhisperTinyArtAdapter does not implement framework '{framework}'.")

        from whitebox_scan_platform.vendored.whisper_art_demo.runner import (
            DEFAULT_MODEL_ID,
            build_html_report,
            run_scan,
            write_json,
        )

        job_id = config.get("job_id", "adhoc")
        configuration = config.get("configuration", {})
        sample_path = configuration.get("sample_path") or "rhel_art_audio_demo/samples/demo_tone.wav"
        output_dir = Path(__file__).resolve().parents[1] / "data" / "art_runs" / job_id
        args = SimpleNamespace(
            audio=sample_path,
            create_demo_audio=not Path(sample_path).exists(),
            model_id=config.get("model", {}).get("source_value") or DEFAULT_MODEL_ID,
            device="cpu",
            clip_seconds=5.0,
            target_text=configuration.get("target_text") or "ATTACK TEST",
            output_dir=str(output_dir),
        )
        report = run_scan(args)
        reports_dir = output_dir / "reports"
        results_json = reports_dir / "results.json"
        report_html = reports_dir / "report.html"
        write_json(results_json, report)
        build_html_report(report, report_html)
        return {
            "status": "completed",
            "framework": "art",
            "adapter": self.capabilities().wrapper_id,
            "report": report,
            "artifacts": {
                "results_json": str(results_json.resolve()),
                "report_html": str(report_html.resolve()),
                "run_log": str((output_dir / "reports" / "run_log.txt").resolve()),
            },
        }
