from __future__ import annotations

import sys
import unittest
from pathlib import Path


PACKAGE_DIR = Path(__file__).resolve().parents[1]
PROJECT_PARENT = PACKAGE_DIR.parent
if str(PROJECT_PARENT) not in sys.path:
    sys.path.insert(0, str(PROJECT_PARENT))

from whitebox_scan_platform.compatibility import attach_framework_compatibility
from whitebox_scan_platform.compatibility import framework_compatibility_inventory
from whitebox_scan_platform.compatibility import framework_run_compatibility
from whitebox_scan_platform.executors.art_executor import run_art_scan
from whitebox_scan_platform.executors.foolbox_executor import run_foolbox_scan


def _job(framework: str) -> dict[str, object]:
    return {
        "job_id": f"{framework}_compat",
        "job_name": f"{framework} compatibility",
        "wrapper_id": "fake_adapter",
        "model": {
            "model_id": "demo-model",
            "source_type": "hf",
            "source_value": "demo-model",
            "task_family": "vision-classification",
            "modality": "vision",
        },
        "configuration": {
            "execution_backend": "python_process_wrapped",
            "scan_modes": ["blackbox", "whitebox"],
            "frameworks": [framework],
            "reports": ["json", "html", "txt_log"],
            "extra_options": {},
        },
    }


class FakeFrameworkAdapter:
    def run_framework_scan(self, framework: str, config: dict[str, object]) -> dict[str, object]:
        return {"status": "completed", "framework": framework, "message": "ok"}


class MissingFrameworkAdapter:
    def run_framework_scan(self, framework: str, config: dict[str, object]) -> dict[str, object]:
        raise NotImplementedError


class ToolCompatibilityTests(unittest.TestCase):
    def test_inventory_covers_all_orchestrated_frameworks(self) -> None:
        inventory = framework_compatibility_inventory(["art", "foolbox", "pyrit", "garak", "textattack"])

        self.assertEqual(set(inventory), {"art", "foolbox", "pyrit", "garak", "textattack"})
        for framework, row in inventory.items():
            self.assertEqual(row["framework"], framework)
            self.assertIn("execution_boundary", row)
            self.assertIn("adapter_strategy", row)
            self.assertIn("provenance", row["provenance_policy"].lower())

    def test_run_compatibility_records_requested_shape_and_decisions(self) -> None:
        row = framework_run_compatibility(
            "garak",
            job_record=_job("garak"),
            decisions={"generator_type": "function.Single"},
        )

        self.assertEqual(row["requested_shape"]["execution_backend"], "python_process_wrapped")
        self.assertEqual(row["requested_shape"]["modality"], "vision")
        self.assertEqual(row["compatibility_decisions"]["generator_type"], "function.Single")

    def test_attach_framework_compatibility_does_not_mutate_payload(self) -> None:
        payload = {"status": "completed", "framework": "pyrit"}

        resolved = attach_framework_compatibility(payload, "pyrit", job_record=_job("pyrit"))

        self.assertNotIn("tool_compatibility", payload)
        self.assertEqual(resolved["tool_compatibility"]["framework"], "pyrit")

    def test_art_and_foolbox_executor_results_include_compatibility(self) -> None:
        art_result = run_art_scan(FakeFrameworkAdapter(), _job("art"))
        foolbox_result = run_foolbox_scan(FakeFrameworkAdapter(), _job("foolbox"))

        self.assertEqual(art_result["tool_compatibility"]["framework"], "art")
        self.assertEqual(foolbox_result["tool_compatibility"]["framework"], "foolbox")
        self.assertEqual(
            art_result["tool_compatibility"]["compatibility_decisions"]["capability_boundary"],
            "wrapper_capability_driven",
        )

    def test_art_and_foolbox_not_implemented_results_include_compatibility(self) -> None:
        art_result = run_art_scan(MissingFrameworkAdapter(), _job("art"))
        foolbox_result = run_foolbox_scan(MissingFrameworkAdapter(), _job("foolbox"))

        self.assertEqual(art_result["status"], "not_implemented")
        self.assertFalse(art_result["tool_compatibility"]["compatibility_decisions"]["adapter_path_available"])
        self.assertFalse(foolbox_result["tool_compatibility"]["compatibility_decisions"]["adapter_path_available"])


if __name__ == "__main__":
    unittest.main()
