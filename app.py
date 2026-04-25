from __future__ import annotations

import mimetypes
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse

from .compatibility import install_framework, install_all_frameworks, FRAMEWORK_PACKAGE_SPECS
from .executor import (
    build_preflight,
    build_job_terminal_view,
    collect_job_artifacts,
    create_template,
    delete_template,
    export_template,
    create_job,
    default_options,
    import_template,
    list_jobs,
    list_templates,
    list_wrappers,
    reconcile_job_statuses,
    register_wrapper,
    run_job,
    sync_builtin_wrappers,
    update_template,
)
from .schemas import JobTemplateCreate, JobTemplateImport, JobTemplateUpdate, ScanJobCreate, WrapperRegistration
from .storage import BASE_DIR, ensure_dirs, load_job


ensure_dirs()
sync_builtin_wrappers()
reconcile_job_statuses()
# Bharath Srinivasan | Sentinel Adversarial Orchestrator application surface and connected UI are proprietary material.
app = FastAPI(
    title="Sentinel Adversarial Orchestrator",
    description="Sentinel's local-first orchestration platform for black-box and white-box AI security scanning.",
    version="0.1.0",
)


@app.get("/", response_class=HTMLResponse)
def home() -> str:
    ui_path = Path(__file__).resolve().parent / "ui" / "index.html"
    return HTMLResponse(
        ui_path.read_text(encoding="utf-8"),
        headers={
            "Content-Security-Policy": "default-src 'self' 'unsafe-inline'; img-src 'self' data:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'",
            "Referrer-Policy": "no-referrer",
            "X-Content-Type-Options": "nosniff",
        },
    )


@app.get("/api/options")
def options() -> dict:
    return {"options": default_options(), "wrappers": list_wrappers(), "templates": list_templates()}


@app.get("/api/wrappers")
def wrappers() -> dict:
    return {"wrappers": list_wrappers()}


@app.get("/api/templates")
def templates() -> dict:
    return {"templates": list_templates()}


@app.post("/api/templates")
def templates_create(payload: JobTemplateCreate) -> dict:
    template = create_template(
        payload=payload.payload,
        template_name=payload.template_name,
        description=payload.description,
    )
    return {"template": template}


@app.put("/api/templates/{template_id}")
def templates_update(template_id: str, payload: JobTemplateUpdate) -> dict:
    try:
        template = update_template(
            template_id=template_id,
            payload=payload.payload,
            template_name=payload.template_name,
            description=payload.description,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"template": template}


@app.delete("/api/templates/{template_id}")
def templates_delete(template_id: str) -> dict:
    try:
        template = delete_template(template_id=template_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"deleted": template}


@app.get("/api/templates/{template_id}/export")
def templates_export(template_id: str) -> dict:
    try:
        template = export_template(template_id=template_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"template": template}


@app.post("/api/templates/import")
def templates_import(payload: JobTemplateImport) -> dict:
    try:
        template = import_template(
            template_data=payload.template,
            template_name=payload.template_name,
            description=payload.description,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"template": template}


@app.post("/api/wrappers/register")
def wrappers_register(payload: WrapperRegistration) -> dict:
    return {"wrapper": register_wrapper(payload)}


@app.post("/api/scans")
def scans_create(payload: ScanJobCreate, background_tasks: BackgroundTasks) -> dict:
    record = create_job(payload)
    background_tasks.add_task(run_job, record["job_id"])
    return {"job": record}


@app.post("/api/scans/preflight")
def scans_preflight(payload: ScanJobCreate) -> dict:
    return {"preflight": build_preflight(payload)}


@app.post("/api/scans/demo/whisper-art")
def scans_demo_whisper_art(background_tasks: BackgroundTasks) -> dict:
    payload = ScanJobCreate(
        job_name="whisper tiny art demo",
        model={
            "model_id": "openai/whisper-tiny.en",
            "source_type": "hf",
            "source_value": "openai/whisper-tiny.en",
            "task_family": "speech-to-text",
            "modality": "audio",
        },
        configuration={
            "execution_backend": "python_process_wrapped",
            "scan_modes": ["blackbox", "whitebox"],
            "frameworks": ["art"],
            "reports": ["json", "html", "txt_log"],
            "sample_path": "rhel_art_audio_demo/samples/demo_tone.wav",
            "min_samples": 1,
            "max_iter": 5,
            "batch_size": 1,
            "include_all_applicable_attacks": True,
            "target_text": "ATTACK TEST",
            "extra_options": {},
        },
        wrapper_id="whisper_tiny_art_adapter",
    )
    record = create_job(payload)
    background_tasks.add_task(run_job, record["job_id"])
    return {"job": record}


@app.get("/api/scans")
def scans_list() -> dict:
    return {"jobs": list_jobs()}


@app.get("/api/scans/{job_id}")
def scans_get(job_id: str) -> dict:
    payload = load_job(job_id)
    if payload is None:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found.")
    return {"job": payload}


@app.get("/api/scans/{job_id}/artifacts")
def scans_artifacts(job_id: str) -> dict:
    payload = load_job(job_id)
    if payload is None:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found.")
    return {"job_id": job_id, "artifacts": collect_job_artifacts(payload)}


@app.get("/api/scans/{job_id}/terminal")
def scans_terminal(job_id: str) -> dict:
    payload = load_job(job_id)
    if payload is None:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found.")
    return {"job_id": job_id, "terminal": build_job_terminal_view(payload)}


def _resolve_artifact_path(path: str) -> Path:
    target = Path(path).expanduser().resolve()
    allowed_root = BASE_DIR.resolve()
    if allowed_root != target and allowed_root not in target.parents:
        raise HTTPException(status_code=403, detail="Artifact path is outside the allowed workspace root.")
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail=f"Artifact '{target}' not found.")
    return target


def _artifact_headers(target: Path) -> dict[str, str]:
    headers = {
        "Referrer-Policy": "no-referrer",
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "SAMEORIGIN",
    }
    if target.suffix.lower() == ".html":
        headers["Content-Security-Policy"] = (
            "default-src 'none'; "
            "style-src 'unsafe-inline'; "
            "img-src 'self' data:; "
            "font-src 'self' data:; "
            "base-uri 'none'; "
            "form-action 'none'; "
            "frame-ancestors 'self'; "
            "sandbox"
        )
    return headers


def _artifact_media_type(target: Path) -> str:
    media_type_map = {
        ".json": "application/json",
        ".html": "text/html",
        ".txt": "text/plain",
        ".log": "text/plain",
        ".md": "text/markdown",
        ".csv": "text/csv",
        ".yml": "text/plain",
        ".yaml": "text/plain",
    }
    return media_type_map.get(target.suffix.lower()) or mimetypes.guess_type(str(target))[0] or "application/octet-stream"


@app.get("/api/artifacts/content")
def artifact_content(path: str) -> dict:
    target = _resolve_artifact_path(path)

    media_type = _artifact_media_type(target)
    if media_type is None:
        raise HTTPException(status_code=415, detail="Artifact preview is only supported for text-like files.")

    content = target.read_text(encoding="utf-8", errors="replace")
    truncated = False
    if len(content) > 200_000:
        content = content[:200_000] + "\n\n[truncated]"
        truncated = True

    return {
        "path": str(target),
        "media_type": media_type,
        "truncated": truncated,
        "content": content,
    }


@app.get("/api/artifacts/view")
def artifact_view(path: str) -> FileResponse:
    target = _resolve_artifact_path(path)
    return FileResponse(
        path=target,
        media_type=_artifact_media_type(target),
        filename=target.name,
        content_disposition_type="inline",
        headers=_artifact_headers(target),
    )


@app.get("/api/artifacts/download")
def artifact_download(path: str) -> FileResponse:
    target = _resolve_artifact_path(path)
    return FileResponse(
        path=target,
        media_type=_artifact_media_type(target),
        filename=target.name,
        content_disposition_type="attachment",
        headers=_artifact_headers(target),
    )


# ── Install endpoints ─────────────────────────────────────────────────────────

@app.post("/api/install/{framework}")
def install_one(framework: str) -> dict:
    """Install or upgrade a single adversarial framework package."""
    if framework not in FRAMEWORK_PACKAGE_SPECS:
        supported = ", ".join(FRAMEWORK_PACKAGE_SPECS)
        raise HTTPException(status_code=400, detail=f"Unknown framework '{framework}'. Supported: {supported}")
    return install_framework(framework)


@app.post("/api/install")
def install_all() -> dict:
    """Install or upgrade all adversarial framework packages."""
    return install_all_frameworks()


@app.get("/api/install/status")
def install_status() -> dict:
    """Return install status for each adversarial framework."""
    order = list(FRAMEWORK_PACKAGE_SPECS.keys())
    from .compatibility import framework_compatibility_inventory
    inventory = framework_compatibility_inventory(order)
    return {
        fw: {
            "installed": row["installed"],
            "installed_version": row.get("installed_version", ""),
            "minimum_version": row.get("minimum_version", ""),
            "version_ok": row.get("version_ok", False),
            "package": row.get("package_name", ""),
        }
        for fw, row in inventory.items()
    }
