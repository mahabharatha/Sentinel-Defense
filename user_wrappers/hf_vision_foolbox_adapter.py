from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from PIL import Image

from whitebox_scan_platform.contracts import BaseScanAdapter, WrapperCapabilities


def _now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _task_family_alias(value: str) -> str:
    cleaned = str(value or "").strip().lower()
    if cleaned == "image-classification":
        return "vision-classification"
    return cleaned


class _HFVisionBoundary(nn.Module):
    def __init__(
        self,
        *,
        model: nn.Module,
        resize_height: int,
        resize_width: int,
        mean: list[float],
        std: list[float],
    ) -> None:
        super().__init__()
        self.model = model
        self.resize_height = int(resize_height)
        self.resize_width = int(resize_width)
        mean_tensor = torch.tensor(mean, dtype=torch.float32).view(1, -1, 1, 1)
        std_tensor = torch.tensor(std, dtype=torch.float32).view(1, -1, 1, 1)
        self.register_buffer("mean", mean_tensor)
        self.register_buffer("std", std_tensor)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        resized = F.interpolate(
            x,
            size=(self.resize_height, self.resize_width),
            mode="bilinear",
            align_corners=False,
        )
        normalized = (resized - self.mean) / self.std
        return self.model(pixel_values=normalized).logits


class HFVisionClassificationFoolboxAdapter(BaseScanAdapter):
    def __init__(self) -> None:
        self._runtime_cache: dict[str, dict[str, Any]] = {}
        self._mode_cache: dict[tuple[str, str], dict[str, Any]] = {}
        self._framework_cache: dict[str, dict[str, Any]] = {}

    def capabilities(self) -> WrapperCapabilities:
        return WrapperCapabilities(
            wrapper_id="hf_vision_foolbox_adapter",
            display_name="HF Vision Foolbox Adapter",
            supports_blackbox=True,
            supports_whitebox=True,
            supports_api_models=False,
            supports_python_process_models=True,
            supports_art=False,
            supports_foolbox=True,
            supports_pyrit=False,
            supports_garak=False,
            supports_giskard=False,
            supports_promptfoo=False,
            supports_textattack=False,
            supports_logits=True,
            supports_gradients=True,
            supported_modalities=["vision"],
            supported_task_families=["vision-classification", "image-classification"],
            supported_frameworks=["foolbox"],
            notes="Runs real Foolbox attacks against Hugging Face vision classification models.",
        )

    def validate_config(self, config: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        configuration = config.get("configuration", {})
        model = config.get("model", {})
        sample_path = str(configuration.get("sample_path", "")).strip()
        frameworks = set(configuration.get("frameworks", []))
        task_family = _task_family_alias(model.get("task_family", ""))

        if configuration.get("execution_backend") != "python_process_wrapped":
            errors.append("HFVisionClassificationFoolboxAdapter requires the python_process_wrapped backend.")
        if model.get("modality") != "vision":
            errors.append("HFVisionClassificationFoolboxAdapter requires model modality 'vision'.")
        if task_family != "vision-classification":
            errors.append(
                "HFVisionClassificationFoolboxAdapter requires task family 'vision-classification' or 'image-classification'."
            )
        if "foolbox" not in frameworks:
            errors.append("HFVisionClassificationFoolboxAdapter requires the Foolbox framework to be selected.")
        if not sample_path:
            errors.append("Sample Path must point to an input image file.")
        elif not Path(sample_path).expanduser().exists():
            errors.append(f"Sample image '{sample_path}' was not found.")

        try:
            import foolbox  # noqa: F401
        except Exception as exc:
            errors.append(f"Foolbox is not available in the current environment: {exc!r}")

        return errors

    def _reports_root(self, config: dict[str, Any]) -> Path:
        job_id = str(config.get("job_id", "adhoc"))
        root = Path(__file__).resolve().parents[1] / "data" / "foolbox_runs" / job_id
        (root / "reports" / "images").mkdir(parents=True, exist_ok=True)
        return root

    def _resolve_image_size(self, processor: Any) -> tuple[int, int]:
        crop_size = getattr(processor, "crop_size", None)
        size = getattr(processor, "size", None)
        for candidate in (crop_size, size):
            if isinstance(candidate, dict):
                height = candidate.get("height") or candidate.get("shortest_edge") or candidate.get("size")
                width = candidate.get("width") or candidate.get("shortest_edge") or candidate.get("size")
                if height and width:
                    return int(height), int(width)
            if isinstance(candidate, int):
                return int(candidate), int(candidate)
        return 224, 224

    def _image_to_tensor(self, image_path: str) -> torch.Tensor:
        image = Image.open(image_path).convert("RGB")
        array = np.asarray(image, dtype=np.float32) / 255.0
        tensor = torch.from_numpy(array).permute(2, 0, 1).unsqueeze(0)
        return tensor

    def _label_name(self, runtime: dict[str, Any], label_id: int) -> str:
        config = runtime["hf_model"].config
        id2label = getattr(config, "id2label", {}) or {}
        if label_id in id2label:
            return str(id2label[label_id])
        if str(label_id) in id2label:
            return str(id2label[str(label_id)])
        return f"class_{label_id}"

    def _load_runtime(self, config: dict[str, Any]) -> dict[str, Any]:
        job_id = str(config.get("job_id", "adhoc"))
        cached = self._runtime_cache.get(job_id)
        if cached is not None:
            return cached

        from transformers import AutoImageProcessor, AutoModelForImageClassification
        import foolbox as fb

        model_info = config.get("model", {})
        source_value = model_info.get("source_value") or model_info.get("model_id")
        extra_options = (config.get("configuration") or {}).get("extra_options") or {}
        preferred_device = str(extra_options.get("device") or "").strip().lower()
        if preferred_device:
            device = torch.device(preferred_device)
        else:
            device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

        processor = AutoImageProcessor.from_pretrained(source_value)
        hf_model = AutoModelForImageClassification.from_pretrained(source_value)
        hf_model.eval()
        hf_model.to(device)

        resize_height, resize_width = self._resolve_image_size(processor)
        mean = [float(value) for value in (getattr(processor, "image_mean", None) or [0.5, 0.5, 0.5])]
        std = [float(value) for value in (getattr(processor, "image_std", None) or [0.5, 0.5, 0.5])]

        boundary = _HFVisionBoundary(
            model=hf_model,
            resize_height=resize_height,
            resize_width=resize_width,
            mean=mean,
            std=std,
        ).to(device)
        boundary.eval()

        sample_path = str((config.get("configuration") or {}).get("sample_path") or "")
        clean_inputs = self._image_to_tensor(sample_path).to(device)
        with torch.no_grad():
            clean_logits = boundary(clean_inputs)
        clean_label_id = int(clean_logits.argmax(dim=1).item())
        labels = torch.tensor([clean_label_id], device=device)
        fmodel = fb.PyTorchModel(boundary, bounds=(0.0, 1.0), device=device)

        runtime = {
            "device": device,
            "processor": processor,
            "hf_model": hf_model,
            "boundary": boundary,
            "fmodel": fmodel,
            "inputs": clean_inputs,
            "clean_logits": clean_logits,
            "clean_label_id": clean_label_id,
            "clean_label_name": self._label_name({"hf_model": hf_model}, clean_label_id),
            "labels": labels,
            "source_value": source_value,
        }
        self._runtime_cache[job_id] = runtime
        return runtime

    def _tensor_to_image(self, tensor: torch.Tensor, destination: Path) -> None:
        clipped = tensor.detach().cpu().clamp(0.0, 1.0)
        array = (clipped.permute(1, 2, 0).numpy() * 255.0).round().astype(np.uint8)
        Image.fromarray(array).save(destination)

    def _run_attack(
        self,
        *,
        runtime: dict[str, Any],
        config: dict[str, Any],
        scope: str,
        attack_name: str,
        attack_factory: Callable[[], Any],
        epsilons: list[float],
        rationale: str,
    ) -> dict[str, Any]:
        reports_root = self._reports_root(config)
        images_dir = reports_root / "reports" / "images"
        started_at = _now_utc()

        try:
            attack = attack_factory()
            raw_advs, clipped_advs, is_adv = attack(
                runtime["fmodel"],
                runtime["inputs"],
                runtime["labels"],
                epsilons=epsilons,
            )
            success_tensor = is_adv.detach().cpu().numpy().astype(bool)
            success_by_epsilon = [bool(value) for value in success_tensor[:, 0].tolist()]
            selected_index = next((idx for idx, value in enumerate(success_by_epsilon) if value), len(epsilons) - 1)
            if isinstance(clipped_advs, list):
                selected_adv = clipped_advs[selected_index][0].detach().cpu()
            else:
                selected_adv = clipped_advs[selected_index, 0].detach().cpu()
            selected_epsilon = float(epsilons[selected_index])

            with torch.no_grad():
                adv_logits = runtime["boundary"](selected_adv.unsqueeze(0).to(runtime["device"]))
            adversarial_label_id = int(adv_logits.argmax(dim=1).item())
            adversarial_label_name = self._label_name(runtime, adversarial_label_id)

            diff = selected_adv - runtime["inputs"][0].detach().cpu()
            linf = float(diff.abs().max().item())
            l2 = float(torch.norm(diff.reshape(-1), p=2).item())

            image_path = images_dir / f"{scope}_{attack_name}_adv.png"
            self._tensor_to_image(selected_adv, image_path)
            return {
                "attack_name": attack_name,
                "framework": "foolbox",
                "scope": scope,
                "status": "completed",
                "started_at_utc": started_at,
                "finished_at_utc": _now_utc(),
                "rationale": rationale,
                "attack_type": "whitebox" if scope == "whitebox" else "blackbox",
                "success": bool(success_by_epsilon[selected_index]),
                "success_by_epsilon": success_by_epsilon,
                "selected_epsilon": selected_epsilon,
                "epsilons": [float(value) for value in epsilons],
                "clean_label_id": runtime["clean_label_id"],
                "clean_label_name": runtime["clean_label_name"],
                "adversarial_label_id": adversarial_label_id,
                "adversarial_label_name": adversarial_label_name,
                "prediction_changed": adversarial_label_id != runtime["clean_label_id"],
                "perturbation_linf": linf,
                "perturbation_l2": l2,
                "artifacts": {
                    "adversarial_image": str(image_path.resolve()),
                },
            }
        except Exception as exc:
            return {
                "attack_name": attack_name,
                "framework": "foolbox",
                "scope": scope,
                "status": "failed",
                "started_at_utc": started_at,
                "finished_at_utc": _now_utc(),
                "rationale": rationale,
                "error": repr(exc),
                "success": False,
                "success_by_epsilon": [],
                "epsilons": [float(value) for value in epsilons],
            }

    def _mode_attack_specs(self, mode: str, config: dict[str, Any]) -> list[dict[str, Any]]:
        max_iter = max(5, int((config.get("configuration") or {}).get("max_iter") or 10))
        if mode == "whitebox":
            return [
                {
                    "attack_name": "LinfFastGradientAttack",
                    "attack_factory": lambda: __import__("foolbox").attacks.LinfFastGradientAttack(),
                    "epsilons": [0.01, 0.03, 0.05],
                    "rationale": "Gradient-based white-box Fast Gradient attack over the classification boundary.",
                },
                {
                    "attack_name": "LinfProjectedGradientDescentAttack",
                    "attack_factory": lambda: __import__("foolbox").attacks.LinfProjectedGradientDescentAttack(
                        steps=max_iter
                    ),
                    "epsilons": [0.02, 0.04, 0.08],
                    "rationale": "Iterative white-box PGD attack over the classification boundary.",
                },
            ]
        return [
            {
                "attack_name": "SaltAndPepperNoiseAttack",
                "attack_factory": lambda: __import__("foolbox").attacks.SaltAndPepperNoiseAttack(),
                "epsilons": [0.02, 0.08, 0.16],
                "rationale": "Decision-based black-box salt-and-pepper noise search.",
            },
            {
                "attack_name": "L2AdditiveGaussianNoiseAttack",
                "attack_factory": lambda: __import__("foolbox").attacks.L2AdditiveGaussianNoiseAttack(),
                "epsilons": [0.25, 0.5, 1.0],
                "rationale": "Black-box Gaussian noise attack over the model prediction boundary.",
            },
        ]

    def _html_report(self, *, title: str, payload: dict[str, Any]) -> str:
        clean = payload.get("clean_prediction") or {}
        attacks = payload.get("attack_results") or []
        rows = []
        for attack in attacks:
            rows.append(
                "<tr>"
                f"<td>{html.escape(str(attack.get('attack_name', '')))}</td>"
                f"<td>{html.escape(str(attack.get('attack_type', '-')))}</td>"
                f"<td>{html.escape(str(attack.get('status', '')))}</td>"
                f"<td>{html.escape(str(attack.get('success', False)))}</td>"
                f"<td>{html.escape(str(attack.get('selected_epsilon', '-')))}</td>"
                f"<td>{html.escape(str(attack.get('adversarial_label_name', '-')))}</td>"
                f"<td>{html.escape(str(attack.get('perturbation_linf', '-')))}</td>"
                f"<td>{html.escape(str(attack.get('perturbation_l2', '-')))}</td>"
                "</tr>"
            )
        if not rows:
            rows.append("<tr><td colspan='8'>No attacks executed.</td></tr>")

        return "\n".join(
            [
                "<html><body style='font-family: Avenir Next, Segoe UI, sans-serif; padding: 18px;'>",
                f"<h1>{html.escape(title)}</h1>",
                f"<p><strong>Job:</strong> {html.escape(str(payload.get('job_name', '')))}</p>",
                f"<p><strong>Wrapper:</strong> {html.escape(str(payload.get('wrapper_id', '')))}</p>",
                f"<p><strong>Model:</strong> {html.escape(str((payload.get('model') or {}).get('model_id', '')))}</p>",
                f"<p><strong>Sample:</strong> {html.escape(str((payload.get('configuration') or {}).get('sample_path', '')))}</p>",
                "<h2>Clean Prediction</h2>",
                "<table border='1' cellspacing='0' cellpadding='8'>",
                "<tr><th>Label ID</th><th>Label</th><th>Confidence</th></tr>",
                (
                    "<tr>"
                    f"<td>{html.escape(str(clean.get('label_id', '-')))}</td>"
                    f"<td>{html.escape(str(clean.get('label_name', '-')))}</td>"
                    f"<td>{html.escape(str(clean.get('confidence', '-')))}</td>"
                    "</tr>"
                ),
                "</table>",
                "<h2>Attack Results</h2>",
                "<table border='1' cellspacing='0' cellpadding='8'>",
                "<tr><th>Attack</th><th>Type</th><th>Status</th><th>Success</th><th>Epsilon</th><th>Adv Label</th><th>Linf</th><th>L2</th></tr>",
                *rows,
                "</table>",
                "</body></html>",
                "",
            ]
        )

    def _write_mode_artifacts(self, *, mode: str, payload: dict[str, Any], config: dict[str, Any]) -> dict[str, str]:
        reports_root = self._reports_root(config)
        reports_dir = reports_root / "reports"
        results_json = reports_dir / f"{mode}_results.json"
        report_html = reports_dir / f"{mode}_report.html"
        run_log = reports_dir / f"{mode}_run_log.txt"

        results_json.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        report_html.write_text(
            self._html_report(title=f"Foolbox {mode.title()} Scan Report", payload=payload),
            encoding="utf-8",
        )
        run_log.write_text(
            "\n".join(
                [
                    f"job_id={config.get('job_id', '')}",
                    f"mode={mode}",
                    f"framework=foolbox",
                    f"model_id={(config.get('model') or {}).get('model_id', '')}",
                    f"sample_path={(config.get('configuration') or {}).get('sample_path', '')}",
                    f"status={payload.get('status', '')}",
                    "",
                    json.dumps(payload, indent=2),
                    "",
                ]
            ),
            encoding="utf-8",
        )

        return {
            f"{mode}_results_json": str(results_json.resolve()),
            f"{mode}_report_html": str(report_html.resolve()),
            f"{mode}_run_log": str(run_log.resolve()),
        }

    def _run_mode(self, mode: str, config: dict[str, Any]) -> dict[str, Any]:
        job_id = str(config.get("job_id", "adhoc"))
        cache_key = (job_id, mode)
        cached = self._mode_cache.get(cache_key)
        if cached is not None:
            return cached

        runtime = self._load_runtime(config)
        clean_logits = runtime["clean_logits"].detach().cpu()
        clean_probs = clean_logits.softmax(dim=1)
        clean_confidence = float(clean_probs[0, runtime["clean_label_id"]].item())

        attack_results = [
            self._run_attack(
                runtime=runtime,
                config=config,
                scope=mode,
                attack_name=spec["attack_name"],
                attack_factory=spec["attack_factory"],
                epsilons=spec["epsilons"],
                rationale=spec["rationale"],
            )
            for spec in self._mode_attack_specs(mode, config)
        ]
        successful = [row for row in attack_results if row.get("success")]

        payload = {
            "status": "completed" if all(row.get("status") != "failed" for row in attack_results) else "partial_failure",
            "mode": mode,
            "kind": "real_model_backed",
            "framework": "foolbox",
            "adapter": self.capabilities().wrapper_id,
            "job_id": config.get("job_id"),
            "job_name": config.get("job_name"),
            "wrapper_id": self.capabilities().wrapper_id,
            "model": config.get("model"),
            "configuration": config.get("configuration"),
            "clean_prediction": {
                "label_id": runtime["clean_label_id"],
                "label_name": runtime["clean_label_name"],
                "confidence": clean_confidence,
            },
            "attack_results": attack_results,
            "attack_count": len(attack_results),
            "successful_attack_count": len(successful),
        }
        payload["artifacts"] = self._write_mode_artifacts(mode=mode, payload=payload, config=config)
        self._mode_cache[cache_key] = payload
        return payload

    def run_blackbox_scan(self, config: dict[str, Any]) -> dict[str, Any]:
        return self._run_mode("blackbox", config)

    def run_whitebox_scan(self, config: dict[str, Any]) -> dict[str, Any]:
        return self._run_mode("whitebox", config)

    def run_framework_scan(self, framework: str, config: dict[str, Any]) -> dict[str, Any]:
        if framework != "foolbox":
            raise NotImplementedError(f"HFVisionClassificationFoolboxAdapter does not implement framework '{framework}'.")

        job_id = str(config.get("job_id", "adhoc"))
        cached = self._framework_cache.get(job_id)
        if cached is not None:
            return cached

        selected_modes = set((config.get("configuration") or {}).get("scan_modes") or [])
        blackbox = self._run_mode("blackbox", config) if "blackbox" in selected_modes else None
        whitebox = self._run_mode("whitebox", config) if "whitebox" in selected_modes else None

        reports_root = self._reports_root(config)
        reports_dir = reports_root / "reports"
        payload = {
            "status": "completed",
            "framework": "foolbox",
            "kind": "real_model_backed",
            "adapter": self.capabilities().wrapper_id,
            "job_id": config.get("job_id"),
            "job_name": config.get("job_name"),
            "wrapper_id": self.capabilities().wrapper_id,
            "model": config.get("model"),
            "configuration": config.get("configuration"),
            "selected_modes": sorted(selected_modes),
            "blackbox": blackbox,
            "whitebox": whitebox,
            "clean_prediction": (whitebox or blackbox or {}).get("clean_prediction") or {},
            "attack_results": (blackbox or {}).get("attack_results", []) + (whitebox or {}).get("attack_results", []),
        }

        results_json = reports_dir / "results.json"
        report_html = reports_dir / "report.html"
        run_log = reports_dir / "run_log.txt"
        results_json.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        report_html.write_text(
            self._html_report(title="Foolbox Framework Report", payload=payload),
            encoding="utf-8",
        )
        run_log.write_text(
            "\n".join(
                [
                    f"job_id={config.get('job_id', '')}",
                    "framework=foolbox",
                    f"selected_modes={','.join(sorted(selected_modes))}",
                    f"model_id={(config.get('model') or {}).get('model_id', '')}",
                    "",
                    json.dumps(payload, indent=2),
                    "",
                ]
            ),
            encoding="utf-8",
        )
        payload["artifacts"] = {
            "results_json": str(results_json.resolve()),
            "report_html": str(report_html.resolve()),
            "run_log": str(run_log.resolve()),
        }
        self._framework_cache[job_id] = payload
        return payload
