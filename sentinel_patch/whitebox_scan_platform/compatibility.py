"""Shim: whitebox_scan_platform.compatibility -> sentinel.compatibility"""
from sentinel.compatibility import *  # noqa: F401, F403
try:
    from sentinel.compatibility import __all__  # noqa: F401
except ImportError:
    pass
