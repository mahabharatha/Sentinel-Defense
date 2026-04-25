# Sentinel Adversarial Orchestrator — Patch

## Files and where they go in ~/Documents/sentinel/

| File | Destination |
|------|-------------|
| `run.py` | `sentinel/run.py` (new) |
| `app.py` | `sentinel/app.py` (replace) |
| `compatibility.py` | `sentinel/compatibility.py` (replace) |
| `requirements.txt` | `sentinel/requirements.txt` (replace) |
| `requirements-core.txt` | `sentinel/requirements-core.txt` (new) |
| `index.html` | `sentinel/ui/index.html` (replace) |
| `whitebox_scan_platform/` | `sentinel/whitebox_scan_platform/` (new folder — entire folder) |

## What changed

### Broken scans fixed
All scans failed because subprocess calls used `python -m whitebox_scan_platform.executors.garak_runner`
but no `whitebox_scan_platform` package existed on disk. The new `whitebox_scan_platform/` shim package
maps all imports and subprocess `-m` calls to the real `sentinel.*` modules.

### Version independence
- `requirements.txt`: upper version caps removed from all adversarial tools (`foolbox<4`, `garak<1`, `pyrit<1`, `textattack<1` all removed)
- `compatibility.py`: runtime feature probing replaces version number comparisons; `FRAMEWORK_PACKAGE_SPECS` has only minimum versions

### One-click install
- New API endpoints: `POST /api/install/{framework}`, `POST /api/install`, `GET /api/install/status`
- UI: Framework Runtime Matrix has per-framework Install/Upgrade buttons and "Install / Upgrade All" button

## Start the server (new way)
```bash
cd ~/Documents/sentinel
source venv/bin/activate
python run.py
```

## Adding a new adversarial tool
1. Add entry to `FRAMEWORK_PACKAGE_SPECS` in `compatibility.py`
2. Add `framework_compatibility_profiles()` entry in `compatibility.py`
3. Add `executors/newtool_executor.py` and `executors/newtool_runner.py`
4. Add entry to `framework_registry.py`
5. Add shim stub `whitebox_scan_platform/executors/newtool_executor.py` (copy any existing stub, change module name)
