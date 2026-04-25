"""Shim: whitebox_scan_platform.schemas -> sentinel.schemas"""
from sentinel.schemas import *  # noqa: F401, F403
try:
    from sentinel.schemas import __all__  # noqa: F401
except ImportError:
    pass
