"""
whitebox_scan_platform — compatibility shim for Sentinel Adversarial Orchestrator.

The real package lives at the sentinel root. This shim registers all
sentinel.* modules under the whitebox_scan_platform.* namespace so that:
  - subprocess calls: python -m whitebox_scan_platform.executors.garak_runner
  - absolute imports:  from whitebox_scan_platform.contracts import BaseScanAdapter
both resolve correctly regardless of how the project root is named on disk.
"""
from __future__ import annotations

import importlib
import importlib.util
import sys
import types
from pathlib import Path

_HERE = Path(__file__).resolve().parent          # .../sentinel/whitebox_scan_platform
_ROOT = _HERE.parent                              # .../sentinel

def _bootstrap_aliases() -> None:
    # Ensure sentinel root is importable as the primary package
    if "sentinel" not in sys.modules:
        spec = importlib.util.spec_from_file_location("sentinel", _ROOT / "__init__.py",
               submodule_search_locations=[str(_ROOT)])
        if spec and spec.loader:
            mod = importlib.util.module_from_spec(spec)
            sys.modules["sentinel"] = mod
            spec.loader.exec_module(mod)  # type: ignore[union-attr]

    # Mirror every already-loaded sentinel.* into whitebox_scan_platform.*
    for name, mod in list(sys.modules.items()):
        if name == "sentinel" or name.startswith("sentinel."):
            alias = "whitebox_scan_platform" + name[len("sentinel"):]
            sys.modules.setdefault(alias, mod)

_bootstrap_aliases()
