"""Shim: whitebox_scan_platform.framework_registry -> sentinel.framework_registry"""
from sentinel.framework_registry import *  # noqa: F401, F403
try:
    from sentinel.framework_registry import __all__  # noqa: F401
except ImportError:
    pass
