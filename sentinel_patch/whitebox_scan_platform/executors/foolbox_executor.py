"""Shim: whitebox_scan_platform.executors.foolbox_executor -> sentinel.executors.foolbox_executor"""
from __future__ import annotations
import runpy
import sys

# Re-export everything from the real module so import * works
from sentinel.executors.foolbox_executor import *  # noqa: F401, F403
try:
    from sentinel.executors.foolbox_executor import __all__  # noqa: F401
except ImportError:
    pass

if __name__ == "__main__":
    runpy.run_module("sentinel.executors.foolbox_executor", run_name="__main__", alter_sys=True)
