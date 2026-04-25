UNIVERSAL ADVERSERIAL AI TESTING KIT

CURRENT STATE

This repository is a private-source scanning platform foundation with:

- a FastAPI backend and browser UI
- wrapper registration and persistence
- execution planning for black-box and white-box scans
- a real local Whisper Tiny plus IBM ART white-box path
- a real local TrOCR plus IBM ART path with split blackbox and whitebox summaries
- smoke-tested demo paths for wrapper-based white-box and API-based black-box orchestration
- scaffolding for Foolbox, PyRIT, Garak, Giskard, Promptfoo, and TextAttack

REAL VS DEMO PATHS

Real model-backed path today:

- openai/whisper-tiny.en
- local Hugging Face snapshot
- python_process_wrapped backend
- IBM ART through user_wrappers/whisper_tiny_art_adapter.py
- microsoft/trocr-small-printed
- python_process_wrapped backend
- IBM ART through user_wrappers/trocr_small_art_adapter.py

Demo-only smoke paths today:

- wrapper-based white-box orchestration through user_wrappers/demo_adapter.py
- API-based black-box orchestration through user_wrappers/demo_adapter.py

Important honesty note:

The demo adapter proves platform routing and executor behavior.
It does NOT prove a real third-party API assessment or a real model-backed Foolbox, PyRIT, Garak, or Giskard integration.

WHAT THE UI NOW SUPPORTS

- required fields are visibly marked
- blank required form fields are blocked before submission
- wrapper compatibility filtering
- preflight validation
- wrapper capability matrix
- live job status with auto refresh
- artifact browsing for text-like and HTML outputs
- terminal-style execution detail viewing
- clear "Single select" and "Multi-select allowed" guidance on relevant form groups

WHAT THE WRAPPER CAPABILITY MATRIX SHOWS

The matrix shows registered wrappers returned by the backend registry.
It does not automatically list every Python file under user_wrappers.

CURRENT PRACTICAL WRAPPERS

- demo_adapter
  smoke adapter for orchestration checks
- whisper_tiny_art_adapter
  real local Whisper Tiny + IBM ART path
- trocr_small_art_adapter
  real local TrOCR + IBM ART OCR path

HOW IT IS MEANT TO WORK

1. Launch the UI.
2. Choose a model source, task family, backend, scan modes, frameworks, and reports.
3. Optionally register a custom wrapper.
4. Run preflight to see blockers, warnings, and compatible wrappers.
5. Launch the job.
6. Review job status, browse artifacts, and inspect terminal-style execution details from the UI.

WHAT IS REAL TODAY

- local white-box Whisper Tiny plus IBM ART
- local TrOCR plus IBM ART
- wrapper-based orchestration routing
- API-based orchestration routing in demo form

WHAT STILL NEEDS IMPLEMENTATION FOR FULLER COVERAGE

- real API wrappers for specific provider endpoints
- more model-backed framework executors
- stronger report-availability gating for pdf and xlsx
- saved job templates
- wrapper test button
- safer wrapper trust and execution workflow

RUN LOCALLY

Minimal platform setup:

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

DEPENDENCY POLICY

- ART, Foolbox, Garak, and PyRIT should be installed during the standard platform setup path.
- local model servers such as Ollama remain external infrastructure.
- the goal is reproducible deployment, not hidden first-run package installation.

See:

- docs/deployment_dependency_policy.md

For the real Whisper Tiny plus ART path:

pip install -r requirements-art-whisper.txt
PYTHONPATH=. .venv/bin/python run_whisper_art_demo.py

If the model is already cached and the environment is network-restricted:

HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 PYTHONPATH=. .venv/bin/python run_whisper_art_demo.py

Launch the UI:

PYTHONPATH=. .venv/bin/uvicorn whitebox_scan_platform.app:app --host 127.0.0.1 --port 8011

Then open:

http://127.0.0.1:8011

SCREENSHOT WORKFLOW

Refresh the main repo screenshot with:

chmod +x scripts/refresh_product_screenshot.sh
./scripts/refresh_product_screenshot.sh --source /absolute/path/to/new-product-screenshot.png --label "Describe UI update here"

This keeps README.md and docs/index.html aligned to the same screenshot asset.

CAVEATS

- api_based does not automatically mean real black-box provider integration exists
- true white-box usually requires local model access, gradients, logits, or estimator-compatible behavior
- report availability depends on the selected execution path
- pdf and xlsx should not be assumed unless that path actually exports them
- CUDA-only attacks will be skipped honestly on non-CUDA hosts
- split blackbox and whitebox summaries are written under data/job_reports/<job_id>/reports/
- framework-level IBM ART artifacts are written under data/art_runs/<job_id>/reports/

GITHUB-ORIENTED REPO FILES TO CHECK

- README.md
- docs/index.html
- GITHUB_PAGES_SETUP.txt
- PRIVATE_GITHUB_PUBLISHING.txt
- CONTRIBUTING.md
- SECURITY.md

For fuller details, use README.md as the primary source of truth.
