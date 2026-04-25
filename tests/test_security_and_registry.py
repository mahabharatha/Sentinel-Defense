from __future__ import annotations

import unittest
from pathlib import Path

from fastapi.testclient import TestClient
from pydantic import ValidationError

from whitebox_scan_platform.app import app
from whitebox_scan_platform.framework_registry import FRAMEWORK_CAPABILITY_FLAGS
from whitebox_scan_platform.framework_registry import FRAMEWORK_SUPPORT_MATRIX
from whitebox_scan_platform.framework_registry import default_framework_order
from whitebox_scan_platform.framework_registry import framework_supported
from whitebox_scan_platform.schemas import ScanConfiguration
from whitebox_scan_platform.schemas import ScanJobCreate
from whitebox_scan_platform.schemas import WrapperRegistration
from whitebox_scan_platform.storage import BASE_DIR
from whitebox_scan_platform.storage import resolve_workspace_path


class FrameworkRegistryTests(unittest.TestCase):
    def test_default_framework_order_is_stable(self) -> None:
        self.assertEqual(default_framework_order(), ["art", "foolbox", "pyrit", "garak", "textattack"])

    def test_registry_exposes_capability_flags_for_all_frameworks(self) -> None:
        self.assertEqual(set(FRAMEWORK_CAPABILITY_FLAGS), set(default_framework_order()))
        self.assertEqual(set(FRAMEWORK_SUPPORT_MATRIX), set(default_framework_order()))

    def test_framework_supported_respects_supported_framework_list(self) -> None:
        capabilities = {
            "supports_art": False,
            "supported_frameworks": ["art"],
        }
        self.assertTrue(framework_supported(capabilities, "art"))


class SecurityBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(app)

    def test_artifact_access_blocks_outside_workspace(self) -> None:
        response = self.client.get("/api/artifacts/content", params={"path": "/tmp/outside.txt"})
        self.assertEqual(response.status_code, 403)

    def test_html_artifact_view_sets_csp_headers(self) -> None:
        artifact_dir = BASE_DIR / "data" / "test_security"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        artifact_path = artifact_dir / "sample_report.html"
        artifact_path.write_text("<html><body>ok</body></html>", encoding="utf-8")
        try:
            response = self.client.get("/api/artifacts/view", params={"path": str(artifact_path)})
            self.assertEqual(response.status_code, 200)
            csp = response.headers.get("content-security-policy", "")
            self.assertIn("sandbox", csp)
            self.assertIn("default-src 'none'", csp)
        finally:
            artifact_path.unlink(missing_ok=True)
            try:
                artifact_dir.rmdir()
            except OSError:
                pass

    def test_wrapper_registration_rejects_path_like_ids(self) -> None:
        with self.assertRaises(ValidationError):
            WrapperRegistration(
                wrapper_id="../evil",
                display_name="Bad Wrapper",
                class_name="BadWrapper",
                code="print('nope')",
            )

    def test_scan_job_rejects_invalid_wrapper_id(self) -> None:
        with self.assertRaises(ValidationError):
            ScanJobCreate(
                job_name="bad wrapper ref",
                model={
                    "model_id": "demo",
                    "source_type": "hf",
                    "source_value": "demo/model",
                    "task_family": "text-classification",
                    "modality": "text",
                },
                configuration=ScanConfiguration(
                    execution_backend="python_process_wrapped",
                    scan_modes=["blackbox"],
                    frameworks=["textattack"],
                    reports=["json"],
                ),
                wrapper_id="../../escape",
            )

    def test_workspace_path_rejects_external_absolute_paths(self) -> None:
        with self.assertRaises(ValueError):
            resolve_workspace_path("/tmp/outside.txt", field_name="sample_path")


if __name__ == "__main__":
    unittest.main()
