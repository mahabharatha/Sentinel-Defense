# Sentinel Adversarial Orchestrator — Setup Guide

This document is the canonical install reference for the orchestrator. It
covers prerequisites, the one-command installer, manual installation, the
optional one-time HF cache warm-up, and the offline-NLTK procedure that the
TextAttack constraints depend on. It is written to be skim-friendly at the
top and exhaustively detailed in the per-step sections below.

> **Audience.** Operators, integrators, and reviewers preparing a host (laptop,
> workstation, container, or CI runner) to run end-to-end adversarial scans
> against text, vision, audio, and multimodal models.

---

## 1. Quick start (TL;DR)

If your host has Python 3.11+ and an internet connection during the first
warm-up:

```bash
git clone <your-private-remote-url> sentinel
cd sentinel
./install.sh                                              # creates venv, installs deps, scaffolds data/
source venv/bin/activate
python scripts/warm_hf_cache.py --include-vision --include-audio
bash scripts/install_nltk_offline.sh                       # NLTK corpora used by TextAttack constraints
python run.py                                              # http://127.0.0.1:8000
```

Open http://127.0.0.1:8000 in a browser. Skip ahead to
[USAGE.md](USAGE.md) for the operator walkthrough.

---

## 2. Supported platforms

| Platform     | Status                       | Notes                                                                                       |
|--------------|------------------------------|---------------------------------------------------------------------------------------------|
| macOS 12+    | First-class                  | Apple Silicon and Intel both work; the project ships with a Python 3.11 venv layout.        |
| Linux x86_64 | First-class                  | Tested on Ubuntu 22.04 / Fedora 39 / Debian 12. Container images recommended for CI.        |
| Linux arm64  | Supported                    | Same toolchain; pin `torch>=2.3` for arm wheels.                                            |
| Windows 10+  | Supported with WSL2          | Native Windows is unsupported because some adversarial frameworks (PyRIT, TextAttack)       |
|              |                              | rely on POSIX subprocess semantics. WSL2 + Ubuntu 22.04 is the tested path.                 |
| Docker       | Recommended for CI           | Build a slim image around `python:3.11-slim` and copy the repo plus a pre-warmed HF cache.  |

CPU-only hosts work for every framework except IBM ART white-box attacks on
large vision/audio targets, which benefit (but do not require) GPU / MPS.

---

## 3. Prerequisites

### 3.1 Required

- **Python ≥ 3.11.** The project pins `requires-python = ">=3.11"` in
  `pyproject.toml`. PyRIT additionally restricts itself to `<3.14` (see
  `compatibility.framework_compatibility_profiles`).
- **pip ≥ 24** and **wheel**. The installer will upgrade both inside the venv
  before resolving requirements.
- **A C/C++ toolchain** for building any wheels that don't ship pre-built for
  your interpreter (`xcode-select --install` on macOS; `build-essential` on
  Debian/Ubuntu; `Development Tools` on Fedora).
- **git** for cloning the private repository.
- **curl** and **unzip** for the offline NLTK installer.

### 3.2 Optional but recommended

- **Ollama** for local LLM/VLM execution paths used by Garak and PyRIT
  templates. Install from <https://ollama.ai> and pull the models referenced
  by built-in templates:
  ```bash
  ollama pull tinyllama:1.1b-chat
  ollama pull gemma3:4b
  ```
  The orchestrator auto-detects an Ollama daemon at `127.0.0.1:11434` and
  surfaces its reachability and loaded models in the UI's Local Service
  Health card.
- **`hf_transfer`** (`pip install hf_transfer`) for ~10× faster Hugging Face
  downloads. The cache-warmer script will use it automatically when
  `HF_HUB_ENABLE_HF_TRANSFER=1` is exported.
- **GPU drivers** (CUDA, ROCm, or Apple's Metal stack). Not required for any
  built-in template, but accelerates IBM ART / Foolbox white-box runs.

### 3.3 Disk and memory budget

| Asset                          | Size (approx) | Required for                                            |
|--------------------------------|--------------:|---------------------------------------------------------|
| Python venv + base deps        |       350 MB  | API server, schemas                                     |
| Adversarial framework deps     |      2.5 GB  | ART, Foolbox, PyRIT, Garak, TextAttack                  |
| HF cache (text only)           |       450 MB  | TextAttack templates (`bert-base-uncased`, distilbert)  |
| HF cache (+ vision)            |      +1.6 GB  | ART OCR / vision-classification templates               |
| HF cache (+ audio)             |     +200 MB  | Whisper Tiny speech-to-text demos                       |
| NLTK data                      |        12 MB  | TextAttack POS / tokenization / lemma constraints       |
| Per-job artefacts              |  10 KB–5 MB  | Per scan in `data/job_reports/<job_id>/`                |

8 GB of free disk and 8 GB of RAM are comfortable for routine usage. White-box
runs against larger targets benefit from 16 GB+.

---

## 4. The one-command installer

```bash
./install.sh                  # full install (default)
./install.sh --core           # API surface only — skips ML deps for fast boot
./install.sh --force          # delete and recreate venv/
./install.sh --skip-data      # don't scaffold data/ subdirectories
./install.sh --help           # show usage
```

**What it does, in order:**

1. **Locates a suitable Python.** Prefers `python3.11`, then `python3.12`,
   `python3.13`, then `python3`. Aborts (exit 1) if no interpreter ≥ 3.11 is
   on `$PATH`.
2. **Creates `venv/`** beside the repo using `python -m venv`.
3. **Activates the venv** for the remainder of the script.
4. **Upgrades pip, wheel, setuptools** quietly inside the venv.
5. **Installs requirements.** `requirements-core.txt` is the lightweight set
   (`fastapi`, `uvicorn`, `pydantic`, `httpx`, `Pillow`); `requirements.txt`
   adds the adversarial frameworks plus their ML dependencies. The `--core`
   flag picks the smaller set; the default picks the full set.
6. **Scaffolds `data/`** with `jobs/`, `job_reports/`, `demo/`,
   `matplotlib_cache/`, `textattack_cache/`, `textattack_runs/`,
   `pyrit_multimodal_smoke/`, plus empty `wrappers.json` and `templates.json`
   index files (skipped when `--skip-data` is passed).
7. **Verifies the install** by attempting `import` of `fastapi`, `uvicorn`,
   `pydantic`, and `httpx`. Exits 3 if any are missing — usually means your
   pip mirror is blocking access or a wheel failed to build.

The installer is idempotent. Re-running it on an existing venv updates pip
and re-resolves requirements without nuking the environment unless `--force`
is passed.

### 4.1 Manual install (when `install.sh` cannot run)

```bash
python3.11 -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip wheel setuptools
python -m pip install -r requirements.txt
mkdir -p data/jobs data/job_reports data/demo data/textattack_cache \
         data/textattack_runs data/pyrit_multimodal_smoke
[ -f data/wrappers.json ] || echo '{"wrappers": []}' > data/wrappers.json
[ -f data/templates.json ] || echo '{"templates": []}' > data/templates.json
```

This reproduces every step the script performs.

---

## 5. Pre-warming caches

Every framework executor that loads a Hugging Face model runs subprocesses
with `HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1` set, so the cache must
be populated before the first run.

### 5.1 HF model cache (online, one-time)

```bash
python scripts/warm_hf_cache.py                       # text only (TextAttack)
python scripts/warm_hf_cache.py --include-vision      # + ViT, TrOCR
python scripts/warm_hf_cache.py --include-audio       # + Whisper Tiny
python scripts/warm_hf_cache.py --include-vision --include-audio   # full set
```

The script downloads models into `data/textattack_cache/` (which the runner
treats as `HF_HOME`). It is safe to re-run; existing files are skipped via HF
hub's content-addressable cache.

If you are behind a corporate proxy or hit `CERTIFICATE_VERIFY_FAILED`, set
`SSL_CERT_FILE=$(python -m certifi)` before the script. The script also sets
this automatically when `certifi` is installed.

For faster downloads, install `hf_transfer` once and re-run with the env var:

```bash
pip install hf_transfer
HF_HUB_ENABLE_HF_TRANSFER=1 python scripts/warm_hf_cache.py --include-vision --include-audio
```

### 5.2 NLTK corpora (cross-platform, offline-friendly)

`scripts/install_nltk_offline.sh` fetches the NLTK zip files via `curl` (which
trusts the OS certificate store on every platform) and unpacks them into
`venv/nltk_data/`. The script is the recommended path because Python's
built-in `nltk.download()` frequently fails with `CERTIFICATE_VERIFY_FAILED`
on stock interpreters.

```bash
bash scripts/install_nltk_offline.sh
```

You should see eight `installed -> …` lines and a final `summary: 8
installed, 0 failed`. If any line fails, see [TROUBLESHOOTING.md](TROUBLESHOOTING.md#ssl-certificate-failures).

### 5.3 Ollama models (only for Garak + PyRIT templates)

```bash
ollama serve &
ollama pull tinyllama:1.1b-chat
ollama pull gemma3:4b
```

Verify the daemon and models are visible to Sentinel by reloading the UI;
the **Local Service Health** card should show `ollama` as `reachable=true`
with both model identifiers as separate chips.

---

## 6. Starting the server

```bash
source venv/bin/activate
python run.py                            # 127.0.0.1:8000, no autoreload
python run.py --host 0.0.0.0             # expose to LAN
python run.py --port 8888                # custom port
python run.py --reload                   # uvicorn autoreload (dev only)
```

The server logs `Starting Sentinel Adversarial Orchestrator at http://...`
and serves the single-page UI at `/`. All API endpoints live under `/api/`
(see [USAGE.md](USAGE.md) for the API reference).

To stop the server, send SIGINT (`Ctrl+C` in the foreground terminal) or use
`pkill -f run.py` if it was backgrounded.

---

## 7. Verifying the install

### 7.1 Static check

```bash
python -c "import sentinel.app, sentinel.executor, sentinel.jobs, sentinel.preflight, sentinel.templates; print('imports ok')"
```

### 7.2 Unit test suite

```bash
source venv/bin/activate
pytest tests/ -v
pytest tests/ -v --ignore=tests/test_end_to_end.py --ignore=tests/test_executor_runtime.py    # skip Ollama-dependent suites
```

### 7.3 End-to-end smoke (every built-in template)

```bash
bash scripts/run_full_smoke.sh
```

Expected outcome on a healthy install: **15 / 15 templates clean** in roughly
3.5 minutes (template-by-template progress visible in real time). The
`run_full_smoke.sh` runner stops any prior server, clears `__pycache__`,
starts a fresh server, waits for `/api/options` to respond, runs every
built-in template, validates each report, and stops the server on exit. The
verdict JSON is written to `data/smoke_runs/smoke_<timestamp>.json`. See
[RELEASE_NOTES.md](RELEASE_NOTES.md) for the smoke driver's validation
rules.

To narrow the run:

```bash
SENTINEL_ONLY=11 bash scripts/run_full_smoke.sh             # template #11 only
SENTINEL_SKIP=7,13,14,15 bash scripts/run_full_smoke.sh     # skip Ollama-backed templates
SENTINEL_TIMEOUT=1800 bash scripts/run_full_smoke.sh        # 30-minute per-template ceiling
```

---

## 8. Container image (optional)

A minimal Dockerfile that captures the same setup contract:

```dockerfile
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    HF_HOME=/opt/sentinel/data/textattack_cache \
    TRANSFORMERS_CACHE=/opt/sentinel/data/textattack_cache

RUN apt-get update \
 && apt-get install -y --no-install-recommends curl unzip git build-essential \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/sentinel
COPY . /opt/sentinel/

RUN python -m pip install --upgrade pip wheel setuptools \
 && python -m pip install -r requirements.txt \
 && bash scripts/install_nltk_offline.sh

EXPOSE 8000
CMD ["python", "run.py", "--host", "0.0.0.0", "--port", "8000"]
```

Build and run:

```bash
docker build -t sentinel-orchestrator:latest .
docker run --rm -p 8000:8000 -v "$PWD/data:/opt/sentinel/data" sentinel-orchestrator:latest
```

The `-v` mount keeps `data/jobs/`, `data/job_reports/`, and the HF cache on
the host so they survive container restarts.

For Ollama-backed templates inside Docker, run Ollama on the host and pass
`--add-host=host.docker.internal:host-gateway`, then point the Sentinel
templates' endpoints at `http://host.docker.internal:11434/api/generate`.

---

## 9. Where to go next

- **Operator walkthrough.** [USAGE.md](USAGE.md) — register a wrapper, build a
  scan, read the report.
- **Architecture overview.** [architecture_hld.md](architecture_hld.md) —
  module split, data flow, design ethos mapping.
- **Repo navigation.** [REPO_STRUCTURE.md](REPO_STRUCTURE.md) — every directory
  and what lives there.
- **When something breaks.** [TROUBLESHOOTING.md](TROUBLESHOOTING.md) — common
  errors keyed to root cause and fix.
- **What changed recently.** [RELEASE_NOTES.md](RELEASE_NOTES.md) — concrete
  per-task changelog with file-level diffs.
