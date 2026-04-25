"""Shim: whitebox_scan_platform.executors.garak_runner -> sentinel.executors.garak_runner"""
from __future__ import annotations
import runpy
import sys

# Re-export everything from the real module so import * works
from sentinel.executors.garak_runner import *  # noqa: F401, F403
try:
    from sentinel.executors.garak_runner import __all__  # noqa: F401
except ImportError:
    pass

if __name__ == "__main__":
    runpy.run_module("sentinel.executors.garak_runner", run_name="__main__", alter_sys=True)
