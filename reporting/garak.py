"""HTML renderer for Garak attempt samples.

Extracted from executor.py during the reporting-layer split (Task 5).
Callers should import from this module, e.g.
    from sentinel.reporting.garak import _render_garak_attempt_samples_html
The old `from sentinel.executor import _render_garak_attempt_samples_html` still works via a re-export
shim in executor.py.
"""
from __future__ import annotations

import base64
import html
import json
import mimetypes
import re
from pathlib import Path
from typing import Any

from .pyrit import _html_block
from .utils import _first_present, _html_scalar, _html_table, _RawHtml


def _render_garak_attempt_samples_html(sample_bundle: dict[str, Any] | None) -> str:
    if not sample_bundle or not sample_bundle.get("samples"):
        return '<p class="muted">No Garak prompt/response samples were recorded.</p>'

    total_attempts = sample_bundle.get("total_attempts", 0)
    displayed_attempts = sample_bundle.get("displayed_attempts", 0)
    note_parts = [f"Showing {displayed_attempts} of {total_attempts} recorded Garak attempts."]
    if sample_bundle.get("json_decode_errors"):
        note_parts.append(f"Skipped {sample_bundle['json_decode_errors']} malformed JSONL lines.")
    report_path = sample_bundle.get("path")
    if report_path:
        note_parts.append(f"Source: {report_path}")

    header_html = "".join(
        f"<th>{html.escape(header)}</th>"
        for header in ["Seq", "Goal", "Trigger", "Prompt", "Response", "Detector Results"]
    )
    rows_html = []
    for sample in sample_bundle["samples"]:
        detector_results = sample.get("detector_results") or {}
        detector_text = json.dumps(detector_results, indent=2, sort_keys=True) if detector_results else "-"
        rows_html.append(
            "".join(
                [
                    "<tr>",
                    f"<td>{html.escape(str(sample.get('seq', '-')))}</td>",
                    f"<td>{_html_block(sample.get('goal'))}</td>",
                    f"<td>{_html_block(sample.get('trigger'))}</td>",
                    f"<td>{_html_block(sample.get('prompt'))}</td>",
                    f"<td>{_html_block(sample.get('output'))}</td>",
                    f"<td>{_html_block(detector_text)}</td>",
                    "</tr>",
                ]
            )
        )

    return "".join(
        [
            f"<p class='section-note'>{html.escape(' '.join(note_parts))}</p>",
            "<table>",
            f"<thead><tr>{header_html}</tr></thead>",
            "<tbody>",
            "".join(rows_html),
            "</tbody></table>",
        ]
    )
