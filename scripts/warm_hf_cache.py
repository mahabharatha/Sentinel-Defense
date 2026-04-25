#!/usr/bin/env python3
"""Pre-download the Hugging Face models that built-in templates need, into the
TextAttack / platform offline cache.

The TextAttack runner forces ``HF_HUB_OFFLINE=1`` and ``TRANSFORMERS_OFFLINE=1``
so the subprocess can run without network. If the required model isn't already
in the cache, every TextAttack template fails immediately with
``LocalEntryNotFoundError``. This helper does the one-time online warmup.

Usage:
    # Run ONCE with internet access before the first TextAttack smoke:
    python scripts/warm_hf_cache.py

    # Include ART / OCR / Whisper models the built-in demos expect:
    python scripts/warm_hf_cache.py --include-vision --include-audio

    # Target a specific cache directory (default: the same TA_CACHE_DIR the
    # platform's TextAttack runner uses, data/textattack_cache/):
    python scripts/warm_hf_cache.py --cache-dir /path/to/hf_cache

Environment:
    The script sets HF_HOME / TRANSFORMERS_CACHE to the chosen cache dir so
    that subsequent offline runs find the files in the same place the runner
    reads from.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CACHE = REPO_ROOT / "data" / "textattack_cache"

# Models that the built-in templates rely on.
TEXT_MODELS = [
    # TextAttack smokes (templates 8-12) — all use this HF checkpoint as
    # the target classifier.
    "distilbert-base-uncased-finetuned-sst-2-english",
]
# MaskedLM checkpoints that specific TextAttack recipes load for their
# transformations (e.g. BAE uses bert-base-uncased via WordSwapMaskedLM).
# These need to be cached *in addition* to the classifier above.
TEXT_MASKED_LM_MODELS = [
    "bert-base-uncased",
]
VISION_MODELS = [
    # ART/Foolbox vision-classification demos.
    "google/vit-base-patch16-224",
    # OCR demos.
    "microsoft/trocr-small-printed",
]
AUDIO_MODELS = [
    # Whisper Tiny and the speech-to-text demos.
    "openai/whisper-tiny.en",
]


def warm_text(models: list[str]) -> list[tuple[str, str, str]]:
    from transformers import AutoModelForSequenceClassification, AutoTokenizer
    results: list[tuple[str, str, str]] = []
    for name in models:
        try:
            AutoTokenizer.from_pretrained(name)
            AutoModelForSequenceClassification.from_pretrained(name)
            results.append((name, "ok", ""))
        except Exception as exc:
            results.append((name, "fail", str(exc)[:200]))
    return results


def warm_masked_lm(models: list[str]) -> list[tuple[str, str, str]]:
    """Warm MaskedLM checkpoints used by TextAttack transformations like
    WordSwapMaskedLM (BAE recipe). These are separate from classifier
    checkpoints and must also be in the cache for offline runs."""
    from transformers import AutoModelForMaskedLM, AutoTokenizer
    results: list[tuple[str, str, str]] = []
    for name in models:
        try:
            AutoTokenizer.from_pretrained(name)
            AutoModelForMaskedLM.from_pretrained(name)
            results.append((name, "ok", ""))
        except Exception as exc:
            results.append((name, "fail", str(exc)[:200]))
    return results


def warm_vision(models: list[str]) -> list[tuple[str, str, str]]:
    from transformers import AutoConfig, AutoProcessor
    results = []
    for name in models:
        try:
            AutoConfig.from_pretrained(name)
            try:
                AutoProcessor.from_pretrained(name)
            except Exception:
                pass  # processor-less models fall through; config alone is enough
            results.append((name, "ok", ""))
        except Exception as exc:
            results.append((name, "fail", str(exc)[:200]))
    return results


def warm_audio(models: list[str]) -> list[tuple[str, str, str]]:
    from transformers import AutoConfig, AutoProcessor
    results = []
    for name in models:
        try:
            AutoConfig.from_pretrained(name)
            AutoProcessor.from_pretrained(name)
            results.append((name, "ok", ""))
        except Exception as exc:
            results.append((name, "fail", str(exc)[:200]))
    return results


# NLTK resources that TextAttack constraints rely on. BAE in particular
# needs the perceptron POS tagger (modern NLTK looks for the language-
# tagged variant `averaged_perceptron_tagger_eng`); older recipes pull
# in punkt, stopwords, and wordnet too.
NLTK_RESOURCES = [
    "averaged_perceptron_tagger",
    "averaged_perceptron_tagger_eng",
    "punkt",
    "punkt_tab",
    "stopwords",
    "wordnet",
    "omw-1.4",
    "universal_tagset",
]


def warm_nltk(resources: list[str]) -> list[tuple[str, str, str]]:
    """Download NLTK corpora into the venv's nltk_data dir so TextAttack's
    POS / tokenization / lemma constraints work offline.

    macOS Python (the python.org framework build) ships without a system CA
    bundle, so NLTK's downloader gets ``CERTIFICATE_VERIFY_FAILED`` against
    raw.githubusercontent.com. ``certifi`` is already a transitive dep
    (huggingface_hub pulls it in), so we point Python's SSL stack at
    certifi's bundle before calling ``nltk.download``. As a final fallback
    we patch the NLTK downloader to skip certificate verification — slightly
    less safe but indispensable on machines behind ill-configured
    intercepting proxies.
    """
    try:
        import nltk
    except ImportError:
        return [("(nltk not installed)", "fail", "pip install nltk first")]

    # Step 1: point SSL at certifi's bundle.
    try:
        import certifi
        os.environ.setdefault("SSL_CERT_FILE", certifi.where())
        os.environ.setdefault("REQUESTS_CA_BUNDLE", certifi.where())
    except ImportError:
        certifi = None  # type: ignore

    # Step 2: build an SSL context the NLTK downloader uses for HTTPS.
    import ssl
    try:
        ctx = ssl.create_default_context(cafile=certifi.where()) if certifi else ssl.create_default_context()
    except Exception:
        ctx = ssl._create_unverified_context()  # last resort
    # Patch urllib's default opener so nltk's downloader picks up the context.
    import urllib.request as _urllib_request
    _https_handler = _urllib_request.HTTPSHandler(context=ctx)
    _opener = _urllib_request.build_opener(_https_handler)
    _urllib_request.install_opener(_opener)

    venv_root = Path(sys.executable).resolve().parent.parent
    target_dir = venv_root / "nltk_data"
    target_dir.mkdir(parents=True, exist_ok=True)
    if str(target_dir) not in nltk.data.path:
        nltk.data.path.insert(0, str(target_dir))

    results = []
    for name in resources:
        try:
            ok = nltk.download(name, download_dir=str(target_dir), quiet=True, raise_on_error=True)
            results.append((f"nltk:{name}", "ok" if ok else "fail",
                            "" if ok else "download() returned False"))
        except Exception as exc:
            # Final-fallback: try once with verification disabled
            try:
                _opener_no_verify = _urllib_request.build_opener(
                    _urllib_request.HTTPSHandler(context=ssl._create_unverified_context())
                )
                _urllib_request.install_opener(_opener_no_verify)
                ok = nltk.download(name, download_dir=str(target_dir), quiet=True, raise_on_error=True)
                results.append((f"nltk:{name}", "ok-unverified" if ok else "fail",
                                "" if ok else "download() returned False"))
                # Restore verifying opener for the next iteration
                _urllib_request.install_opener(_opener)
            except Exception as exc2:
                results.append((f"nltk:{name}", "fail", str(exc2)[:200]))
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cache-dir", default=str(DEFAULT_CACHE),
                        help=f"HF cache directory (default: {DEFAULT_CACHE}).")
    parser.add_argument("--include-vision", action="store_true",
                        help="Also download ViT / TrOCR models used by the vision/OCR templates.")
    parser.add_argument("--include-audio", action="store_true",
                        help="Also download Whisper Tiny used by the speech-to-text templates.")
    parser.add_argument("--only-text", action="store_true",
                        help="Only warm the TextAttack models (default behaviour).")
    args = parser.parse_args()

    cache_dir = Path(args.cache_dir).expanduser().resolve()
    cache_dir.mkdir(parents=True, exist_ok=True)
    # Point HF/transformers at the same path the TextAttack runner will read.
    os.environ["HF_HOME"] = str(cache_dir)
    os.environ["TRANSFORMERS_CACHE"] = str(cache_dir)
    os.environ.pop("HF_HUB_OFFLINE", None)
    os.environ.pop("TRANSFORMERS_OFFLINE", None)

    print(f"[warm] cache dir: {cache_dir}")
    print("[warm] downloading (online)...")

    try:
        import transformers  # noqa: F401
    except ImportError:
        print("[error] transformers is not installed in this venv. "
              "Run 'pip install transformers' or './install.sh' first.", file=sys.stderr)
        return 2

    rows: list[tuple[str, str, str]] = []
    rows += warm_text(TEXT_MODELS)
    rows += warm_masked_lm(TEXT_MASKED_LM_MODELS)
    rows += warm_nltk(NLTK_RESOURCES)
    if args.include_vision:
        rows += warm_vision(VISION_MODELS)
    if args.include_audio:
        rows += warm_audio(AUDIO_MODELS)

    print("\n" + "=" * 80)
    print(f"{'status':8s}  model")
    print("-" * 80)
    any_fail = False
    for name, status, err in rows:
        print(f"{status:8s}  {name}")
        if err:
            print(f"          {err}")
        if status != "ok":
            any_fail = True
    print("-" * 80)
    if any_fail:
        print("\n[warm] Some downloads failed. Check your internet connection and retry.")
        return 1
    print("\n[warm] Cache is ready. TextAttack templates can now run offline.")
    print(f"[warm] Verify with:  ls {cache_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
