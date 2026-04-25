from __future__ import annotations

import json
import os
import re
import tempfile
import threading
from pathlib import Path
from typing import Any, Optional


# Task 10: serialize mutations that depend on reading then writing the same file
# (e.g. reconcile_job_statuses, save_job vs live updates). A single module-level
# lock is coarse but correct; callers that already hold the lock must not re-enter.
JOB_WRITE_LOCK = threading.RLock()


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
JOBS_DIR = DATA_DIR / "jobs"
WRAPPERS_DIR = BASE_DIR / "user_wrappers"
WRAPPER_INDEX = DATA_DIR / "wrappers.json"
TEMPLATE_INDEX = DATA_DIR / "templates.json"
SAFE_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_-]{0,127}$")


def ensure_safe_identifier(value: str, *, field_name: str) -> str:
    cleaned = str(value or "").strip()
    if not SAFE_IDENTIFIER_RE.fullmatch(cleaned):
        raise ValueError(
            f"{field_name} must start with a letter, number, or underscore and contain only letters, numbers, underscores, or hyphens."
        )
    return cleaned


def resolve_wrapper_file_path(wrapper_id: str) -> Path:
    safe_wrapper_id = ensure_safe_identifier(wrapper_id, field_name="wrapper_id")
    return WRAPPERS_DIR / f"{safe_wrapper_id}.py"


def resolve_workspace_path(path_value: str, *, field_name: str) -> Path:
    raw_path = str(path_value or "").strip()
    if not raw_path:
        raise ValueError(f"{field_name} cannot be blank.")
    path = Path(raw_path).expanduser()
    resolved = path.resolve() if path.is_absolute() else (BASE_DIR / path).resolve()
    workspace_root = BASE_DIR.resolve()
    if workspace_root != resolved and workspace_root not in resolved.parents:
        raise ValueError(f"{field_name} must stay within the workspace root.")
    return resolved


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    WRAPPERS_DIR.mkdir(parents=True, exist_ok=True)
    if not WRAPPER_INDEX.exists():
        write_json(WRAPPER_INDEX, {"wrappers": []})
    if not TEMPLATE_INDEX.exists():
        write_json(TEMPLATE_INDEX, {"templates": []})


def read_json(path: Path, default: Optional[Any] = None) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    # Task 10: atomic write via tempfile + os.replace so a reader never observes a
    # half-written file, and a concurrent mutation can't leave the file truncated.
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=2, sort_keys=False) + "\n"
    fd, tmp_path = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            try:
                os.fsync(handle.fileno())
            except OSError:
                # Some filesystems (e.g. tmpfs on CI) don't support fsync; best effort only.
                pass
        os.replace(tmp_path, str(path))
    except Exception:
        try:
            os.unlink(tmp_path)
        except FileNotFoundError:
            pass
        raise


def list_job_files() -> list[Path]:
    ensure_dirs()
    return sorted(JOBS_DIR.glob("*.json"))


def save_job(job_id: str, payload: dict[str, Any]) -> Path:
    # Task 10: hold the job-write lock while mutating on-disk state. Combined with
    # atomic write_json this prevents reconcile_job_statuses from overwriting an
    # in-flight status update (and vice-versa).
    ensure_dirs()
    path = JOBS_DIR / f"{job_id}.json"
    with JOB_WRITE_LOCK:
        write_json(path, payload)
    return path


def load_job(job_id: str) -> Optional[dict[str, Any]]:
    ensure_dirs()
    return read_json(JOBS_DIR / f"{job_id}.json")


def save_wrapper_file(wrapper_id: str, code: str) -> Path:
    ensure_dirs()
    path = resolve_wrapper_file_path(wrapper_id)
    path.write_text(code, encoding="utf-8")
    return path


def load_wrapper_index() -> dict[str, Any]:
    ensure_dirs()
    return read_json(WRAPPER_INDEX, default={"wrappers": []})


def save_wrapper_index(payload: dict[str, Any]) -> None:
    ensure_dirs()
    write_json(WRAPPER_INDEX, payload)


def load_wrapper_code(wrapper_id: str) -> str | None:
    ensure_dirs()
    path = resolve_wrapper_file_path(wrapper_id)
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")


def load_template_index() -> dict[str, Any]:
    ensure_dirs()
    return read_json(TEMPLATE_INDEX, default={"templates": []})


def save_template_index(payload: dict[str, Any]) -> None:
    ensure_dirs()
    write_json(TEMPLATE_INDEX, payload)
