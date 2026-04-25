"""Shim: whitebox_scan_platform.executor -> sentinel.executor"""
from sentinel.executor import *  # noqa: F401, F403
try:
    from sentinel.executor import __all__  # noqa: F401
except ImportError:
    pass
