from __future__ import annotations

import json
import sys
from pathlib import Path

from fastapi.testclient import TestClient

PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_PARENT = PACKAGE_DIR.parent
if str(PROJECT_PARENT) not in sys.path:
    sys.path.insert(0, str(PROJECT_PARENT))

from whitebox_scan_platform.app import app


def main() -> None:
    client = TestClient(app)

    options = client.get("/api/options")
    options.raise_for_status()

    wrapper_payload = {
        "wrapper_id": "demo_adapter",
        "display_name": "Demo Adapter",
        "class_name": "DemoAdapter",
        "code": """
from whitebox_scan_platform.contracts import BaseScanAdapter, WrapperCapabilities

class DemoAdapter(BaseScanAdapter):
    def capabilities(self):
        return WrapperCapabilities(
            wrapper_id="demo_adapter",
            display_name="Demo Adapter",
            supports_blackbox=True,
            supports_whitebox=True,
            supports_api_models=True,
            supports_python_process_models=True,
            supports_art=True,
            supports_foolbox=True,
            supports_pyrit=True,
            supports_garak=True,
            supports_textattack=True,
            supports_logits=True,
            supports_gradients=True,
            supported_modalities=["audio", "multimodal"],
            supported_frameworks=["art", "foolbox", "pyrit", "garak", "textattack"],
            notes="Smoke test adapter"
        )

    def run_blackbox_scan(self, config):
        return {"status": "ok", "kind": "blackbox", "model": config["model"]["model_id"]}

    def run_whitebox_scan(self, config):
        return {"status": "ok", "kind": "whitebox", "frameworks": config["configuration"]["frameworks"]}

    def run_framework_scan(self, framework, config):
        return {"status": "ok", "framework": framework, "backend": config["configuration"]["execution_backend"]}
""".strip(),
        "supports_blackbox": True,
        "supports_whitebox": True,
        "supports_api_models": True,
        "supports_python_process_models": True,
        "supports_art": True,
        "supports_foolbox": True,
        "supports_pyrit": True,
        "supports_garak": True,
        "supports_textattack": True,
        "supports_logits": True,
        "supports_gradients": True,
        "supported_modalities": ["audio", "multimodal"],
        "supported_frameworks": ["art", "foolbox", "pyrit", "garak", "textattack"],
        "notes": "Smoke test adapter",
    }
    reg = client.post("/api/wrappers/register", json=wrapper_payload)
    reg.raise_for_status()

    job_payload = {
        "job_name": "demo full platform scan",
        "model": {
            "model_id": "nvidia/audio-flamingo-3-hf",
            "source_type": "hf",
            "source_value": "nvidia/audio-flamingo-3-hf",
            "task_family": "audio-language",
            "modality": "audio",
        },
        "configuration": {
            "execution_backend": "python_process_wrapped",
            "scan_modes": ["blackbox", "whitebox"],
            "frameworks": ["art", "foolbox", "pyrit", "garak", "textattack"],
            "reports": ["json", "html", "txt_log"],
            "sample_path": "/tmp/demo_samples",
            "min_samples": 5,
            "max_iter": 5,
            "batch_size": 1,
            "include_all_applicable_attacks": True,
            "target_text": "ATTACK TEST",
            "extra_options": {},
        },
        "wrapper_id": "demo_adapter",
    }
    created = client.post("/api/scans", json=job_payload)
    created.raise_for_status()
    job_id = created.json()["job"]["job_id"]

    fetched = client.get(f"/api/scans/{job_id}")
    fetched.raise_for_status()

    out_dir = PACKAGE_DIR / "data" / "demo"
    out_dir.mkdir(parents=True, exist_ok=True)
    output_path = out_dir / "smoke_demo_result.json"
    output_path.write_text(json.dumps(fetched.json(), indent=2), encoding="utf-8")
    print(output_path.resolve())
    print(json.dumps(fetched.json(), indent=2))


if __name__ == "__main__":
    main()
