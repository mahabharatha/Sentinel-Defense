"""Shim: whitebox_scan_platform.executors.art_executor -> sentinel.executors.art_executor"""
from __future__ import annotations
import runpy
import sys

# Re-export everything from the real module so import * works
from sentinel.executors.art_executor import *  # noqa: F401, F403
try:
    from sentinel.executors.art_executor import __all__  # noqa: F401
except ImportError:
    pass

if __name__ == "__main__":
    runpy.run_module("sentinel.executors.art_executor", run_name="__main__", alter_sys=True)
