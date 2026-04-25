from __future__ import annotations

from typing import Any

from whitebox_scan_platform.compatibility import attach_framework_compatibility
from whitebox_scan_platform.contracts import BaseScanAdapter


def run_art_scan(adapter: BaseScanAdapter, job_record: dict[str, Any]) -> dict[str, Any]:
    """Execute a real ART path when the adapter exposes one."""
    decisions = {
        "executor": "adapter.run_framework_scan",
        "adapter_class": adapter.__class__.__name__,
        "wrapper_id": job_record.get("wrapper_id") or "",
        "capability_boundary": "wrapper_capability_driven",
    }
    try:
        return attach_framework_compatibility(
            adapter.run_framework_scan("art", job_record),
            "art",
            job_record=job_record,
            decisions=decisions,
        )
    except NotImplementedError:
        return attach_framework_compatibility(
            {
                "status": "not_implemented",
                "framework": "art",
                "message": "Adapter did not expose a concrete ART execution path.",
            },
            "art",
            job_record=job_record,
            decisions={**decisions, "adapter_path_available": False},
        )
