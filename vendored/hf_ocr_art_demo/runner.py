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
import torch.nn.functional as F
from PIL import Image
from art.attacks.evasion.fast_gradient import FastGradientMethod
from art.attacks.evasion.projected_gradient_descent.projected_gradient_descent import ProjectedGradientDescent
from art.estimators.estimator import BaseEstimator, LossGradientsMixin
from transformers import AutoImageProcessor, AutoTokenizer, VisionEncoderDecoderModel


DEFAULT_MODEL_ID = "microsoft/trocr-small-printed"
DEFAULT_TARGET_TEXT = "ATTACK TEST"


@dataclass
class OCRProcessorBundle:
    image_processor: Any
    tokenizer: Any

    def batch_decode(self, *args, **kwargs) -> list[str]:
        return self.tokenizer.batch_decode(*args, **kwargs)


def now_utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def normalized_text(value: str) -> str:
    return " ".join(value.strip().upper().split())


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


def serializable_attack_value(value: Any) -> Any:
    if isinstance(value, (np.floating, float)):
        if np.isinf(value):
            return "inf" if float(value) > 0 else "-inf"
        return float(value)
    if isinstance(value, (np.integer, int)):
        return int(value)
    return value


def normalize_image_size(size: Any) -> tuple[int, int]:
    if isinstance(size, dict):
        if "height" in size and "width" in size:
            return int(size["height"]), int(size["width"])
        if "shortest_edge" in size:
            edge = int(size["shortest_edge"])
            return edge, edge
    if isinstance(size, (int, float)):
        edge = int(size)
        return edge, edge
    raise ValueError(f"Unsupported image processor size metadata: {size!r}")


def load_processor_bundle(model_id: str) -> OCRProcessorBundle:
    return OCRProcessorBundle(
        image_processor=AutoImageProcessor.from_pretrained(model_id, local_files_only=True),
        tokenizer=AutoTokenizer.from_pretrained(model_id, use_fast=False, local_files_only=True),
    )


def load_image_array(image_path: Path) -> np.ndarray:
    with Image.open(image_path) as image_fp:
        image = image_fp.convert("RGB")
    array = np.asarray(image).astype(np.float32) / 255.0
    return array[None, ...]


def save_image_array(path: Path, image_array: np.ndarray) -> None:
    clipped = np.clip(image_array, 0.0, 1.0)
    image = Image.fromarray((clipped * 255.0).round().astype(np.uint8))
    image.save(path)


@dataclass
class OCRRuntime:
    processor: OCRProcessorBundle
    model: VisionEncoderDecoderModel
    device: torch.device
    image_size: tuple[int, int]
    mean: torch.Tensor
    std: torch.Tensor
    pad_token_id: int
    eos_token_id: int
    bos_token_id: int
    max_target_length: int

    @classmethod
    def load(cls, model_id: str, device: str = "cpu") -> "OCRRuntime":
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
        processor = load_processor_bundle(model_id)
        model = VisionEncoderDecoderModel.from_pretrained(model_id, local_files_only=True)
        torch_device = torch.device(device)
        model.to(torch_device)
        model.eval()

        image_processor = processor.image_processor
        height, width = normalize_image_size(getattr(image_processor, "size", None))
        mean = torch.tensor(image_processor.image_mean, dtype=torch.float32, device=torch_device).view(1, 3, 1, 1)
        std = torch.tensor(image_processor.image_std, dtype=torch.float32, device=torch_device).view(1, 3, 1, 1)
        pad_token_id = int(processor.tokenizer.pad_token_id)
        eos_token_id = int(processor.tokenizer.eos_token_id)
        bos_token_id = int(processor.tokenizer.bos_token_id)

        model.config.pad_token_id = pad_token_id
        if model.config.decoder_start_token_id is None:
            model.config.decoder_start_token_id = bos_token_id
        if model.generation_config.pad_token_id is None:
            model.generation_config.pad_token_id = pad_token_id
        if model.generation_config.decoder_start_token_id is None:
            model.generation_config.decoder_start_token_id = bos_token_id

        return cls(
            processor=processor,
            model=model,
            device=torch_device,
            image_size=(height, width),
            mean=mean,
            std=std,
            pad_token_id=pad_token_id,
            eos_token_id=eos_token_id,
            bos_token_id=bos_token_id,
            max_target_length=int(getattr(model.generation_config, "max_length", 20) or 20),
        )

    def preprocess(self, x: torch.Tensor) -> torch.Tensor:
        if x.ndim != 4:
            raise ValueError(f"Expected NHWC batch input, got shape {tuple(x.shape)}.")
        x = x.permute(0, 3, 1, 2)
        x = F.interpolate(x, size=self.image_size, mode="bilinear", align_corners=False)
        return (x - self.mean) / self.std

    def encode_target_text(self, target_text: str, batch_size: int) -> np.ndarray:
        encoded = self.processor.tokenizer(
            target_text,
            padding="max_length",
            truncation=True,
            max_length=self.max_target_length,
            return_tensors="np",
        )
        target_ids = encoded["input_ids"].astype(np.int64)
        if batch_size == 1:
            return target_ids
        return np.repeat(target_ids, batch_size, axis=0)

    def decode_texts(self, x: np.ndarray) -> list[str]:
        x_tensor = torch.tensor(x, dtype=torch.float32, device=self.device)
        pixel_values = self.preprocess(x_tensor)
        with torch.inference_mode():
            generated = self.model.generate(pixel_values, max_length=self.max_target_length)
        return self.processor.batch_decode(generated, skip_special_tokens=True)

    def predict_token_ids(self, x: np.ndarray) -> np.ndarray:
        texts = self.decode_texts(x)
        encoded = self.processor.tokenizer(
            texts,
            padding="max_length",
            truncation=True,
            max_length=self.max_target_length,
            return_tensors="np",
        )
        return encoded["input_ids"].astype(np.int64)


class OCRArtEstimator(BaseEstimator, LossGradientsMixin):
    """ART estimator exposing target-text loss gradients for OCR vision-encoder-decoder models."""

    def __init__(self, runtime: OCRRuntime):
        super().__init__(
            model=runtime.model,
            clip_values=(0.0, 1.0),
            preprocessing_defences=None,
            postprocessing_defences=None,
            preprocessing=None,
        )
        self.runtime = runtime
        self._input_shape = (None, None, 3)

    @property
    def input_shape(self) -> tuple[int | None, int | None, int]:
        return self._input_shape

    def predict(self, x: np.ndarray, batch_size: int = 1, **kwargs) -> np.ndarray:
        _ = batch_size, kwargs
        return self.runtime.predict_token_ids(x)

    def fit(self, x, y, **kwargs) -> None:  # pragma: no cover - estimator is inference only
        _ = x, y, kwargs
        raise NotImplementedError("OCRArtEstimator does not support fitting.")

    def loss_gradient(self, x, y, **kwargs) -> np.ndarray:
        _ = kwargs
        x_tensor = torch.tensor(x, dtype=torch.float32, device=self.runtime.device, requires_grad=True)
        pixel_values = self.runtime.preprocess(x_tensor)

        target_ids = torch.tensor(y, dtype=torch.long, device=self.runtime.device)
        decoder_input_ids = target_ids[:, :-1]
        target_labels = target_ids[:, 1:].clone()
        target_labels[target_labels == self.runtime.pad_token_id] = -100

        outputs = self.runtime.model(
            pixel_values=pixel_values,
            decoder_input_ids=decoder_input_ids,
            use_cache=False,
            return_dict=True,
        )
        logits = outputs.logits
        loss = F.cross_entropy(
            logits.reshape(-1, logits.shape[-1]),
            target_labels.reshape(-1),
            ignore_index=-100,
        )
        loss.backward()
        gradients = x_tensor.grad.detach().cpu().numpy().astype(np.float32)
        return gradients


def attack_specs(max_iter: int) -> list[dict[str, Any]]:
    return [
        {
            "attack_name": "FastGradientMethod",
            "kind": "fgm",
            "params": {
                "norm": np.inf,
                "eps": 0.08,
                "eps_step": 0.08,
                "targeted": True,
                "num_random_init": 0,
                "batch_size": 1,
            },
            "reason": "Generic IBM ART loss-gradient image attack against the OCR target text objective.",
        },
        {
            "attack_name": "ProjectedGradientDescent",
            "kind": "pgd",
            "params": {
                "norm": np.inf,
                "eps": 0.12,
                "eps_step": 0.02,
                "max_iter": max(1, int(max_iter)),
                "targeted": True,
                "num_random_init": 0,
                "batch_size": 1,
                "verbose": False,
            },
            "reason": "Iterative IBM ART PGD over the OCR target text objective.",
        },
    ]


def create_attack(estimator: OCRArtEstimator, spec: dict[str, Any]):
    params = dict(spec["params"])
    if spec["kind"] == "fgm":
        return FastGradientMethod(estimator=estimator, **params)
    if spec["kind"] == "pgd":
        return ProjectedGradientDescent(estimator=estimator, **params)
    raise ValueError(f"Unsupported attack kind: {spec['kind']}")


def build_html_report(report: dict[str, Any], output_path: Path) -> None:
    attacks = report.get("per_attack_results", [])
    rows = "\n".join(
        [
            "<tr>"
            f"<td>{html.escape(str(item.get('attack_name', '')))}</td>"
            f"<td>{html.escape(str(item.get('status', '')))}</td>"
            f"<td>{html.escape(str(item.get('clean_transcript', '')))}</td>"
            f"<td>{html.escape(str(item.get('adversarial_transcript', '')))}</td>"
            f"<td>{html.escape(str(item.get('target_matched', '')))}</td>"
            f"<td>{html.escape(str(item.get('perturbation_linf', '')))}</td>"
            "</tr>"
            for item in attacks
        ]
    )
    html_text = "\n".join(
        [
            "<html><body>",
            "<h1>IBM ART OCR White-Box Report</h1>",
            "<p>This report was generated from a real ART-backed OCR run against a Hugging Face vision-encoder-decoder model.</p>",
            f"<p><strong>Model:</strong> {html.escape(str(report.get('model', {}).get('model_id', '')))}</p>",
            f"<p><strong>Sample:</strong> {html.escape(str(report.get('input', {}).get('image_path', '')))}</p>",
            f"<p><strong>Target text:</strong> {html.escape(str(report.get('input', {}).get('target_text', '')))}</p>",
            f"<p><strong>Clean transcript:</strong> {html.escape(str(report.get('clean_result', {}).get('transcript', '')))}</p>",
            "<table border='1' cellspacing='0' cellpadding='6'>",
            "<thead><tr><th>Attack</th><th>Status</th><th>Clean</th><th>Adversarial</th><th>Target matched</th><th>Linf</th></tr></thead>",
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
            "<h1>OCR Black-Box Baseline</h1>",
            "<p>This report contains the clean OCR baseline captured before the IBM ART white-box attacks ran.</p>",
            f"<p><strong>Model:</strong> {html.escape(str(clean_report.get('model_id', '')))}</p>",
            f"<p><strong>Sample:</strong> {html.escape(str(clean_report.get('sample_path', '')))}</p>",
            f"<p><strong>Extracted text:</strong> {html.escape(str(clean_report.get('clean_transcript', '')))}</p>",
            "</body></html>",
            "",
        ]
    )
    output_path.write_text(html_text, encoding="utf-8")


def run_baseline(runtime: OCRRuntime, image_array: np.ndarray) -> dict[str, Any]:
    transcript = runtime.decode_texts(image_array)[0].strip()
    return {"transcript": transcript}


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
        "clean_transcript": clean_result.get("transcript", ""),
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
                f"target_text={whitebox_report.get('input', {}).get('target_text', '')}",
                f"clean_transcript={clean_result['transcript']}",
                *[
                    f"{item['attack_name']}={item.get('status')} target_matched={item.get('target_matched')}"
                    for item in whitebox_report.get("per_attack_results", [])
                ],
                "",
            ]
        ),
        encoding="utf-8",
    )
    artifact_paths["whitebox_run_log"].write_text(
        artifact_paths["run_log"].read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    artifact_paths["blackbox_run_log"].write_text(
        "\n".join(
            [
                f"model_id={model_id}",
                f"image_path={image_file}",
                f"clean_transcript={clean_result['transcript']}",
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
    target_text: str = DEFAULT_TARGET_TEXT,
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

    clean_x = load_image_array(image_file)
    runtime = OCRRuntime.load(model_id=model_id, device="cpu")
    estimator = OCRArtEstimator(runtime)

    started_at = now_utc()
    clean_result = run_baseline(runtime, clean_x)
    target_ids = runtime.encode_target_text(target_text, batch_size=clean_x.shape[0])

    per_attack_results: list[dict[str, Any]] = []
    inventory: list[dict[str, Any]] = []

    save_image_array(reports_dir / "clean_input.png", clean_x[0])

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
            attack = create_attack(estimator, spec)
            adv_x = attack.generate(x=clean_x.copy(), y=target_ids.copy())
            adv_text = runtime.decode_texts(adv_x)[0].strip()
            runtime_sec = time.perf_counter() - attack_started
            perturbation = adv_x - clean_x
            save_image_array(reports_dir / f"{spec['attack_name']}_adv.png", adv_x[0])
            per_attack_results.append(
                {
                    "attack_name": spec["attack_name"],
                    "status": "RUN",
                    "runtime_sec": runtime_sec,
                    "attack_parameters": {
                        key: serializable_attack_value(value)
                        for key, value in spec["params"].items()
                    },
                    "clean_transcript": clean_result["transcript"],
                    "adversarial_transcript": adv_text,
                    "transcript_changed": normalized_text(adv_text) != normalized_text(clean_result["transcript"]),
                    "target_matched": normalized_text(adv_text) == normalized_text(target_text),
                    "perturbation_linf": float(np.max(np.abs(perturbation))),
                    "perturbation_l2": float(np.linalg.norm(perturbation.reshape(perturbation.shape[0], -1), axis=1)[0]),
                    "artifacts": {
                        "adversarial_image": str((reports_dir / f"{spec['attack_name']}_adv.png").resolve()),
                    },
                }
            )
        except Exception as exc:  # pragma: no cover - defensive reporting
            per_attack_results.append(
                {
                    "attack_name": spec["attack_name"],
                    "status": "FAILED",
                    "error": repr(exc),
                }
            )

    finished_at = now_utc()
    report = {
        "timestamps": {
            "started_at_utc": started_at,
            "finished_at_utc": finished_at,
        },
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
            "task_boundary": "Hugging Face OCR with IBM ART image evasion attacks over a target-text loss objective.",
        },
        "input": {
            "image_path": str(image_file),
            "target_text": target_text,
        },
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
