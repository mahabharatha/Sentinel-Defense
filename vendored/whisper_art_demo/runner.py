from __future__ import annotations

import argparse
import json
import logging
import math
import os
import platform
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf
import torch
from art.attacks.evasion import (
    BasicIterativeMethod,
    CarliniWagnerASR,
    FastGradientMethod,
    ImperceptibleASRPyTorch,
    MomentumIterativeMethod,
    ProjectedGradientDescent,
    ProjectedGradientDescentNumpy,
)
from art.attacks.evasion.imperceptible_asr.imperceptible_asr import ImperceptibleASR, PsychoacousticMasker
from art.estimators.pytorch import PyTorchEstimator
from art.estimators.speech_recognition.speech_recognizer import PytorchSpeechRecognizerMixin, SpeechRecognizerMixin
from scipy.signal import resample_poly
from transformers import AutoTokenizer, WhisperForConditionalGeneration, WhisperProcessor

from .build_html_report import build_html


DEFAULT_MODEL_ID = "openai/whisper-tiny.en"
DEFAULT_TARGET_TRANSCRIPT = "ATTACK TEST"
DEFAULT_SAMPLE_RATE = 16_000
DEFAULT_CLIP_SECONDS = 5.0


def now_utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def normalize_text(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def pick_device(requested: str) -> torch.device:
    if requested != "auto":
        return torch.device(requested)
    if torch.cuda.is_available():
        return torch.device("cuda")
    return torch.device("cpu")


def choose_dtype(device: torch.device) -> torch.dtype:
    if device.type == "cuda":
        return torch.float16
    return torch.float32


def whisper_generate_kwargs(model: WhisperForConditionalGeneration, max_new_tokens: int = 64) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"max_new_tokens": max_new_tokens}
    if bool(getattr(model.config, "is_multilingual", False)):
        kwargs["language"] = "english"
        kwargs["task"] = "transcribe"
    return kwargs


def configure_logging(log_path: Path) -> logging.Logger:
    logger = logging.getLogger("vendored_whisper_art_demo")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)
    return logger


@dataclass
class LoadedResources:
    model: WhisperForConditionalGeneration
    processor: Any
    tokenizer: Any
    device: torch.device
    dtype: torch.dtype
    model_id: str


def load_pretrained_local_first(loader: Any, model_id: str, **kwargs: Any) -> Any:
    try:
        original_hf_offline = os.environ.get("HF_HUB_OFFLINE")
        original_transformers_offline = os.environ.get("TRANSFORMERS_OFFLINE")
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        try:
            return loader.from_pretrained(model_id, local_files_only=True, **kwargs)
        finally:
            if original_hf_offline is None:
                os.environ.pop("HF_HUB_OFFLINE", None)
            else:
                os.environ["HF_HUB_OFFLINE"] = original_hf_offline
            if original_transformers_offline is None:
                os.environ.pop("TRANSFORMERS_OFFLINE", None)
            else:
                os.environ["TRANSFORMERS_OFFLINE"] = original_transformers_offline
    except Exception as exc:
        if os.environ.get("RHEL_ART_ALLOW_ONLINE_FETCH", "").strip() == "1":
            return loader.from_pretrained(model_id, **kwargs)
        raise RuntimeError(
            f"Required Hugging Face files for '{model_id}' are not fully available in the local cache. "
            "Pre-download the model or set RHEL_ART_ALLOW_ONLINE_FETCH=1 to permit network fetches."
        ) from exc


def load_resources(model_id: str, device_name: str) -> LoadedResources:
    device = pick_device(device_name)
    dtype = choose_dtype(device)
    processor = load_pretrained_local_first(WhisperProcessor, model_id)
    tokenizer = getattr(processor, "tokenizer", None) or load_pretrained_local_first(AutoTokenizer, model_id)
    model = load_pretrained_local_first(
        WhisperForConditionalGeneration,
        model_id,
        low_cpu_mem_usage=True,
        torch_dtype=dtype,
    )
    model.eval()
    model.to(device)
    return LoadedResources(
        model=model,
        processor=processor,
        tokenizer=tokenizer,
        device=device,
        dtype=dtype,
        model_id=model_id,
    )


def ensure_demo_audio(audio_path: Path, sample_rate: int) -> Path:
    if audio_path.exists():
        return audio_path

    seconds = 2.0
    timeline = np.linspace(0.0, seconds, int(sample_rate * seconds), endpoint=False, dtype=np.float32)
    waveform = 0.1 * np.sin(2.0 * math.pi * 220.0 * timeline)
    waveform[int(0.75 * sample_rate) : int(0.85 * sample_rate)] *= 0.2
    audio_path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(audio_path), waveform, sample_rate)
    return audio_path


def load_waveform(path: Path, target_sample_rate: int = DEFAULT_SAMPLE_RATE, pad_to_sec: float = DEFAULT_CLIP_SECONDS) -> tuple[np.ndarray, int]:
    audio, sample_rate = sf.read(str(path), dtype="float32", always_2d=False)
    audio = np.asarray(audio, dtype=np.float32)
    if audio.ndim > 1:
        audio = np.mean(audio, axis=1, dtype=np.float32)
    if sample_rate != target_sample_rate:
        source_rate = int(sample_rate)
        target_rate = int(target_sample_rate)
        divisor = math.gcd(source_rate, target_rate)
        up = target_rate // divisor
        down = source_rate // divisor
        audio = resample_poly(audio, up, down).astype(np.float32)
        sample_rate = target_sample_rate
    target_samples = int(target_sample_rate * pad_to_sec)
    if len(audio) < target_samples:
        audio = np.pad(audio, (0, target_samples - len(audio)))
    elif len(audio) > target_samples:
        audio = audio[:target_samples]
    peak = float(np.max(np.abs(audio))) if len(audio) else 0.0
    if peak > 0.0:
        audio = audio / peak
    return audio, target_sample_rate


def extract_log_mel_torch(resources: LoadedResources, waveforms: torch.Tensor) -> torch.Tensor:
    feature_extractor = resources.processor.feature_extractor
    if waveforms.ndim == 1:
        waveforms = waveforms.unsqueeze(0)
    waveforms = waveforms.to(resources.device, torch.float32)
    target_samples = int(feature_extractor.n_samples)
    current_samples = waveforms.shape[-1]
    if current_samples < target_samples:
        waveforms = torch.nn.functional.pad(waveforms, (0, target_samples - current_samples))
    elif current_samples > target_samples:
        waveforms = waveforms[..., :target_samples]
    window = torch.hann_window(feature_extractor.n_fft, device=resources.device)
    stft = torch.stft(
        waveforms,
        n_fft=feature_extractor.n_fft,
        hop_length=feature_extractor.hop_length,
        window=window,
        return_complex=True,
    )
    magnitudes = stft[..., :-1].abs() ** 2
    mel_filters = torch.from_numpy(feature_extractor.mel_filters).to(resources.device, torch.float32)
    mel_spec = torch.matmul(mel_filters.T.unsqueeze(0), magnitudes)
    log_spec = torch.clamp(mel_spec, min=1e-10).log10()
    max_val = log_spec.amax(dim=(1, 2), keepdim=True)
    log_spec = torch.maximum(log_spec, max_val - 8.0)
    log_spec = (log_spec + 4.0) / 4.0
    return log_spec.to(resources.dtype)


class WhisperTinyArtSpeechRecognizer(PytorchSpeechRecognizerMixin, SpeechRecognizerMixin, PyTorchEstimator):
    def __init__(self, resources: LoadedResources, sample_rate: int, input_length: int) -> None:
        self.resources = resources
        self._sample_rate = sample_rate
        self._input_shape = (input_length,)
        super().__init__(
            model=resources.model,
            clip_values=(-1.0, 1.0),
            channels_first=False,
            preprocessing_defences=None,
            postprocessing_defences=None,
            preprocessing=None,
            device_type="gpu" if resources.device.type == "cuda" else "cpu",
        )

    @property
    def input_shape(self) -> tuple[int, ...]:
        return self._input_shape

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    def fit(self, x, y, **kwargs) -> None:
        raise NotImplementedError("Training is not supported in this demo script.")

    def get_activations(self, x, layer, batch_size, framework=False):
        raise NotImplementedError("Activation export is not supported in this demo script.")

    def clone_for_refitting(self):
        raise NotImplementedError("Refitting is not supported in this demo script.")

    def set_batchnorm(self, train: bool) -> None:
        return None

    def to_training_mode(self) -> None:
        self._model.train()

    def _prepare_targets(self, y: np.ndarray) -> dict[str, torch.Tensor]:
        tokenized = self.resources.tokenizer(
            [str(item).lower() for item in y.tolist()],
            return_tensors="pt",
            padding=True,
        )
        labels = tokenized["input_ids"].to(self.resources.device)
        labels = labels.masked_fill(labels == self.resources.tokenizer.pad_token_id, -100)
        return {"labels": labels}

    def _waveforms_to_features(self, x: np.ndarray | torch.Tensor) -> torch.Tensor:
        if isinstance(x, np.ndarray):
            waveforms = torch.tensor(x, dtype=torch.float32, device=self.resources.device)
        else:
            waveforms = x.to(self.resources.device, torch.float32)
        return extract_log_mel_torch(self.resources, waveforms)

    @torch.inference_mode()
    def predict(self, x: np.ndarray, batch_size: int = 1, **kwargs) -> np.ndarray:
        transcripts: list[str] = []
        for start in range(0, len(x), batch_size):
            batch = x[start : start + batch_size]
            features = self._waveforms_to_features(batch)
            generated_ids = self._model.generate(
                input_features=features,
                **whisper_generate_kwargs(self._model, max_new_tokens=64),
            )
            decoded = self.resources.processor.batch_decode(generated_ids, skip_special_tokens=True)
            transcripts.extend(text.strip().upper() for text in decoded)
        return np.array(transcripts)

    def loss_gradient(self, x: np.ndarray, y: np.ndarray, **kwargs) -> np.ndarray:
        waveforms = torch.tensor(x, dtype=torch.float32, device=self.resources.device, requires_grad=True)
        features = extract_log_mel_torch(self.resources, waveforms)
        labels = self._prepare_targets(y)["labels"]
        outputs = self._model(input_features=features, labels=labels)
        loss = outputs.loss
        self._model.zero_grad(set_to_none=True)
        loss.backward()
        return waveforms.grad.detach().cpu().numpy()

    def compute_loss(self, x: np.ndarray, y: np.ndarray, **kwargs) -> np.ndarray:
        with torch.no_grad():
            features = self._waveforms_to_features(x)
            labels = self._prepare_targets(y)["labels"]
            outputs = self._model(input_features=features, labels=labels)
            return np.array([float(outputs.loss.detach().cpu().item())] * len(x), dtype=np.float32)

    def compute_loss_and_decoded_output(self, masked_adv_input: torch.Tensor, original_output: np.ndarray, **kwargs):
        features = extract_log_mel_torch(self.resources, masked_adv_input)
        labels = self._prepare_targets(original_output)["labels"]
        outputs = self._model(input_features=features, labels=labels)
        generated_ids = self._model.generate(
            input_features=features.detach(),
            **whisper_generate_kwargs(self._model, max_new_tokens=64),
        )
        decoded = self.resources.processor.batch_decode(generated_ids, skip_special_tokens=True)
        return outputs.loss, np.array([text.strip().upper() for text in decoded])


def build_attack_inventory(cuda_available: bool) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = [
        {"attack_name": "FastGradientMethod", "decision": "RUN", "reason": "Generic loss-gradient waveform attack supported."},
        {"attack_name": "BasicIterativeMethod", "decision": "RUN", "reason": "Generic iterative loss-gradient waveform attack supported."},
        {"attack_name": "ProjectedGradientDescent", "decision": "RUN", "reason": "Generic PGD waveform attack supported."},
        {"attack_name": "ProjectedGradientDescentNumpy", "decision": "RUN", "reason": "Generic numpy PGD waveform attack supported."},
        {"attack_name": "MomentumIterativeMethod", "decision": "RUN", "reason": "Momentum iterative waveform attack supported."},
        {"attack_name": "CarliniWagnerASR", "decision": "RUN", "reason": "ASR-native attack supported by speech recognizer estimator."},
        {"attack_name": "ImperceptibleASR", "decision": "RUN", "reason": "ASR-native psychoacoustic attack supported."},
    ]
    if cuda_available:
        entries.append(
            {
                "attack_name": "ImperceptibleASRPyTorch",
                "decision": "RUN",
                "reason": "CUDA-backed PyTorch ASR attack supported on this host.",
            }
        )
    else:
        entries.append(
            {
                "attack_name": "ImperceptibleASRPyTorch",
                "decision": "BLOCKED_BY_RESOURCES",
                "reason": "ART implementation requires CUDA; this host is not exposing a CUDA device.",
            }
        )
    return entries


def attack_params(name: str) -> dict[str, Any]:
    if name == "FastGradientMethod":
        return {"eps": 0.005, "eps_step": 0.001, "targeted": True, "num_random_init": 0, "batch_size": 1}
    if name == "BasicIterativeMethod":
        return {"eps": 0.005, "eps_step": 0.001, "max_iter": 5, "targeted": True, "batch_size": 1, "verbose": True}
    if name == "ProjectedGradientDescent":
        return {"eps": 0.005, "eps_step": 0.001, "max_iter": 5, "targeted": True, "num_random_init": 0, "batch_size": 1, "verbose": True}
    if name == "ProjectedGradientDescentNumpy":
        return {"eps": 0.005, "eps_step": 0.001, "max_iter": 5, "targeted": True, "num_random_init": 0, "batch_size": 1, "verbose": True}
    if name == "MomentumIterativeMethod":
        return {"eps": 0.005, "eps_step": 0.001, "decay": 1.0, "max_iter": 5, "targeted": True, "batch_size": 1, "verbose": True}
    if name == "CarliniWagnerASR":
        return {"eps": 0.05, "learning_rate": 0.001, "max_iter": 5, "batch_size": 1}
    if name == "ImperceptibleASR":
        return {"eps": 0.05, "learning_rate_1": 0.001, "max_iter_1": 5, "alpha": 0.001, "learning_rate_2": 0.0005, "max_iter_2": 5, "batch_size": 1}
    if name == "ImperceptibleASRPyTorch":
        return {"eps": 0.05, "learning_rate_1": 0.001, "max_iter_1": 5, "learning_rate_2": 0.0005, "max_iter_2": 5, "batch_size": 1}
    raise KeyError(f"Unsupported attack: {name}")


def build_attack(name: str, estimator: WhisperTinyArtSpeechRecognizer, params: dict[str, Any]) -> Any:
    if name == "FastGradientMethod":
        return FastGradientMethod(estimator=estimator, **params)
    if name == "BasicIterativeMethod":
        return BasicIterativeMethod(estimator=estimator, **params)
    if name == "ProjectedGradientDescent":
        return ProjectedGradientDescent(estimator=estimator, **params)
    if name == "ProjectedGradientDescentNumpy":
        return ProjectedGradientDescentNumpy(estimator=estimator, **params)
    if name == "MomentumIterativeMethod":
        return MomentumIterativeMethod(estimator=estimator, **params)
    if name == "CarliniWagnerASR":
        return CarliniWagnerASR(estimator=estimator, **params)
    if name == "ImperceptibleASR":
        masker = PsychoacousticMasker(sample_rate=estimator.sample_rate)
        return ImperceptibleASR(estimator=estimator, masker=masker, **params)
    if name == "ImperceptibleASRPyTorch":
        return ImperceptibleASRPyTorch(estimator=estimator, **params)
    raise KeyError(f"Unsupported attack: {name}")


def evaluate_attack(
    attack_name: str,
    clean_transcript: str,
    adv_transcript: str,
    target_text: str,
    runtime_sec: float,
    params: dict[str, Any],
) -> dict[str, Any]:
    return {
        "attack_name": attack_name,
        "status": "RUN",
        "runtime_sec": runtime_sec,
        "attack_parameters": params,
        "clean_transcript": clean_transcript,
        "adversarial_transcript": adv_transcript,
        "transcript_changed": normalize_text(clean_transcript) != normalize_text(adv_transcript),
        "target_matched": normalize_text(adv_transcript) == normalize_text(target_text),
    }


def build_html_report(report: dict[str, Any], html_path: Path) -> None:
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text(build_html(report), encoding="utf-8")


def run_scan(args: argparse.Namespace) -> dict[str, Any]:
    project_dir = Path(args.output_dir)
    reports_dir = project_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    logger = configure_logging(reports_dir / "run_log.txt")

    audio_path = ensure_demo_audio(Path(args.audio), DEFAULT_SAMPLE_RATE) if args.create_demo_audio else Path(args.audio)
    if not audio_path.exists():
        raise FileNotFoundError(f"Audio file not found: {audio_path}")

    resources = load_resources(args.model_id, args.device)
    logger.info("Loaded model=%s on device=%s dtype=%s", resources.model_id, resources.device, resources.dtype)

    waveform, sample_rate = load_waveform(audio_path, DEFAULT_SAMPLE_RATE, args.clip_seconds)
    batch = np.expand_dims(waveform, axis=0).astype(np.float32)
    estimator = WhisperTinyArtSpeechRecognizer(resources=resources, sample_rate=sample_rate, input_length=batch.shape[1])

    clean_predictions = estimator.predict(batch, batch_size=1)
    clean_transcript = str(clean_predictions[0]) if len(clean_predictions) else ""
    logger.info("Clean transcript: %s", clean_transcript)

    inventory = build_attack_inventory(cuda_available=torch.cuda.is_available())
    target_text = args.target_text

    per_attack_results: list[dict[str, Any]] = []
    skipped_attacks: list[dict[str, Any]] = []
    for entry in inventory:
        name = entry["attack_name"]
        if entry["decision"] != "RUN":
            skipped_attacks.append(entry)
            logger.info("Skipping %s: %s", name, entry["reason"])
            continue

        params = attack_params(name)
        logger.info("Starting attack %s with params=%s", name, params)
        started = time.perf_counter()
        try:
            attack = build_attack(name, estimator, params)
            adv_x = attack.generate(x=batch, y=np.array([target_text], dtype=object))
            adv_prediction = estimator.predict(adv_x.astype(np.float32), batch_size=1)
            adv_transcript = str(adv_prediction[0]) if len(adv_prediction) else ""
            runtime_sec = time.perf_counter() - started
            result = evaluate_attack(name, clean_transcript, adv_transcript, target_text, runtime_sec, params)
            result["perturbation_linf"] = float(np.max(np.abs(adv_x - batch)))
            per_attack_results.append(result)
            logger.info(
                "Completed attack %s in %.2fs; changed=%s target_matched=%s",
                name,
                runtime_sec,
                result["transcript_changed"],
                result["target_matched"],
            )
        except Exception as exc:
            runtime_sec = time.perf_counter() - started
            failure = {
                "attack_name": name,
                "status": "FAILED_AT_RUNTIME",
                "runtime_sec": runtime_sec,
                "attack_parameters": params,
                "error": repr(exc),
            }
            per_attack_results.append(failure)
            logger.exception("Attack %s failed after %.2fs", name, runtime_sec)

    report = {
        "timestamps": {"started_at_utc": now_utc(), "finished_at_utc": now_utc()},
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "machine": platform.machine(),
            "torch": torch.__version__,
            "cuda_available": torch.cuda.is_available(),
            "cuda_device_count": torch.cuda.device_count() if torch.cuda.is_available() else 0,
            "device_used": str(resources.device),
            "pid": os.getpid(),
        },
        "model": {
            "model_id": resources.model_id,
            "task_boundary": "small Whisper ASR demo with IBM ART waveform and ASR-native attacks",
        },
        "input": {
            "audio_path": str(audio_path.resolve()),
            "sample_rate": sample_rate,
            "clip_seconds": args.clip_seconds,
            "target_text": target_text,
        },
        "clean_result": {"transcript": clean_transcript},
        "attack_inventory": inventory,
        "per_attack_results": per_attack_results,
        "skipped_attacks": skipped_attacks,
    }
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Vendored Whisper Tiny + IBM ART audio demo.")
    parser.add_argument("--audio", default="samples/demo_tone.wav", help="Path to a WAV file. Use --create-demo-audio to synthesize one if missing.")
    parser.add_argument("--create-demo-audio", action="store_true", help="Create a tiny synthetic demo WAV if --audio does not exist.")
    parser.add_argument("--model-id", default=DEFAULT_MODEL_ID, help="Smaller demo model to use instead of Whisper Large V3.")
    parser.add_argument("--device", default="auto", choices=["auto", "cpu", "cuda"], help="Preferred execution device.")
    parser.add_argument("--clip-seconds", type=float, default=DEFAULT_CLIP_SECONDS, help="Pad or trim audio to this duration.")
    parser.add_argument("--target-text", default=DEFAULT_TARGET_TRANSCRIPT, help="Target phrase for targeted attacks.")
    parser.add_argument("--output-dir", default="vendored_art_demo_output", help="Directory where reports and logs will be written.")
    args = parser.parse_args()

    report = run_scan(args)
    output_dir = Path(args.output_dir)
    results_path = output_dir / "reports" / "results.json"
    html_path = output_dir / "reports" / "report.html"
    write_json(results_path, report)
    build_html_report(report, html_path)
    print(
        json.dumps(
            {
                "output_dir": str(output_dir.resolve()),
                "results_path": str(results_path.resolve()),
                "html_path": str(html_path.resolve()),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
