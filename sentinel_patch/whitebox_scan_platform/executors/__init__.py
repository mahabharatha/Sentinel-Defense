"""Shim: whitebox_scan_platform.executors -> sentinel.executors"""
from __future__ import annotations
import importlib, sys

def __getattr__(name: str):
    mod = importlib.import_module(f"sentinel.executors.{name}")
    sys.modules[f"whitebox_scan_platform.executors.{name}"] = mod
    return mod
