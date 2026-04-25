# Sentinel Adversarial Orchestrator — Repository Structure

Annotated walkthrough of every top-level directory and significant file in
the repo. The orchestrator is intentionally a flat layout: source modules at
the root, runtime artefacts under `data/`, documentation under `docs/`, and
a small set of operator scripts under `scripts/`. There is no `src/` indirection.

> **Conventions.** Italics denote regenerable / runtime artefacts that are
> intentionally untracked by git (see `.gitignore`). Bold denotes shippable
> source.

---

## 1. Tree at a glance

```
sentinel/
├─ README.md                    # Project entry point and link hub
├─ LICENSE.txt                  # Proprietary license terms (do not relax)
├─ NOTICE.txt                   # Third-party attribution required by deps
├─ CONTRIBUTING.md              # Internal contribution checklist
├─ SECURITY.md                  # Vulnerability disclosure policy
├─ THIRD_PARTY_COMPLIANCE.txt   # Licensing audit trail
├─ install.sh                   # One-command installer
├─ pyproject.toml               # Build metadata
├─ requirements.txt             # Full ML stack
├─ requirements-core.txt        # API surface only
├─ requirements-art-whisper.txt # ART speech-to-text demo deps
├─ run.py                       # uvicorn launcher
├─ __init__.py                  # Package marker for `sentinel`
├─ app.py                       # API surface (23 endpoints)
├─ schemas.py                   # Pydantic models for every payload
├─ contracts.py                 # BaseScanAdapter protocol
├─ compatibility.py             # Per-framework profiles + version probing
├─ framework_registry.py        # Framework dispatch contract
├─ executor.py                  # Orchestration facade (post-refactor)
├─ templates.py                 # Template CRUD (extracted from executor.py)
├─ preflight.py                 # Runtime evaluation (extracted)
├─ jobs.py                      # Job lifecycle + wrapper manager (extracted)
├─ storage.py                   # File-backed persistence with atomic writes
│
├─ executors/                   # Per-framework executor modules
│  ├─ __init__.py
│  ├─ art_executor.py
│  ├─ foolbox_executor.py
│  ├─ garak_executor.py
│  ├─ garak_runner.py
│  ├─ garak_ollama_function.py
│  ├─ pyrit_executor.py
│  ├─ pyrit_runner.py
│  ├─ textattack_executor.py
│  └─ textattack_runner.py
│
├─ reporting/                   # Reporting subpackage (extracted Task 5)
│  ├─ __init__.py
│  ├─ utils.py                  # HTML helpers, scalar/table renderers
│  ├─ normalized.py             # Unified severity engine + per-framework normalizers
│  ├─ pyrit.py                  # PyRIT renderers
│  ├─ garak.py                  # Garak renderers
│  ├─ textattack.py             # TextAttack renderers
│  ├─ foolbox.py                # Foolbox renderers
│  └─ art.py                    # ART renderers
│
├─ user_wrappers/               # Built-in adapter implementations
│  ├─ whisper_tiny_art_adapter.py
│  ├─ hf_speech_to_text_art_adapter.py
│  ├─ hf_ocr_art_adapter.py
│  ├─ trocr_small_art_adapter.py
│  ├─ hf_vision_classification_art_adapter.py
│  └─ hf_vision_foolbox_adapter.py
│
├─ whitebox_scan_platform/      # Compatibility shim package
│  ├─ __init__.py               # Mirrors sentinel.* under whitebox_scan_platform.*
│  └─ executors/                # Subprocess entry points referenced by -m calls
│
├─ ui/
│  └─ index.html                # Single-page operator console (~4500 lines)
│
├─ docs/                        # All Markdown documentation lives here
│  ├─ architecture_hld.md       # High-level design + mermaid diagram
│  ├─ index.html                # Public landing page (separate from app UI)
│  ├─ normalized_severity_framework.md
│  ├─ tool_compatibility_layer.md
│  ├─ deployment_runtime_checklist.md
│  ├─ deployment_dependency_policy.md
│  ├─ pyrit_multimodal_smoke_matrix.md
│  ├─ textattack_smoke_matrix.md
│  ├─ SETUP.md                  # Comprehensive install reference
│  ├─ USAGE.md                  # Operator walkthrough
│  ├─ REPO_STRUCTURE.md         # This file
│  ├─ TROUBLESHOOTING.md        # Error → fix lookup
│  ├─ RELEASE_NOTES.md          # Per-task changelog
│  └─ images/
│     ├─ sentinel-orchestrator-logo.svg
│     ├─ product-screenshot-current.png
│     └─ product-screenshot.json   # Cache-bust metadata for the screenshot
│
├─ scripts/                     # Operator helpers
│  ├─ run_full_smoke.sh         # One-shot end-to-end smoke runner
│  ├─ smoke_all_builtins.py     # Driver invoked by run_full_smoke
│  ├─ warm_hf_cache.py          # Pre-download HF models + NLTK corpora
│  ├─ install_nltk_offline.sh   # curl-based NLTK installer (SSL-safe)
│  ├─ cleanup_failed_jobs.py    # Remove failed-status job records
│  ├─ add_repo_collaborator.sh  # GitHub admin helper
│  ├─ refresh_product_screenshot.sh
│  └─ update_git.sh
│
├─ tests/                       # pytest suites
│  ├─ test_end_to_end.py        # Hits the live server
│  ├─ test_executor_runtime.py  # Smoke-style integration tests
│  ├─ test_garak_executor.py
│  ├─ test_pyrit_executor.py
│  ├─ test_textattack_executor.py
│  ├─ test_normalized_severity.py
│  ├─ test_security_and_registry.py
│  └─ test_tool_compatibility.py
│
├─ sentinel_patch/              # Self-contained patch deliverable mirroring
│  ├─ PATCH_README.md           # changes that ship to a deployed instance
│  ├─ run.py
│  ├─ app.py
│  ├─ compatibility.py
│  ├─ requirements*.txt
│  ├─ index.html
│  └─ whitebox_scan_platform/
│
├─ rhel_art_audio_demo/         # Optional demo bundle for IBM ART speech-to-text
│  └─ samples/
│     └─ demo_tone.wav          # Generated by setup; not tracked
│
└─ data/                        # *Runtime artefacts. Mostly ignored by git.*
   ├─ builtin_templates.json    # **Tracked** — 15 built-in templates (Task 6)
   ├─ wrappers.json             # *Generated index of registered wrappers*
   ├─ templates.json            # *User-saved templates*
   ├─ demo/                     # *Demo input assets*
   │  └─ textattack_smoke_samples.jsonl  # **Tracked** — small smoke pack
   ├─ jobs/                     # *Per-job records (one JSON per job_id)*
   ├─ job_reports/              # *Per-job report bundles*
   │  └─ <job_id>/reports/      # Mode summaries + native mirrors
   ├─ art_runs/                 # *IBM ART native artefacts*
   ├─ foolbox_runs/             # *Foolbox native artefacts*
   ├─ garak_runs/               # *Garak native artefacts*
   ├─ pyrit_runs/               # *PyRIT native artefacts (per attack run)*
   ├─ textattack_runs/          # *TextAttack native artefacts*
   ├─ ocr_runs/                 # *Legacy OCR run output*
   ├─ test_runs/                # *Test fixture run output*
   ├─ smoke_runs/               # *run_full_smoke.sh output*
   ├─ textattack_cache/         # *HF model cache (HF_HOME pointer)*
   ├─ matplotlib_cache/         # *Matplotlib font cache*
   └─ pyrit_multimodal_smoke/   # *PyRIT multimodal smoke fixtures*
```

---

## 2. Source modules — module-by-module reference

### 2.1 The orchestration core

#### `app.py`
The API surface. Defines the application instance, configures background
tasks, owns every `@app.{get,post,put,delete}` route, and bridges every
endpoint to the orchestration helpers in `executor.py`. On first import it
calls `ensure_dirs()`, `sync_builtin_wrappers()`, and
`reconcile_job_statuses()` so the instance starts with a clean view of the
filesystem.

#### `executor.py` (facade)
After Task 7 (the orchestration split), `executor.py` is a 1.55-K-line
**facade** that retains the cross-layer orchestrator
(`execute_job_record`), the mode-summary HTML rendering, and the sample
loader helpers. Everything else (template CRUD, preflight, job lifecycle,
wrapper management, reporting) lives in dedicated modules and is
re-exported from the bottom of this file. This means existing imports such
as `from sentinel.executor import build_preflight` keep working unchanged.

#### `templates.py`
Template CRUD: `sync_builtin_templates`, `list_templates`, `save_template`,
`create_template`, `update_template`, `delete_template`, `export_template`,
`import_template`. Loads `BUILTIN_TEMPLATES` from
`data/builtin_templates.json` at module import time.

#### `preflight.py`
Runtime evaluation: `python_runtime_summary`, local Ollama detection,
`evaluate_platform_support`, `evaluate_wrapper_compatibility`,
`evaluate_runtime_readiness`, `report_expectations`, `build_preflight`.
Holds `FRAMEWORK_RUNTIME_SPECS` as the single source of truth derived from
`compatibility.framework_compatibility_profiles`.

#### `jobs.py`
Wrapper + job lifecycle: `register_wrapper`, `sync_builtin_wrappers`,
`list_wrappers` (with the post-Task-1 `installed_versions` enrichment),
`build_execution_plan`, `create_job` (Task 11 collision-resistant IDs),
`run_job`, `list_jobs`, `reconcile_job_statuses` (Task 10 lock-protected),
`build_job_terminal_view`, `collect_job_artifacts`, plus the wrapper cache.

#### `storage.py`
File-backed persistence with atomic writes (tempfile + os.replace + fsync,
Task 10) and a module-level `JOB_WRITE_LOCK` (RLock) shared with
`reconcile_job_statuses`. Centralizes path resolution to keep artefacts
inside the repo root.

#### `schemas.py`
Pydantic models for every payload: `ModelSelection`, `ScanConfiguration`,
`ScanJobCreate`, `ScanJobRecord`, `JobTemplateCreate`,
`JobTemplateUpdate`, `JobTemplateImport`, `JobTemplateRecord`,
`WrapperRegistration`, `WrapperInfo`. Type literals for
`ExecutionBackend`, `ScanMode`, `FrameworkName`, `ReportName`, and
`ModelSourceType`.

#### `contracts.py`
`BaseScanAdapter` protocol that every wrapper inherits from. Defines
`capabilities()`, `validate_config()`, and the per-framework hooks
(`run_art_scan`, `run_foolbox_scan`, etc.) that adapters can override.

#### `compatibility.py`
Per-framework `FrameworkCompatibilityProfile` records that carry package
name, import name, python requirement, known version risks, optional
capabilities, and adapter strategy. `framework_compatibility_inventory` is
the single function that probes each framework's runtime status.
`framework_runtime_specs` derives `FRAMEWORK_RUNTIME_SPECS` for
`preflight.py`. Includes `install_framework` and `install_all_frameworks`
helpers used by the `/api/install/*` endpoints.

#### `framework_registry.py`
`FRAMEWORK_SUPPORT_MATRIX`, `FRAMEWORK_CAPABILITY_FLAGS`,
`default_framework_order`, `framework_supported`. The dispatch contract
that the orchestrator consults when deciding whether a path is implemented
or planned.

### 2.2 Executors

`executors/` holds one module per framework. Each exposes a `run_*_scan`
function whose contract is: take a job record and return a dict with
`status`, `framework`, `message`, framework-specific keys, and an
`artifacts` map. Subprocess-based runners (`pyrit_runner.py`,
`textattack_runner.py`, `garak_runner.py`) live alongside their executors;
they are intentionally entry points so they can run as `-m
whitebox_scan_platform.executors.<runner>` from a fresh subprocess.

### 2.3 Reporting

`reporting/` was extracted in Task 5. It now holds:

- **`utils.py`** — small renderers shared across frameworks: `_RawHtml`,
  `_first_present`, `_resolve_mode_framework_payload`, `_html_scalar`,
  `_html_table`.
- **`normalized.py`** — the unified severity engine. Constants
  (`NORMALIZED_SEVERITY_*`), severity map, per-framework normalizers,
  HTML rendering, artefact writers.
- **`pyrit.py`**, **`garak.py`**, **`textattack.py`**, **`foolbox.py`**,
  **`art.py`** — per-framework HTML render helpers.

### 2.4 User wrappers

`user_wrappers/` is where built-in adapter implementations live. Adding a
custom adapter through the **Register Wrapper** UI panel writes a new file
into this directory and updates `data/wrappers.json`.

### 2.5 Compatibility shim

`whitebox_scan_platform/` is a tiny shim that re-exports every `sentinel.*`
module under the legacy `whitebox_scan_platform.*` namespace. This keeps
subprocess invocations like `python -m
whitebox_scan_platform.executors.textattack_runner` working without forcing
a full package rename. The `__init__.py` registers aliases at import time;
see [RELEASE_NOTES.md](RELEASE_NOTES.md) for why this exists.

### 2.6 UI

`ui/index.html` is the single-page operator console. It is intentionally a
single file — there is no separate JS/CSS asset pipeline — so deployment
is a single static drop. After the Task 9 layout pass, the document order
is:

1. Hero band
2. Create Scan Job (left wide column)
3. Right column stack: Register Wrapper → Runtime Environment → Local Service Health
4. Live Job Status (with Original + Normalized Artefacts side-by-side beneath)
5. Wrapper Capability Matrix (always-expanded full-width section)
6. Preflight
7. Terminal View (collapsible tree at the bottom)

### 2.7 Tests

`tests/` uses `pytest`. The smoke-style suites
(`test_end_to_end.py`, `test_executor_runtime.py`) require a live API and
an Ollama daemon for full coverage; the rest are pure-Python and fast.

---

## 3. Runtime data layout

`data/` is the single source of mutable state. **Do not commit anything in
here that is not explicitly tracked** (the `.gitignore` enforces this).

```
data/
├─ builtin_templates.json   # Tracked — 15 built-in templates
├─ wrappers.json            # Generated — registered wrapper index
├─ templates.json           # Generated — user-saved templates
│
├─ jobs/
│  └─ <job_id>.json         # One JSON per job. Atomic-written via storage.write_json
│
├─ job_reports/
│  └─ <job_id>/
│     └─ reports/
│        ├─ blackbox_report.html
│        ├─ blackbox_results.json
│        ├─ blackbox_run_log.txt
│        ├─ blackbox_summary_report.html
│        ├─ blackbox_summary_results.json
│        ├─ blackbox_summary_run_log.txt
│        ├─ blackbox_normalized_severity.html
│        ├─ blackbox_normalized_severity.json
│        ├─ blackbox_normalized_severity_log.txt
│        └─ <whitebox_…>     # Same set for whitebox mode when applicable
│
├─ art_runs/<job_id>/reports/    # IBM ART native artefacts
├─ foolbox_runs/<job_id>/reports/
├─ garak_runs/<job_id>/reports/
├─ pyrit_runs/<job_id>/reports/
│  └─ <NN>_<attack_type>/        # PyRIT additionally splits per attack
├─ textattack_runs/<job_id>/reports/
│
├─ smoke_runs/                   # run_full_smoke.sh outputs
├─ textattack_cache/             # HF model cache (HF_HOME)
├─ matplotlib_cache/
└─ pyrit_multimodal_smoke/       # Per-attack PyRIT multimodal fixtures
```

Why this layout: every framework writes its native artefacts into its own
`<framework>_runs/` directory, so framework upgrades can change those
formats freely without colliding with each other. The orchestrator
synthesises a normalised summary into `job_reports/<job_id>/reports/` for
cross-framework comparison.

---

## 4. The patch package

`sentinel_patch/` is a self-contained patch deliverable mirroring the
top-level files that need to ship to a deployed instance. It is here so
that deployments can pull a tarball of just the changed files instead of
the full repo. See `sentinel_patch/PATCH_README.md` for the file map.

---

## 5. What is NOT in the repo (and how to get it)

- **Hugging Face model weights.** Run `python scripts/warm_hf_cache.py`.
- **NLTK corpora.** Run `bash scripts/install_nltk_offline.sh`.
- **Ollama model files.** `ollama pull <model>` outside the repo.
- **Per-job runtime artefacts** under `data/jobs/`, `data/job_reports/`,
  `data/<framework>_runs/`, `data/smoke_runs/`. These are all regenerated
  on first use by `storage.ensure_dirs()`.
- **The venv.** Build it with `./install.sh`.

---

## 6. Where to look first when debugging

| Symptom                                          | First file to read                                         |
|--------------------------------------------------|------------------------------------------------------------|
| Server fails to start                            | `app.py` top-of-file imports + `sync_builtin_wrappers`     |
| Preflight returns unexpected blocker             | `preflight.evaluate_platform_support` and the relevant     |
|                                                  | profile in `compatibility.framework_compatibility_profiles`|
| A wrapper is missing from the UI                 | `data/wrappers.json` and `jobs.list_wrappers`              |
| Built-in template doesn't autofill correctly     | `data/builtin_templates.json` payload                       |
| Report HTML looks broken                         | `reporting/<framework>.py` or `reporting/normalized.py`    |
| Subprocess can't import `whitebox_scan_platform` | `whitebox_scan_platform/__init__.py` + `executors/<fw>_executor.py` PYTHONPATH handling |
| Atomic-write contention                          | `storage.JOB_WRITE_LOCK` / `storage.write_json`            |
| Severity rollup misclassifies                    | `reporting/normalized._build_normalized_severity_payload`  |

The `tests/` suite is the second-best reference: every guard in the code
has a unit test that captures what the guard exists for.
