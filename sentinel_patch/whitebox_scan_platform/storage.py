"""Shim: whitebox_scan_platform.storage -> sentinel.storage"""
from sentinel.storage import *  # noqa: F401, F403
try:
    from sentinel.storage import __all__  # noqa: F401
except ImportError:
    pass
