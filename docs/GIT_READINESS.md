# Git Readiness Audit

Generated as part of the final delivery pass. Captures the state of the
repository at the moment it became ready for private-remote push, and
the manual cleanup steps an operator must run before the first push.

---

## 1. Verdict

**Ready to ship.** Every required file is present, no secrets are tracked,
the source-only tree is 4.4 MB, and the new `.gitignore` covers every
runtime artifact path the orchestrator generates.

| Check                                            | Status                                 |
|--------------------------------------------------|----------------------------------------|
| Secret-pattern scan (OpenAI / AWS / GH / Slack)  | 0 hits                                 |
| Required files (34 sources + 5 docs + 5 scripts) | 34 / 34                                |
| Source-only repo size                            | 4.4 MB                                 |
| With venv + runtime caches + jobs                | 4.46 GB (intentionally untracked)      |
| `.gitignore` patterns                            | 70 (cross-platform)                    |
| LICENSE                                          | Preserved verbatim (proprietary)       |
| Brand assets                                     | Refreshed (octopus mark + banner)       |
| Documentation suite                              | Setup / Usage / Repo / Troubleshooting / Release Notes |
| Architecture diagram                             | Mermaid in HLD + SVG export             |
| End-to-end smoke                                 | 15 / 15 templates clean                 |

---

## 2. Manual cleanup before first push

### 2.1 Remove macOS metadata files (one-time)

```bash
find . -name '.DS_Store' -not -path './.git/*' -not -path './venv/*' -delete
```

Three known instances at audit time: `.DS_Store`, `docs/.DS_Store`,
`vendored/.DS_Store`. The new `.gitignore` will keep them from ever coming
back regardless of which OS the contributor is on.

### 2.2 Stop tracking anything that the new `.gitignore` covers

```bash
git rm -r --cached venv .venv .venv311 data __pycache__ .pyrit_home .art .matplotlib 2>/dev/null
git status
```

This step is only needed if the previous repo state had any of those paths
tracked. The audit is unable to distinguish "tracked but ignored" from
"never tracked"; running the command is harmless when nothing is tracked.

### 2.3 (Optional) Confirm the recently-removed failed-job records are gone

```bash
ls data/jobs                    # should NOT contain 0643edbb*, 5734521f*,
                                # e14a47b6*, fa48628f* (legacy failed runs)
python scripts/cleanup_failed_jobs.py --apply
```

Failed-job records are runtime artifacts under `data/jobs/` — already
ignored by `.gitignore`, but the cleanup script keeps the working tree
tidy.

---

## 3. What the new `.gitignore` covers

The complete set, grouped by origin:

| Category                  | Patterns                                                                                |
|---------------------------|------------------------------------------------------------------------------------------|
| Python bytecode           | `__pycache__/`, `*.py[cod]`, `*$py.class`, `*.so`, `*.pyd`                               |
| Virtual environments      | `venv/`, `.venv/`, `.venv311/`, `.venv312/`, `env/`, `ENV/`, `.env`                      |
| Build / packaging         | `build/`, `dist/`, `sdist/`, `*.egg`, `*.egg-info/`, `.eggs/`, `pip-wheel-metadata/`     |
| Test / coverage caches    | `.pytest_cache/`, `.mypy_cache/`, `.dmypy.json`, `.ruff_cache/`, `.tox/`, `.nox/`,       |
|                           | `.coverage*`, `htmlcov/`, `coverage.xml`, `nosetests.xml`, `.cache/`                     |
| IDE / editor              | `.idea/`, `.vscode/`, `*.swp`, `*.swo`, `*~`, `.spyderproject`, `.spyproject`            |
| Cross-platform metadata   | `.DS_Store`, `Thumbs.db`, `desktop.ini`                                                  |
| Logs / temp               | `*.log`, `*.tmp`                                                                         |
| Runtime job artifacts     | `data/jobs/`, `data/job_reports/`, `data/<framework>_runs/`, `data/smoke_runs/`,         |
|                           | `data/wrappers.json`                                                                     |
| Caches                    | `data/textattack_cache/`, `data/matplotlib*`, `.matplotlib/`, `.pyrit_home/`, `.art/`    |
| Demo data                 | `data/demo/` (with explicit allow-list for `textattack_smoke_samples.jsonl`)             |
| Audio binary samples      | `/rhel_art_audio_demo/samples/*.wav`                                                     |
| Garak per-run JSONL       | `garak.*.report.jsonl`                                                                   |
| Model weights             | `*.safetensors`, `*.bin`, `*.pt`, `*.pth`, `*.onnx`, `*.ckpt`                            |
| Notebook checkpoints      | `*.ipynb_checkpoints/`                                                                   |
| Compatibility shim mirror | `/whitebox_scan_platform/`                                                               |

Operator note: `data/builtin_templates.json` and
`data/demo/textattack_smoke_samples.jsonl` are explicitly **not** ignored
because they ship with the repo as the canonical built-in template list and
the smoke-test sample pack respectively.

---

## 4. Files that DO ship

```
README.md
LICENSE.txt                     # Preserved verbatim — proprietary terms
NOTICE.txt
CONTRIBUTING.md
SECURITY.md
THIRD_PARTY_COMPLIANCE.txt
GITHUB_PAGES_SETUP.txt
PRIVATE_GITHUB_PUBLISHING.txt

install.sh
pyproject.toml
requirements*.txt
run.py

# Top-level package
__init__.py
app.py
schemas.py
storage.py
contracts.py
compatibility.py
framework_registry.py
executor.py                     # 1,552-line facade (post Task 7 split)
templates.py
preflight.py
jobs.py

# Subpackages
executors/                      # 5 framework executors + 3 runners
reporting/                      # utils, normalized, art, foolbox, garak, pyrit, textattack
user_wrappers/                  # 6 built-in adapters
whitebox_scan_platform/         # legacy import shim

# UI
ui/index.html

# Scripts (operator helpers)
scripts/run_full_smoke.sh
scripts/smoke_all_builtins.py
scripts/warm_hf_cache.py
scripts/install_nltk_offline.sh
scripts/cleanup_failed_jobs.py
scripts/refresh_product_screenshot.sh
scripts/add_repo_collaborator.sh
scripts/update_git.sh

# Documentation
docs/architecture_hld.md
docs/normalized_severity_framework.md
docs/tool_compatibility_layer.md
docs/deployment_runtime_checklist.md
docs/deployment_dependency_policy.md
docs/pyrit_multimodal_smoke_matrix.md
docs/textattack_smoke_matrix.md
docs/SETUP.md
docs/USAGE.md
docs/REPO_STRUCTURE.md
docs/TROUBLESHOOTING.md
docs/RELEASE_NOTES.md
docs/GIT_READINESS.md           # this file
docs/index.html

# Brand assets
docs/images/sentinel-octopus-logo.svg          # 64x64 mark
docs/images/sentinel-orchestrator-logo.svg     # 960x320 banner
docs/images/architecture.svg                   # Architecture diagram
docs/images/product-screenshot-current.png     # UI screenshot
docs/images/product-screenshot.json            # Cache-bust metadata

# Test suite
tests/test_*.py

# Data that ships
data/builtin_templates.json                    # 15 built-in templates (Task 6)
data/demo/textattack_smoke_samples.jsonl       # Tiny smoke pack

# Patch deliverable
sentinel_patch/

# Self-tests / smoke fixtures kept for reference
rhel_art_audio_demo/
```

---

## 5. Recommended first-push sequence

```bash
cd /Users/macmacmac/Documents/sentinel

# 1. Cleanup
find . -name '.DS_Store' -not -path './.git/*' -not -path './venv/*' -delete

# 2. Confirm working tree
git status

# 3. Stage everything that should ship (the .gitignore protects the rest)
git add -A

# 4. Inspect what's staged BEFORE committing — last gate
git status --short | head -60

# 5. Commit
git commit -m "Sentinel Defense: refactor, polish, docs"

# 6. Push to your private remote
git remote -v                         # confirm origin
git push origin main                  # or your default branch
```

If `git status` shows surprises (anything under `data/jobs/`, `venv/`,
caches, etc.), stop, review the `.gitignore`, and rerun.

---

## 6. Out of scope (intentionally)

- **No CI/CD pipeline** — each environment runs the smoke locally via
  `scripts/run_full_smoke.sh`. A `.github/workflows/` pipeline would be a
  reasonable next addition but was not part of this delivery.
- **No remote push** — the user explicitly asked for "prepare only". The
  remote configuration and push are the operator's call.
- **No license rewrite** — the existing `LICENSE.txt` is preserved
  verbatim. If you want different terms, replace its content but keep the
  filename so existing references don't break.

---

## 7. Brand asset usage

- **`docs/images/sentinel-octopus-logo.svg`** — 64×64 square mark used in
  the UI hero (inlined as SVG in `ui/index.html` so no static-file route is
  needed). Standalone file kept for any external slide deck / packaging
  use.
- **`docs/images/sentinel-orchestrator-logo.svg`** — 960×320 banner
  combining the octopus + the new wordmark + tagline strip + copyright.
  Referenced from `README.md` as the project's marquee image.
- **`docs/images/architecture.svg`** — companion to the mermaid diagram in
  `docs/architecture_hld.md`. Embed this in slide decks where the
  mermaid won't render.

All three carry a `<metadata>Copyright (c) 2026 Bharath Srinivasan…</metadata>`
block and are designed within the existing palette tokens (no new colors
introduced).
