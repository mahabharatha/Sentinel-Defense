# Deployment Runtime Checklist

This checklist is the Phase 3 operational hardening baseline for the platform,
with special focus on the built-in PyRIT multimodal path.

## What Must Exist Before Launch

For a supported deployment, the application environment should already contain:

- The API runtime and platform dependencies from `requirements.txt`
- `IBM ART`
- `Foolbox`
- `Garak`
- `PyRIT`

These are platform runtime dependencies and should be installed during the
normal bootstrap path, image build, or deployment job.

## What Stays External

These are still external infrastructure:

- `Ollama`
- any other local inference server
- hosted inference APIs

The platform can preflight-check local Ollama reachability, but it does not
install or manage Ollama itself.

## Recommended Python Runtime

PyRIT in this build expects a Python runtime compatible with:

- `>=3.10,<3.14`

Recommended local bootstrap:

```bash
cd /Users/macmacmac/Documents/whitebox_scan_platform
python3.11 -m venv .venv311
.venv311/bin/python -m pip install --upgrade pip
.venv311/bin/python -m pip install -r requirements.txt
```

## Recommended App Start Command

Run the app from the Python environment that contains the framework packages:

```bash
cd /Users/macmacmac/Documents/whitebox_scan_platform
PYTHONPATH=/Users/macmacmac/Documents .venv311/bin/python -m uvicorn whitebox_scan_platform.app:app --host 127.0.0.1 --port 8013
```

## Recommended Local VLM Checks

Before running PyRIT multimodal scans against Ollama:

1. Confirm Ollama is reachable:

```bash
curl -s http://127.0.0.1:11434/api/tags
```

2. Confirm the target model exists in the Ollama model list.

3. Confirm the seed image path exists on disk.

4. Run the platform preflight check before launching the job.

## What Phase 3 Added

The app now exposes:

- framework runtime inventory in `/api/options`
- Python runtime details in `/api/options`
- local service health in `/api/options`
- preflight blockers for:
  - missing local Ollama reachability for PyRIT and Garak local runs
  - missing local Ollama model for PyRIT and Garak local runs
  - missing multimodal seed image for PyRIT multimodal runs

## Operator Expectation

If preflight says `ready`, the deployment baseline is in a healthier state than
before, but it still does not guarantee that the target model will comply with
the attack objective.

Preflight is meant to catch setup failures early, not to predict scan outcomes.
