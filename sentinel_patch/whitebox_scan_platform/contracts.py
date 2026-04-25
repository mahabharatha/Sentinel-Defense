"""Shim: whitebox_scan_platform.contracts -> sentinel.contracts"""
from sentinel.contracts import *  # noqa: F401, F403
try:
    from sentinel.contracts import __all__  # noqa: F401
except ImportError:
    pass
