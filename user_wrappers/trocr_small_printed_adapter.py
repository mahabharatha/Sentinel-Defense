from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

import torch
from PIL import Image
from transformers import TrOCRProcessor, VisionEncoderDecoderModel

from whitebox_scan_platform.contracts import BaseScanAdapter, WrapperCapabilities


class TrOCRSmallPrintedAdapter(BaseScanAdapter):
    """Real OCR wrapper backed by microsoft/trocr-small-printed."""

    MODEL_ID = "microsoft/trocr-small-printed"
    _processor: TrOCRProcessor | None = None
    _model: VisionEncoderDecoderModel | None = None

    def capabilities(self) -> WrapperCapabilities:
        return WrapperCapabilities(
            wrapper_id="trocr_small_printed_adapter",
            display_name="TrOCR Small Printed Adapter",
            supports_blackbox=True,
            supports_whitebox=False,
            supports_api_models=False,
            supports_python_process_models=True,
            supports_art=False,
            supports_foolbox=False,
            supports_pyrit=False,
            supports_garak=False,
            supports_giskard=False,
            supports_promptfoo=False,
            supports_textattack=False,
            supports_logits=False,
            supports_gradients=False,
            supported_modalities=["vision"],
            supported_frameworks=[],
            notes="Runs real OCR with microsoft/trocr-small-printed on a local image path.",
        )

    @classmethod
    def _load_components(cls, model_id: str) -> tuple[TrOCRProcessor, VisionEncoderDecoderModel]:
        if cls._processor is None or cls._model is None:
            cls._processor = TrOCRProcessor.from_pretrained(model_id, use_fast=False)
            cls._model = VisionEncoderDecoderModel.from_pretrained(model_id)
            cls._model.eval()
        return cls._processor, cls._model

    def validate_config(self, config: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        configuration = config.get("configuration", {})
        model = config.get("model", {})
        sample_path = str(configuration.get("sample_path", "")).strip()

        if configuration.get("execution_backend") != "python_process_wrapped":
            errors.append("TrOCRSmallPrintedAdapter requires the python_process_wrapped backend.")
        if model.get("modality") != "vision":
            errors.append("TrOCRSmallPrintedAdapter requires model modality 'vision'.")
        if model.get("task_family") != "ocr":
            errors.append("TrOCRSmallPrintedAdapter requires task family 'ocr'.")
        if not sample_path:
            errors.append("Sample Path must point to an input image file.")
        elif not Path(sample_path).expanduser().exists():
            errors.append(f"Sample image '{sample_path}' was not found.")
        if "whitebox" in set(configuration.get("scan_modes", [])):
            errors.append("TrOCRSmallPrintedAdapter only supports black-box OCR runs.")
        selected_frameworks = configuration.get("frameworks", [])
        if selected_frameworks:
            errors.append(
                "TrOCRSmallPrintedAdapter does not advertise any framework integrations yet; leave frameworks empty for a truthful OCR run."
            )
        return errors

    def _run_ocr(self, config: dict[str, Any]) -> dict[str, Any]:
        job_id = config.get("job_id", "adhoc")
        model = config.get("model", {})
        configuration = config.get("configuration", {})

        model_id = str(model.get("source_value") or model.get("model_id") or self.MODEL_ID).strip() or self.MODEL_ID
        sample_path = Path(str(configuration.get("sample_path", "")).strip()).expanduser().resolve()
        output_dir = Path(__file__).resolve().parents[1] / "data" / "ocr_runs" / job_id
        reports_dir = output_dir / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)

        processor, trocr_model = self._load_components(model_id)

        with Image.open(sample_path) as image_fp:
            image = image_fp.convert("RGB")
        pixel_values = processor(images=image, return_tensors="pt").pixel_values

        with torch.inference_mode():
            generated_ids = trocr_model.generate(pixel_values)
        extracted_text = processor.batch_decode(generated_ids, skip_special_tokens=True)[0].strip()

        results = {
            "status": "completed",
            "adapter": self.capabilities().wrapper_id,
            "model_id": model_id,
            "sample_path": str(sample_path),
            "ocr_text": extracted_text,
        }

        run_log = reports_dir / "run_log.txt"
        results_json = reports_dir / "results.json"
        report_html = reports_dir / "report.html"

        run_log.write_text(
            "\n".join(
                [
                    f"job_id={job_id}",
                    f"adapter={self.capabilities().wrapper_id}",
                    f"model_id={model_id}",
                    f"sample_path={sample_path}",
                    f"ocr_text={extracted_text}",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        results_json.write_text(json.dumps(results, indent=2), encoding="utf-8")
        report_html.write_text(
            "\n".join(
                [
                    "<html><body>",
                    "<h1>OCR Smoke Report</h1>",
                    f"<p><strong>Model:</strong> {html.escape(model_id)}</p>",
                    f"<p><strong>Sample:</strong> {html.escape(str(sample_path))}</p>",
                    f"<p><strong>Extracted text:</strong> {html.escape(extracted_text)}</p>",
                    "</body></html>",
                    "",
                ]
            ),
            encoding="utf-8",
        )

        results["artifacts"] = {
            "results_json": str(results_json.resolve()),
            "report_html": str(report_html.resolve()),
            "run_log": str(run_log.resolve()),
        }
        return results

    def run_blackbox_scan(self, config: dict[str, Any]) -> dict[str, Any]:
        return self._run_ocr(config)

    def run_whitebox_scan(self, config: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError("TrOCRSmallPrintedAdapter does not implement white-box OCR scanning.")

    def run_framework_scan(self, framework: str, config: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError(f"TrOCRSmallPrintedAdapter does not implement framework '{framework}'.")
