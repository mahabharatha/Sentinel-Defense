"""Template CRUD — built-in template sync, create/update/delete/import/export.

Extracted from executor.py during the responsibility split (Task 7). Call sites
that still import from sentinel.executor keep working via a re-export shim at
the bottom of executor.py.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from .schemas import ScanJobCreate
from .storage import (
    BASE_DIR,
    TEMPLATE_INDEX,
    ensure_dirs,
    load_template_index,
    read_json,
    save_template_index,
)


def now_utc() -> str:
    # Local copy to avoid a circular import of executor.now_utc during module load.
    from time import gmtime, strftime
    return strftime("%Y-%m-%dT%H:%M:%SZ", gmtime())


def model_dump(payload: Any) -> dict[str, Any]:
    if hasattr(payload, "model_dump"):
        return payload.model_dump()
    if hasattr(payload, "dict"):
        return payload.dict()
    if isinstance(payload, dict):
        return payload
    raise TypeError(f"Cannot dump payload of type {type(payload).__name__}")


# Backward-compatible aliases for any caller that already uses the
# underscore-prefixed form.
_now_utc = now_utc
_dump = model_dump


# Task 6: BUILTIN_TEMPLATES now lives in data/builtin_templates.json. Load once
# at module import; fall back to an empty list if the file is absent.
_BUILTIN_TEMPLATES_PATH = BASE_DIR / "data" / "builtin_templates.json"


def _load_builtin_templates() -> list[dict[str, Any]]:
    if not _BUILTIN_TEMPLATES_PATH.exists():
        return []
    try:
        data = json.loads(_BUILTIN_TEMPLATES_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        inner = data.get("templates")
        if isinstance(inner, list):
            return inner
    return []


BUILTIN_TEMPLATES = _load_builtin_templates()


def sync_builtin_templates() -> list[dict[str, Any]]:
    ensure_dirs()
    index = load_template_index()
    existing_templates = index.get("templates", [])
    non_builtin_templates = [row for row in existing_templates if not bool(row.get("builtin"))]
    existing_builtin_map = {row["template_id"]: row for row in existing_templates if bool(row.get("builtin"))}
    templates = list(non_builtin_templates)

    for template in BUILTIN_TEMPLATES:
        existing = existing_builtin_map.get(template["template_id"]) or {}
        templates.append(
            {
                "template_id": template["template_id"],
                "template_name": template["template_name"],
                "description": template["description"],
                "created_at_utc": existing.get("created_at_utc") or now_utc(),
                "updated_at_utc": now_utc(),
                "builtin": True,
                "payload": template["payload"],
            }
        )

    if templates != existing_templates:
        save_template_index({"templates": templates})
    return templates


def list_templates() -> list[dict[str, Any]]:
    ensure_dirs()
    templates = sync_builtin_templates()
    templates.sort(key=lambda row: (not bool(row.get("builtin", False)), row.get("template_name", "").lower()))
    return templates


def save_template(payload: dict[str, Any]) -> dict[str, Any]:
    ensure_dirs()
    index = load_template_index()
    templates = [row for row in index.get("templates", []) if row["template_id"] != payload["template_id"]]
    templates.append(payload)
    save_template_index({"templates": templates})
    return payload


def create_template(payload: ScanJobCreate, template_name: str, description: str = "") -> dict[str, Any]:
    ensure_dirs()
    # Task 11: full-length uuid4().hex (32 chars) to eliminate collision risk.
    template_id = uuid.uuid4().hex
    record = {
        "template_id": template_id,
        "template_name": template_name,
        "description": description,
        "created_at_utc": now_utc(),
        "updated_at_utc": now_utc(),
        "builtin": False,
        "payload": model_dump(payload),
    }
    return save_template(record)


def update_template(template_id: str, payload: ScanJobCreate, template_name: str, description: str = "") -> dict[str, Any]:
    ensure_dirs()
    templates = list_templates()
    current = next((row for row in templates if row.get("template_id") == template_id), None)
    if current is None:
        raise KeyError(f"Template '{template_id}' was not found.")
    if bool(current.get("builtin", False)):
        raise ValueError("Built-in templates cannot be modified.")
    record = {
        "template_id": template_id,
        "template_name": template_name,
        "description": description,
        "created_at_utc": current.get("created_at_utc") or now_utc(),
        "updated_at_utc": now_utc(),
        "builtin": False,
        "payload": model_dump(payload),
    }
    return save_template(record)


def delete_template(template_id: str) -> dict[str, Any]:
    ensure_dirs()
    index = load_template_index()
    templates = index.get("templates", [])
    current = next((row for row in templates if row.get("template_id") == template_id), None)
    if current is None:
        raise KeyError(f"Template '{template_id}' was not found.")
    if bool(current.get("builtin", False)):
        raise ValueError("Built-in templates cannot be deleted.")
    remaining = [row for row in templates if row.get("template_id") != template_id]
    save_template_index({"templates": remaining})
    return current


def export_template(template_id: str) -> dict[str, Any]:
    ensure_dirs()
    current = next((row for row in list_templates() if row.get("template_id") == template_id), None)
    if current is None:
        raise KeyError(f"Template '{template_id}' was not found.")
    return current


def import_template(template_data: dict[str, Any], *, template_name: str | None = None, description: str | None = None) -> dict[str, Any]:
    ensure_dirs()
    if not isinstance(template_data, dict):
        raise ValueError("Imported template must be a JSON object.")
    raw_payload = template_data.get("payload") if "payload" in template_data else template_data
    if not isinstance(raw_payload, dict):
        raise ValueError("Imported template payload must be a JSON object.")
    payload = ScanJobCreate.model_validate(raw_payload)
    resolved_name = str(template_name or template_data.get("template_name") or "Imported Template").strip()
    if not resolved_name:
        raise ValueError("Imported template requires a non-empty template name.")
    resolved_description = str(
        description if description is not None else template_data.get("description") or ""
    ).strip()
    return create_template(payload=payload, template_name=resolved_name, description=resolved_description)
