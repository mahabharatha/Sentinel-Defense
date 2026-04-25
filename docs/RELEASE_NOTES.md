# Sentinel Adversarial Orchestrator — Release Notes

This document is the canonical changelog for the orchestrator. It is
organized around the consolidated refactor plan (Phases 1–6 of the
non-runtime plan plus the post-refactor enhancements) rather than calendar
versions, because the project ships as a private deliverable rather than a
versioned package. Every section maps a logical change to the file(s) it
touches and to the principle from the design ethos that motivated it.

> **Conventions.** Each entry reads `Task ID — Title`. The diff impact is
> summarized as `Files changed`, `Lines added/removed`, and `Risk`. The
> "Migration notes" subsection lists the actions an operator needs to take
> when pulling the change.

---

## Highlights of the current release

| Theme                          | What changed                                                                                       |
|--------------------------------|----------------------------------------------------------------------------------------------------|
| Modular architecture           | `executor.py` split into `templates.py`, `preflight.py`, `jobs.py`, and a `reporting/` subpackage. Facade preserves every existing import. |
| Reporting subpackage           | Severity normalization, per-framework renderers, and the unified verdict moved out of `executor.py`. |
| Atomic, race-free writes       | `storage.JOB_WRITE_LOCK` + tempfile + os.replace + fsync; `reconcile_job_statuses` holds the lock. |
| Collision-resistant IDs        | Templates and jobs use full `uuid4().hex` (32 chars).                                              |
| Cached wrapper sync            | `sync_builtin_wrappers` results are cached and invalidated on `register_wrapper`.                  |
| Version-aware wrapper rows     | `WrapperInfo.installed_versions` per framework, plus `installed_version` scalar.                   |
| One-click installer            | `install.sh` (idempotent), with `--core`, `--force`, `--skip-data`.                                |
| One-shot smoke                 | `scripts/run_full_smoke.sh` runs all 15 templates end-to-end and validates each report.            |
| Demo assets restored           | `data/demo/ocr_sample.png`, `rhel_art_audio_demo/samples/demo_tone.wav` regenerated.               |
| HF + NLTK cache warming        | `scripts/warm_hf_cache.py` (HF + masked LM + NLTK with SSL repair), `scripts/install_nltk_offline.sh`. |
| UI: layout reorder             | Live Job Status under Create Scan Job; Original/Normalized side-by-side; Terminal View at bottom.  |
| UI: world-class polish         | Typography, elevation, hover/focus states, status pills with pulse animation, custom scrollbars.   |
| Right-column stack             | Register Wrapper (collapsed) + Runtime Environment + Local Service Health share the right column. |
| Local Service Health chips     | Each loaded model rendered as its own monospaced chip on its own line.                             |
| Documentation suite            | `SETUP.md`, `USAGE.md`, `REPO_STRUCTURE.md`, `TROUBLESHOOTING.md`, `RELEASE_NOTES.md`, refreshed   |
|                                | architecture HLD with mermaid diagram.                                                             |
| Rebrand                        | "Sentinel RedTeam Console" → "Sentinel Adversarial Orchestrator" across every user-visible string.|
| API naming                     | "FastAPI" replaced with "API" in docs/comments. Runtime imports preserved.                         |

---

## Phase 1 — API correctness

### Task 1 — Version column fix

**Symptom.** The Wrapper Capability Matrix's "Version" column rendered as
an empty cell or a stale string. Multi-framework wrappers had no per-
framework version visibility.

**Change.**

- `schemas.WrapperInfo` gained `installed_versions: dict[str, str]` and a
  convenience scalar `installed_version: str`.
- `executor.framework_runtime_inventory()` now promotes
  `installed_version`, `minimum_version`, and `version_ok` to the top
  level of every framework entry.
- `jobs.list_wrappers()` enriches each wrapper record with a per-framework
  `installed_versions` map plus the scalar.

**Files changed.** `schemas.py`, `executor.py`, `jobs.py` (post-refactor).

**Risk.** Low. Additive schema fields; existing consumers ignore them.

**Migration notes.** None. Refresh the UI; the Version column will
populate automatically.

---

## Phase 3 — Data hygiene

### Task 4 — Clean failed jobs from `data/jobs/`

**Symptom.** `data/jobs/` accumulated 4+ records from runs that errored at
startup with `Wrapper '<name>' must inherit from BaseScanAdapter` and had
no useful evidence.

**Change.** Added `scripts/cleanup_failed_jobs.py`. The script reads every
`data/jobs/*.json`, treats `status="failed"` (and unknown statuses with no
result and non-empty errors) as eligible for deletion, and removes both
the JSON and any matching `data/job_reports/<id>/` directory. Defaults to
dry-run.

**Files changed.** `scripts/cleanup_failed_jobs.py` (new).

**Risk.** Operator-controlled. Default is dry-run; the destructive flag is
`--apply`.

**Migration notes.**

```bash
python scripts/cleanup_failed_jobs.py            # dry-run; review
python scripts/cleanup_failed_jobs.py --apply    # delete
```

---

## Phase 4 — Architectural refactor

### Task 5 — Reporting layer extracted to `sentinel/reporting/`

**Motivation.** `executor.py` carried ~1,300 lines of severity
normalization, per-framework HTML rendering, and template-style helpers
that had nothing to do with orchestration.

**Change.** New `reporting/` subpackage with seven modules:

- `reporting/utils.py` — `_RawHtml`, `_first_present`,
  `_resolve_mode_framework_payload`, `_html_scalar`, `_html_table`.
- `reporting/normalized.py` — severity normalization (Foolbox, ART, Garak,
  PyRIT, TextAttack), HTML rendering, artefact writers.
- `reporting/pyrit.py`, `reporting/garak.py`, `reporting/textattack.py`,
  `reporting/foolbox.py`, `reporting/art.py` — framework-specific
  renderers.

Every previously-`from sentinel.executor import _render_*` import keeps
working through re-export shims at the bottom of `executor.py`.

**Files changed.** 7 new files under `reporting/`. `executor.py` shrank by
~1,000 lines.

**Risk.** Low. Every public symbol is still importable from
`sentinel.executor`.

**Migration notes.** None. Existing tests use the old imports and
continue to pass.

---

### Task 7 — `executor.py` split

**Motivation.** `executor.py` was 4,635 lines (the largest file in the
repo), hosting orchestration, template CRUD, runtime probing, job
lifecycle, wrapper management, and the reporting layer that Task 5 also
extracted from. This was the next safe split target identified in the
prior architecture HLD.

**Change.**

- New top-level modules:
  - **`templates.py`** (~5.9 KB, 10 defs) — template CRUD:
    `sync_builtin_templates`, `list_templates`, `save_template`,
    `create_template`, `update_template`, `delete_template`,
    `export_template`, `import_template`. Loads `BUILTIN_TEMPLATES` from
    `data/builtin_templates.json` at module import time.
  - **`preflight.py`** (~21.7 KB, 15 defs) — runtime checks:
    `python_runtime_summary`, local Ollama detection,
    `evaluate_platform_support`, `evaluate_wrapper_compatibility`,
    `report_expectations`, `evaluate_runtime_readiness`,
    `build_preflight`. Holds `FRAMEWORK_RUNTIME_SPECS` as a single source
    of truth derived from `compatibility.framework_compatibility_profiles`.
  - **`jobs.py`** (~29.7 KB, 28 defs) — wrapper + job lifecycle:
    `register_wrapper`, `sync_builtin_wrappers`, `list_wrappers`,
    `build_execution_plan`, `create_job`, `run_job`, `list_jobs`,
    `reconcile_job_statuses`, `build_job_terminal_view`,
    `collect_job_artifacts`. Also home of the wrapper cache.

- `executor.py` shrank to **1,552 lines** (~66% reduction). It is now a
  facade that re-exports every public symbol so existing imports such as
  `from sentinel.executor import build_preflight` keep working unchanged.

- Circular imports avoided by placing the re-export shim at the **bottom**
  of `executor.py` and by using lazy `from .executor import …` calls
  inside split-module function bodies for any executor-resident symbol
  (e.g. `BUILTIN_WRAPPERS`, `_mode_reports_dir`, `execute_job_record`).

**Files changed.** `executor.py` (4,635 → 1,552 lines), new modules
`templates.py`, `preflight.py`, `jobs.py`.

**Risk.** Medium during the change, low after. AST-validated end-to-end:
all 30 distinct repo-wide imports of `from sentinel.executor import …`
still resolve; all 26 distinct imports across the 8 test files still
resolve.

**Migration notes.**

1. Pull the latest.
2. Clear `__pycache__/` to drop stale bytecode that may still embed old
   import paths:
   ```bash
   find . -type d -name __pycache__ -not -path './venv/*' -exec rm -rf {} +
   ```
3. Restart the server.

---

### Task 6 — `BUILTIN_TEMPLATES` moved to JSON

**Motivation.** The 15 built-in templates were defined as a long Python
literal at the bottom of `executor.py`, mixing data with code.

**Change.** Extracted into `data/builtin_templates.json` (22.7 KB, 15
templates). `templates._load_builtin_templates()` reads this file at
module import time and exposes `BUILTIN_TEMPLATES` as a normal module-
level constant.

**Files changed.** `data/builtin_templates.json` (new). `templates.py`
(loader + constant).

**Risk.** Low. The schema is identical; the only change is the storage
location.

**Migration notes.** None. The file is tracked in git.

---

### Task 11 — Template / job ID collision fix

**Motivation.** `templates.create_template()` and `jobs.create_job()`
generated IDs as `uuid.uuid4().hex[:12]`. Truncating to 12 hex chars gives
a 48-bit ID space; on a long-lived install with thousands of jobs this is
not safe against collision.

**Change.** Both functions now use `uuid.uuid4().hex` (32 chars / 128
bits). Existing 12-char IDs on disk continue to work because lookup is by
filename equality, not by structure.

**Files changed.** `jobs.py`, `templates.py`. Static check confirms
`uuid4().hex[:12]` no longer appears in any module.

**Risk.** Low. Backward-compatible.

**Migration notes.** None.

---

## Phase 5 — Performance / reliability

### Task 8 — Wrapper cache

**Motivation.** `sync_builtin_wrappers()` was called on every UI refresh
and every list endpoint. Each call ran `importlib.util.spec_from_file_location`
+ `exec_module` for every built-in wrapper to resolve its capabilities — a
small but accumulating cost that surfaced as multi-second UI refreshes.

**Change.** `jobs.py` now keeps a module-level `_WRAPPER_CACHE` guarded by
`_WRAPPER_CACHE_LOCK`. `sync_builtin_wrappers(force=True)` invalidates it.
`register_wrapper` calls `_invalidate_wrapper_cache()` after persisting a
new record so the next list pulls fresh data.

**Files changed.** `jobs.py`.

**Risk.** Low. Cache is invalidated on every state-changing path.

**Migration notes.** None.

---

### Task 10 — Job status race fix

**Motivation.** Concurrent `save_job` calls (e.g. background runner
updating status while a UI refresh's `reconcile_job_statuses` ran) could
overwrite each other, leaving a job stuck in `running` or losing its
`result` on disk.

**Change.**

- `storage.JOB_WRITE_LOCK = threading.RLock()` at module scope. Allows
  re-entry from `reconcile_job_statuses` which calls `save_job` inside
  the same lock.
- `storage.write_json` is atomic: writes to a sibling temp file via
  `tempfile.mkstemp`, fsyncs, then `os.replace`. Best-effort fsync (some
  tmpfs filesystems on CI don't support it) so the path is robust.
- `storage.save_job` acquires `JOB_WRITE_LOCK` before writing.
- `executor.reconcile_job_statuses` (re-exported from `jobs.py`) holds
  `JOB_WRITE_LOCK` across the entire read-modify-write loop, so an
  in-flight `save_job` by the runner can't race with a reconciliation
  pass.

**Files changed.** `storage.py`, `executor.py` (now `jobs.py`).

**Risk.** Low. RLock allows the natural re-entry pattern; atomic writes
are best-effort and fall back gracefully.

**Migration notes.** None.

---

## Phase 6 — Validation

### Task 4 (validation) — End-to-end smoke driver

**Change.** Added the `scripts/smoke_all_builtins.py` driver and the
`scripts/run_full_smoke.sh` one-shot runner. The driver:

1. Loads every template from `data/builtin_templates.json`.
2. POSTs each to `/api/scans` and polls `/api/scans/{id}` every 3 s with
   a 15-second heartbeat in the log.
3. Validates each completed report: status, errors, mode artefacts,
   normalized severity payload (`overall_normalized_verdict`,
   `normalized_findings`), JSON parse success, run-log error markers,
   HTML report length / error panels, framework-run status.

The shell runner kills any prior server, clears `__pycache__`, starts a
fresh server in the background, waits up to 60 s for `/api/options` to
respond, runs the driver with `PYTHONUNBUFFERED=1` so the tee pipe
streams output in real time, and stops the server on exit (via `trap`).

Filtering: `SENTINEL_ONLY=11`, `SENTINEL_SKIP=7,13,14,15`,
`SENTINEL_TIMEOUT=1800`, `SENTINEL_EXTRA="--dry-preflight"`.

**Outcome.** First clean run: **15 / 15 templates passed** in ~3.5 minutes.

**Files changed.** `scripts/smoke_all_builtins.py`,
`scripts/run_full_smoke.sh` (both new).

**Risk.** None — pure tooling.

---

## Post-refactor enhancements

### Task — Demo assets restored

**Symptom.** Templates 2/3/5/6 (vision/OCR) failed with `FileNotFoundError`;
templates 1/4 (audio) silently completed with empty summaries.

**Cause.** `data/demo/ocr_sample.png` and
`rhel_art_audio_demo/samples/demo_tone.wav` were referenced by 6 of the 15
built-in templates but never shipped.

**Fix.** Generated both as deterministic, valid binary assets:

- `data/demo/ocr_sample.png` — 64×64 RGB PNG with a synthetic 3-bar +
  baseline pattern (146 bytes, valid IHDR/IDAT/IEND).
- `rhel_art_audio_demo/samples/demo_tone.wav` — 1 second, 16 kHz mono
  16-bit PCM, 440 Hz sine tone (32 KB, parseable via stdlib `wave`).

The generation logic is reproducible inline in TROUBLESHOOTING.md §3.1.

---

### Task — `run.py` CWD fix

**Symptom.** Relative paths in job configurations (e.g.
`sample_path="data/demo/ocr_sample.png"`) failed with `FileNotFoundError`
even after the file was generated.

**Cause.** `run.py` previously did `os.chdir(ROOT.parent)` so uvicorn could
import `sentinel.app:app` from the parent directory. With CWD at the
parent, `data/demo/...` resolved to a path *outside* the repo.

**Fix.** `run.py` now does `os.chdir(ROOT)` (CWD at repo root) and adds
the parent to `sys.path` so the `sentinel.app:app` import path still works.

---

### Task — PyRIT subprocess `PYTHONPATH` fix

**Symptom.** PyRIT runs failed with
`ModuleNotFoundError: No module named 'whitebox_scan_platform'`.

**Cause.** PyRIT subprocess uses `cwd=attack_dir` (a deep folder under
`data/pyrit_runs/<job_id>/<NN>_<attack_type>/`), which doesn't put the
repo root on `sys.path`. The TextAttack path worked because its subprocess
runs with `cwd=repo_root` — the difference was never reconciled.

**Fix.** `executors/pyrit_executor.py` now prepends the repo root to
`PYTHONPATH` in the subprocess env so `python -m
whitebox_scan_platform.executors.pyrit_runner` can resolve the shim
package regardless of the CWD.

---

### Task — TextAttack BAE cache

**Symptom.** TextAttack BAE recipe failed offline with
`LocalEntryNotFoundError`.

**Cause.** BAE loads `bert-base-uncased` via `WordSwapMaskedLM` for its
masked-language-model transformation. The cache warmer only had the
classifier (`distilbert-base-uncased-finetuned-sst-2-english`).

**Fix.** `scripts/warm_hf_cache.py` adds `TEXT_MASKED_LM_MODELS` and a
`warm_masked_lm` function that downloads `bert-base-uncased` via
`AutoModelForMaskedLM`.

---

### Task — NLTK SSL workaround

**Symptom.** `nltk.download(...)` failed with
`CERTIFICATE_VERIFY_FAILED` on stock macOS Python.

**Cause.** Framework Python on macOS doesn't ship a CA bundle that
NLTK's downloader can find through the stdlib SSL stack.

**Fix (1).** `scripts/warm_hf_cache.py`'s `warm_nltk` function:

- Sets `SSL_CERT_FILE` and `REQUESTS_CA_BUNDLE` from `certifi.where()`.
- Builds an `ssl.create_default_context(cafile=…)` and installs it as the
  global urllib opener.
- Falls back to an unverified context only as a last-resort retry.

**Fix (2).** `scripts/install_nltk_offline.sh` — a curl-based installer
that uses the OS certificate store directly. Recommended path on locked-
down macOS / Windows hosts.

---

### Task — Smoke validator hardening

**Symptom.** Smoke validator flagged every run with
`missing severity_counts/findings keys` and Garak with
`ERROR:` even though both were healthy.

**Cause.** Initial validator looked for the wrong keys, and substring-
matched `ERROR:` which matched the JSON-encoded
`"target_error_marker": "GARAK_TARGET_ERROR:"` config string in the synthesized
log.

**Fix.**

- Validator now checks the real payload keys
  (`overall_normalized_verdict`, `normalized_findings`, `framework`,
  `scan_mode`).
- Run-log scanner uses a line-aware helper `_log_has_real_error()` that
  skips lines starting/ending with `"` (JSON-value heuristic) and only
  matches `Traceback (most recent call last):`, `Uncaught exception`,
  `FATAL:`, `AssertionError:`.

---

### Task — UI structure pass

**Change.** Comprehensive layout pass on `ui/index.html`:

- Live Job Status moved directly under Create Scan Job.
- Original Artefacts (left) and Normalized Artefacts (right) nested
  side-by-side inside Live Job Status; collapses to single column under
  1100 px viewport.
- Wrapper Capability Matrix kept as an always-visible full-width section.
- Preflight kept full-width below Matrix.
- Terminal View moved to the bottom and wrapped in a `<details>` (closed
  by default). The synthesized log is now parsed into a tree of
  collapsible sections (Terminal Meta / Header / Mode: blackbox /
  Mode: whitebox / Framework: <name> / Notes / Errors / Artifact Log).
  The hidden raw `<pre id="terminalOut">` is preserved so Copy Terminal
  yields the unparsed transcript.
- Register Wrapper compacted to a `<details>` (closed by default) inside
  a new right-column stack.
- Right-column stack adds Runtime Environment + Local Service Health
  cards directly under Register Wrapper, filling the gap that used to
  appear when Register Wrapper was shorter than Create Scan Job.
- Local Service Health now renders each loaded model as its own
  monospaced `.service-model` chip on its own line.

**Files changed.** `ui/index.html`.

**Risk.** Cosmetic. Every form ID, onclick handler, and JS callback path
preserved. HTML parser balance verified empty-stack zero-error.

---

### Task — UI polish layer

**Change.** Comprehensive typography + interaction pass with no palette
changes:

- Font stack: Inter → SF Pro Display → SF Pro Text → Avenir Next →
  system, with `font-feature-settings: "ss01" "cv11" "cv01"` and
  `letter-spacing: -0.005em`.
- Heading hierarchy: h1 800/-0.025em, h2 700/-0.018em, h3 600/-0.012em.
- Labels: 11 px, weight 700, 0.06em letter-spacing, uppercase eyebrow.
- Cards: 220 ms cubic-bezier hover lift, deeper shadow on hover, refined
  accent stripe gradient.
- Hero h1 + stat values: gradient text fill (white → light cyan).
- Tables: sticky frosted headers (`backdrop-filter: blur(6px)`), zebra
  striping, hover row tinted with `accent-soft`, tabular numerics.
- Status pills (`.status-pill`): semantic palette colors, leading dot,
  `pulse` animation on `running`.
- Custom scrollbars (10 px, accent-tinted thumb).
- `:focus-visible` outline + 6 px `accent-soft` ring on buttons.
- Inline `<code>` / `<kbd>` chip styling (JetBrains Mono, subtle border).
- Print stylesheet baseline.

All changes use existing palette tokens (`--accent`, `--ink`,
`--success`, etc.); no new color values were introduced.

---

### Task — Rebrand

**Change.** "Sentinel RedTeam Console" / "Sentinel Red Team Console" →
"Sentinel Adversarial Orchestrator" across every user-visible string in:
README, app.py title/description, run.py launcher banner, ui/index.html,
docs/index.html, docs/*.md, executor.py + reporting/normalized.py + 6
framework executor/runner CSS comments, executors/__init__.py docstring,
whitebox_scan_platform/__init__.py docstring, sentinel_architecture.svg
title, tests/test_end_to_end.py home-page assertion, all 5 sentinel_patch
files.

Python package names (`sentinel/`, `whitebox_scan_platform/`) intentionally
preserved — imports continue to work without code changes.

---

### Task — API naming cleanup

**Change.** "FastAPI" replaced with "API" in 5 documentation files
(architecture_hld.md, tool_compatibility_layer.md,
deployment_runtime_checklist.md, README.md (×2), docs/index.html chip).
Runtime `from fastapi import` statements and `app = FastAPI(...)`
constructor calls are framework usage, not branding, and were preserved.

---

### Task — Documentation suite

**New files.**

- `docs/SETUP.md` — exhaustive install reference (this file's sibling).
- `docs/USAGE.md` — operator walkthrough (UI tour, API reference, common
  workflows).
- `docs/REPO_STRUCTURE.md` — annotated directory tree.
- `docs/TROUBLESHOOTING.md` — symptom-to-cause-to-fix lookup.
- `docs/RELEASE_NOTES.md` — this file.

**Refreshed.**

- `docs/architecture_hld.md` — updated mermaid diagram showing the
  post-Task-7 module split, plus a "Design Ethos Mapping" section that
  ties each refactor task to its corresponding principle.
- `README.md` — adopted the new brand and links to all the new docs.

---

## How to read a release notes entry

Every entry in this document follows the same shape:

1. **Symptom** (or **Motivation** for additive changes) — what the user-
   facing behaviour was before.
2. **Cause** — the file / line / contract that produced the symptom.
3. **Fix** (or **Change**) — the concrete diff, with file paths.
4. **Risk** — likelihood of regression or operator action.
5. **Migration notes** — exact commands to apply the change to a
   running install.

Future entries should follow the same shape so the document stays useful
as the grep target it is designed to be.
