"""Reporting-layer utilities: _RawHtml marker, small HTML helpers, payload resolver.

Extracted from executor.py during the reporting-layer split (Task 5).
Callers should import from this module, e.g.
    from sentinel.reporting.utils import _RawHtml
The old `from sentinel.executor import _RawHtml` still works via a re-export
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


class _RawHtml(str):
    """Marks trusted HTML fragments that should not be escaped again."""


def _first_present(*values: Any) -> Any:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str):
            if value.strip():
                return value
            continue
        return value
    return None


def _resolve_mode_framework_payload(full_result: dict[str, Any], mode_result: dict[str, Any]) -> dict[str, Any]:
    framework_runs = full_result.get("framework_runs") or {}
    framework_name = str(mode_result.get("framework") or "").strip()
    payload = framework_runs.get(framework_name) if framework_name else None
    if isinstance(payload, dict):
        return payload
    if len(framework_runs) == 1:
        only_payload = next(iter(framework_runs.values()))
        if isinstance(only_payload, dict):
            return only_payload
    return {}


def _html_scalar(value: Any) -> str:
    if value is None:
        return '<span class="muted">-</span>'
    if isinstance(value, _RawHtml):
        return str(value)
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, (list, tuple, set)):
        items = [str(item) for item in value if str(item).strip()]
        return html.escape(", ".join(items)) if items else '<span class="muted">-</span>'
    if isinstance(value, dict):
        return f"<code>{html.escape(json.dumps(value, sort_keys=True))}</code>"
    text = str(value).strip()
    return html.escape(text) if text else '<span class="muted">-</span>'


def _html_table(headers: list[str], rows: list[list[Any]]) -> str:
    if not rows:
        return '<p class="muted">No data recorded.</p>'
    head = "".join(f"<th>{html.escape(header)}</th>" for header in headers)
    body_rows = []
    for row in rows:
        cells = "".join(f"<td>{_html_scalar(cell)}</td>" for cell in row)
        body_rows.append(f"<tr>{cells}</tr>")
    return "<table><thead><tr>" + head + "</tr></thead><tbody>" + "".join(body_rows) + "</tbody></table>"
