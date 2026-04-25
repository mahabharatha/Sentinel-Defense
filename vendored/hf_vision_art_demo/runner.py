from __future__ import annotations

import html
import json
import os
import platform
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import torch
import torch.nn as nn
from art.attacks.evasion.fast_gradient import FastGradientMethod
from art.attacks.evasion.projected_gradient_descent.projected_gradient_descent import ProjectedGradientDescent
from art.estimators.classification import PyTorchClassifier
from PIL import Image
from transformers import AutoImageProcessor, AutoModelForImageClassification


DEFAULT_MODEL_ID = "microsoft/resnet-18"


def now_utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_pretrained_local_first(loader: Any, model_id: str, **kwargs: Any) -> Any:
    try:
        return loader.from_pretrained(model_id, local_files_only=True, **kwargs)
    except Exception as exc:
        if os.environ.get("RHEL_ART_ALLOW_ONLINE_FETCH", "").strip() == "1":
            return loader.from_pretrained(model_id, **kwargs)
        raise RuntimeError(
            f"Required Hugging Face files for '{model_id}' are not fully available in the local cache. "
            "Pre-download the model or set RHEL_ART_ALLOW_ONLINE_FETCH=1 to permit network fetches."
        ) from exc


def serializable_attack_value(value: Any) -> Any:
    if isinstance(value, (np.floating, float)):
        if np.isinf(value):
            return "inf" if float(value) > 0 else "-inf"
        return float(value)
    if isinstance(value, (np.integer, int)):
        return int(value)
    return value


def ensure_output_dirs(output_dir: Path) -> Path:
    reports_dir = output_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    return reports_dir


def report_artifact_paths(reports_dir: Path) -> dict[str, Path]:
    return {
        "results_json": reports_dir / "results.json",
        "report_html": reports_dir / "report.html",
        "run_log": reports_dir / "run_log.txt",
        "blackbox_results_json": reports_dir / "blackbox_results.json",
        "blackbox_report_html": reports_dir / "blackbox_report.html",
        "blackbox_run_log": reports_dir / "blackbox_run_log.txt",
        "whitebox_results_json": reports_dir / "whitebox_results.json",
        "whitebox_report_html": reports_dir / "whitebox_report.html",
        "whitebox_run_log": reports_dir / "whitebox_run_log.txt",
    }


@dataclass
class VisionRuntime:
    processor: Any
    model: Any
    device: torch.device
    image_size: tuple[int, int]
    mean: torch.Tensor
    std: torch.Tensor
    nb_classes: int

    @classmethod
    def load(cls, model_id: str, device: str = "cpu") -> "VisionRuntime":
        processor = load_pretrained_local_first(AutoImageProcessor, model_id)
        model = load_pretrained_local_first(AutoModelForImageClassification, model_id)
        torch_device = torch.device(device)
        model.to(torch_device)
        model.eval()

        size = getattr(processor, "size", None)
        if isinstance(size, dict):
            height = int(size.get("height") or size.get("shortest_edge") or size.get("size") or 224)
            width = int(size.get("width") or size.get("shortest_edge") or size.get("size") or 224)
        elif isinstance(size, int):
            height = width = int(size)
        else:
            height = width = 224

        mean = torch.tensor(getattr(processor, "image_mean", [0.5, 0.5, 0.5]), dtype=torch.float32, device=torch_device).view(1, 3, 1, 1)
        std = torch.tensor(getattr(processor, "image_std", [0.5, 0.5, 0.5]), dtype=torch.float32, device=torch_device).view(1, 3, 1, 1)
        nb_classes = int(getattr(model.config, "num_labels", 1000) or 1000)
        return cls(
            processor=processor,
            model=model,
            device=torch_device,
            image_size=(height, width),
            mean=mean,
            std=std,
            nb_classes=nb_classes,
        )

    def preprocess(self, x: torch.Tensor) -> torch.Tensor:
        return (x - self.mean) / self.std

    def id_to_label(self, label_id: int) -> str:
        id2label = getattr(self.model.config, "id2label", {}) or {}
        if label_id in id2label:
            return str(id2label[label_id])
        if str(label_id) in id2label:
            return str(id2label[str(label_id)])
        return f"class_{label_id}"


class VisionBoundary(nn.Module):
    def __init__(self, runtime: VisionRuntime) -> None:
        super().__init__()
        self.runtime = runtime
        self.model = runtime.model

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        normalized = self.runtime.preprocess(x)
        return self.model(pixel_values=normalized).logits


def load_image_tensor(image_path: Path, image_size: tuple[int, int]) -> np.ndarray:
    with Image.open(image_path) as image_fp:
        image = image_fp.convert("RGB")
    image = image.resize((image_size[1], image_size[0]))
    array = np.asarray(image).astype(np.float32) / 255.0
    return np.transpose(array, (2, 0, 1))[None, ...]


def save_image_tensor(path: Path, image_tensor: np.ndarray) -> None:
    clipped = np.clip(image_tensor, 0.0, 1.0)
    array = np.transpose(clipped, (1, 2, 0))
    image = Image.fromarray((array * 255.0).round().astype(np.uint8))
    image.save(path)


def run_baseline(runtime: VisionRuntime, classifier: PyTorchClassifier, clean_x: np.ndarray) -> dict[str, Any]:
    logits = classifier.predict(clean_x)
    probabilities = torch.softmax(torch.tensor(logits[0]), dim=0).numpy()
    label_id = int(np.argmax(probabilities))
    return {
        "label_id": label_id,
        "label_name": runtime.id_to_label(label_id),
        "confidence": float(probabilities[label_id]),
    }


def attack_specs(max_iter: int) -> list[dict[str, Any]]:
    return [
        {
            "attack_name": "FastGradientMethod",
            "kind": "fgm",
            "params": {
                "eps": 0.02,
                "eps_step": 0.02,
                "targeted": False,
                "batch_size": 1,
                "num_random_init": 0,
            },
            "reason": "Generic IBM ART gradient image attack for vision classification.",
        },
        {
            "attack_name": "ProjectedGradientDescent",
            "kind": "pgd",
            "params": {
                "eps": 0.04,
                "eps_step": 0.01,
                "max_iter": max(1, int(max_iter)),
                "targeted": False,
                "batch_size": 1,
                "num_random_init": 0,
                "verbose": False,
            },
            "reason": "Iterative IBM ART PGD attack for vision classification.",
        },
    ]


def create_attack(classifier: PyTorchClassifier, spec: dict[str, Any]) -> Any:
    params = dict(spec["params"])
    if spec["kind"] == "fgm":
        return FastGradientMethod(estimator=classifier, **params)
    if spec["kind"] == "pgd":
        return ProjectedGradientDescent(estimator=classifier, **params)
    raise ValueError(f"Unsupported attack kind: {spec['kind']}")


def build_html_report(report: dict[str, Any], output_path: Path) -> None:
    attacks = report.get("per_attack_results", [])
    rows = "\n".join(
        [
            "<tr>"
            f"<td>{html.escape(str(item.get('attack_name', '')))}</td>"
            f"<td>{html.escape(str(item.get('status', '')))}</td>"
            f"<td>{html.escape(str(item.get('clean_label_name', '')))}</td>"
            f"<td>{html.escape(str(item.get('adversarial_label_name', '')))}</td>"
            f"<td>{html.escape(str(item.get('prediction_changed', '')))}</td>"
            f"<td>{html.escape(str(item.get('perturbation_linf', '')))}</td>"
            "</tr>"
            for item in attacks
        ]
    )
    html_text = "\n".join(
        [
            "<html><body>",
            "<h1>IBM ART Vision Classification Report</h1>",
            "<p>This report was generated from a real IBM ART image-classification run.</p>",
            f"<p><strong>Model:</strong> {html.escape(str(report.get('model', {}).get('model_id', '')))}</p>",
            f"<p><strong>Sample:</strong> {html.escape(str(report.get('input', {}).get('image_path', '')))}</p>",
            f"<p><strong>Clean label:</strong> {html.escape(str(report.get('clean_result', {}).get('label_name', '')))}</p>",
            "<table border='1' cellspacing='0' cellpadding='6'>",
            "<thead><tr><th>Attack</th><th>Status</th><th>Clean</th><th>Adversarial</th><th>Prediction changed</th><th>Linf</th></tr></thead>",
            f"<tbody>{rows}</tbody>",
            "</table>",
            "</body></html>",
            "",
        ]
    )
    output_path.write_text(html_text, encoding="utf-8")


def build_blackbox_report(clean_report: dict[str, Any], output_path: Path) -> None:
    html_text = "\n".join(
        [
            "<html><body>",
            "<h1>HF Vision Classification Baseline</h1>",
            "<p>This report contains the clean baseline captured before the IBM ART attacks ran.</p>",
            f"<p><strong>Model:</strong> {html.escape(str(clean_report.get('model_id', '')))}</p>",
            f"<p><strong>Sample:</strong> {html.escape(str(clean_report.get('sample_path', '')))}</p>",
            f"<p><strong>Predicted label:</strong> {html.escape(str(clean_report.get('clean_label_name', '')))}</p>",
            f"<p><strong>Confidence:</strong> {html.escape(str(clean_report.get('clean_confidence', '')))}</p>",
            "</body></html>",
            "",
        ]
    )
    output_path.write_text(html_text, encoding="utf-8")


def load_cached_report(output_dir: Path) -> dict[str, Any] | None:
    results_json = output_dir / "reports" / "results.json"
    if results_json.exists():
        return read_json(results_json)
    return None


def write_split_reports(
    *,
    reports_dir: Path,
    model_id: str,
    image_file: Path,
    clean_result: dict[str, Any],
    whitebox_report: dict[str, Any],
) -> None:
    artifact_paths = report_artifact_paths(reports_dir)
    blackbox_report = {
        "status": "completed",
        "mode": "blackbox",
        "model_id": model_id,
        "sample_path": str(image_file),
        "clean_label_id": clean_result.get("label_id"),
        "clean_label_name": clean_result.get("label_name", ""),
        "clean_confidence": clean_result.get("confidence"),
    }

    write_json(artifact_paths["results_json"], whitebox_report)
    write_json(artifact_paths["whitebox_results_json"], whitebox_report)
    write_json(artifact_paths["blackbox_results_json"], blackbox_report)

    build_html_report(whitebox_report, artifact_paths["report_html"])
    build_html_report(whitebox_report, artifact_paths["whitebox_report_html"])
    build_blackbox_report(blackbox_report, artifact_paths["blackbox_report_html"])

    artifact_paths["run_log"].write_text(
        "\n".join(
            [
                f"model_id={model_id}",
                f"image_path={image_file}",
                f"clean_label={clean_result.get('label_name', '')}",
                *[
                    f"{item['attack_name']}={item.get('status')} prediction_changed={item.get('prediction_changed')}"
                    for item in whitebox_report.get("per_attack_results", [])
                ],
                "",
            ]
        ),
        encoding="utf-8",
    )
    artifact_paths["whitebox_run_log"].write_text(artifact_paths["run_log"].read_text(encoding="utf-8"), encoding="utf-8")
    artifact_paths["blackbox_run_log"].write_text(
        "\n".join(
            [
                f"model_id={model_id}",
                f"image_path={image_file}",
                f"clean_label={clean_result.get('label_name', '')}",
                "",
            ]
        ),
        encoding="utf-8",
    )


def run_scan(
    *,
    image_path: str,
    output_dir: str,
    model_id: str = DEFAULT_MODEL_ID,
    max_iter: int = 5,
    force: bool = False,
) -> dict[str, Any]:
    output_path = Path(output_dir)
    reports_dir = ensure_output_dirs(output_path)
    image_file = Path(image_path).expanduser().resolve()
    cached = None if force else load_cached_report(output_path)
    if cached is not None:
        clean_result = cached.get("clean_result", {})
        write_split_reports(
            reports_dir=reports_dir,
            model_id=model_id,
            image_file=image_file,
            clean_result=clean_result,
            whitebox_report=cached,
        )
        return cached

    runtime = VisionRuntime.load(model_id=model_id, device="cpu")
    clean_x = load_image_tensor(image_file, runtime.image_size)
    model_boundary = VisionBoundary(runtime)
    optimizer = torch.optim.Adam(runtime.model.parameters(), lr=1e-4)
    classifier = PyTorchClassifier(
        model=model_boundary,
        loss=nn.CrossEntropyLoss(),
        optimizer=optimizer,
        input_shape=(3, runtime.image_size[0], runtime.image_size[1]),
        nb_classes=runtime.nb_classes,
        clip_values=(0.0, 1.0),
    )

    started_at = now_utc()
    clean_result = run_baseline(runtime, classifier, clean_x)
    clean_y = np.array([clean_result["label_id"]], dtype=np.int64)
    save_image_tensor(reports_dir / "clean_input.png", clean_x[0])

    per_attack_results: list[dict[str, Any]] = []
    inventory: list[dict[str, Any]] = []
    for spec in attack_specs(max_iter=max_iter):
        inventory.append(
            {
                "attack_name": spec["attack_name"],
                "decision": "RUN",
                "reason": spec["reason"],
            }
        )
        attack_started = time.perf_counter()
        try:
            attack = create_attack(classifier, spec)
            adv_x = attack.generate(x=clean_x.copy(), y=clean_y.copy())
            adv_logits = classifier.predict(adv_x)
            adv_probs = torch.softmax(torch.tensor(adv_logits[0]), dim=0).numpy()
            adv_label_id = int(np.argmax(adv_probs))
            runtime_sec = time.perf_counter() - attack_started
            perturbation = adv_x - clean_x
            save_image_tensor(reports_dir / f"{spec['attack_name']}_adv.png", adv_x[0])
            per_attack_results.append(
                {
                    "attack_name": spec["attack_name"],
                    "status": "RUN",
                    "runtime_sec": runtime_sec,
                    "attack_parameters": {key: serializable_attack_value(value) for key, value in spec["params"].items()},
                    "clean_label_id": clean_result["label_id"],
                    "clean_label_name": clean_result["label_name"],
                    "clean_confidence": clean_result["confidence"],
                    "adversarial_label_id": adv_label_id,
                    "adversarial_label_name": runtime.id_to_label(adv_label_id),
                    "adversarial_confidence": float(adv_probs[adv_label_id]),
                    "prediction_changed": adv_label_id != clean_result["label_id"],
                    "perturbation_linf": float(np.max(np.abs(perturbation))),
                    "perturbation_l2": float(np.linalg.norm(perturbation.reshape(perturbation.shape[0], -1), axis=1)[0]),
                    "artifacts": {
                        "adversarial_image": str((reports_dir / f"{spec['attack_name']}_adv.png").resolve()),
                    },
                }
            )
        except Exception as exc:
            per_attack_results.append(
                {
                    "attack_name": spec["attack_name"],
                    "status": "FAILED",
                    "error": repr(exc),
                }
            )

    finished_at = now_utc()
    report = {
        "timestamps": {"started_at_utc": started_at, "finished_at_utc": finished_at},
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "machine": platform.machine(),
            "torch": torch.__version__,
            "cuda_available": torch.cuda.is_available(),
            "cuda_device_count": torch.cuda.device_count() if torch.cuda.is_available() else 0,
            "device_used": "cpu",
            "pid": os.getpid(),
        },
        "model": {
            "model_id": model_id,
            "task_boundary": "Hugging Face vision classification with IBM ART image evasion attacks.",
        },
        "input": {"image_path": str(image_file)},
        "clean_result": clean_result,
        "attack_inventory": inventory,
        "per_attack_results": per_attack_results,
    }

    write_split_reports(
        reports_dir=reports_dir,
        model_id=model_id,
        image_file=image_file,
        clean_result=clean_result,
        whitebox_report=report,
    )
    return report
