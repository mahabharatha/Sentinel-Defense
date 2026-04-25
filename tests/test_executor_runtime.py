from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch


PACKAGE_DIR = Path(__file__).resolve().parents[1]
PROJECT_PARENT = PACKAGE_DIR.parent
if str(PROJECT_PARENT) not in sys.path:
    sys.path.insert(0, str(PROJECT_PARENT))

from whitebox_scan_platform.executor import evaluate_platform_support
from whitebox_scan_platform.executor import evaluate_runtime_readiness
from whitebox_scan_platform.executor import execute_job_record
from whitebox_scan_platform.executor import framework_runtime_inventory
from whitebox_scan_platform.executor import default_options
from whitebox_scan_platform.executor import local_service_inventory
from whitebox_scan_platform.executor import python_runtime_summary
from whitebox_scan_platform.schemas import ScanJobCreate
from whitebox_scan_platform.compatibility import framework_compatibility_inventory


class ExecutorRuntimeTests(unittest.TestCase):
    def test_execute_job_record_ignores_incompatible_wrapper_for_builtin_pyrit(self) -> None:
        class FakeCapabilities:
            supports_blackbox = True
            supports_whitebox = True
            supports_api_models = False
            supports_python_process_models = True
            supports_art = True
            supports_foolbox = False
            supports_pyrit = False
            supports_garak = False
            supports_textattack = False
            supported_frameworks = ["art"]

            def model_dump(self) -> dict[str, object]:
                return {
                    "supports_blackbox": self.supports_blackbox,
                    "supports_whitebox": self.supports_whitebox,
                    "supports_api_models": self.supports_api_models,
                    "supports_python_process_models": self.supports_python_process_models,
                    "supports_art": self.supports_art,
                    "supports_foolbox": self.supports_foolbox,
                    "supports_pyrit": self.supports_pyrit,
                    "supports_garak": self.supports_garak,
                    "supports_textattack": self.supports_textattack,
                    "supported_frameworks": self.supported_frameworks,
                }

        class FakeAdapter:
            def capabilities(self) -> FakeCapabilities:
                return FakeCapabilities()

            def validate_config(self, config: dict[str, object]) -> list[str]:
                return ["wrapper mismatch"]

            def run_blackbox_scan(self, config: dict[str, object]) -> dict[str, object]:
                raise AssertionError("run_blackbox_scan should not be called for incompatible built-in PyRIT jobs")

            def run_whitebox_scan(self, config: dict[str, object]) -> dict[str, object]:
                raise AssertionError("run_whitebox_scan should not be called for incompatible built-in PyRIT jobs")

            def run_framework_scan(self, framework: str, config: dict[str, object]) -> dict[str, object]:
                raise AssertionError("run_framework_scan should not be called for incompatible built-in PyRIT jobs")

        job_record = {
            "job_id": "pyrit_wrapper_ignore",
            "job_name": "pyrit wrapper ignore",
            "wrapper_id": "hf_vision_classification_art_adapter",
            "model": {
                "model_id": "gemma3:4b",
                "source_type": "api",
                "source_value": "http://127.0.0.1:11434/api/generate",
                "task_family": "multimodal-chat",
                "modality": "multimodal",
            },
            "configuration": {
                "execution_backend": "api_based",
                "scan_modes": ["blackbox"],
                "frameworks": ["pyrit"],
                "reports": ["json", "html", "txt_log"],
                "sample_path": "docs/images/product-screenshot.png",
                "min_samples": 1,
                "max_iter": 1,
                "batch_size": 1,
                "include_all_applicable_attacks": True,
                "target_text": "Answer in one short sentence and include screenshot and dashboard.",
                "extra_options": {
                    "pyrit_profile": "multimodal",
                    "pyrit_model_name": "gemma3:4b",
                    "pyrit_attack_type": "prompt_sending",
                },
            },
        }

        builtin_framework_run = {
            "status": "completed",
            "framework": "pyrit",
            "message": "PyRIT run completed.",
            "target_uri": "http://127.0.0.1:11434/api/chat",
            "attack_type": "prompt_sending",
            "attack_types": ["prompt_sending"],
            "objective": "Answer in one short sentence and include screenshot and dashboard.",
            "model_name": "gemma3:4b",
            "tool_compatibility": {"framework": "pyrit", "execution_boundary": "built_in_api_executor"},
            "artifacts": {},
        }

        with patch("whitebox_scan_platform.executor._load_adapter", return_value=FakeAdapter()), \
             patch("whitebox_scan_platform.executor._run_builtin_framework_scan", return_value=builtin_framework_run), \
             patch("whitebox_scan_platform.executor._attach_mode_summary_artifacts", side_effect=lambda job, result: result):
            result = execute_job_record(job_record)

        self.assertEqual(result["framework_runs"]["pyrit"]["status"], "completed")
        self.assertEqual(result["blackbox"]["framework"], "pyrit")
        self.assertEqual(result["blackbox"]["tool_compatibility"]["framework"], "pyrit")
        note_types = {note["type"] for note in result["notes"]}
        self.assertIn("validation", note_types)
        self.assertIn("pyrit_wrapper_ignored", note_types)

    def test_python_runtime_summary_reports_pyrit_compatibility(self) -> None:
        summary = python_runtime_summary()
        self.assertIn("python_executable", summary)
        self.assertIn("python_version", summary)
        self.assertIn("pyrit_supported_python", summary)

    def test_framework_runtime_inventory_reports_missing_imports(self) -> None:
        with patch("whitebox_scan_platform.executor.importlib.util.find_spec") as mock_find_spec:
            mock_find_spec.side_effect = lambda name: object() if name == "art" else None
            inventory = framework_runtime_inventory()

        self.assertTrue(inventory["art"]["installed"])
        self.assertFalse(inventory["pyrit"]["installed"])
        self.assertEqual(inventory["garak"]["package_name"], "garak")
        self.assertEqual(inventory["pyrit"]["python_requirement"], ">=3.10,<3.14")
        self.assertEqual(inventory["garak"]["compatibility_layer"]["execution_boundary"], "built_in_cli_executor")
        self.assertNotIn("giskard", inventory)
        self.assertNotIn("promptfoo", inventory)

    def test_compatibility_inventory_tracks_garak_feature_fallbacks(self) -> None:
        def fake_find_spec(name: str) -> object | None:
            if name == "garak":
                return object()
            return None

        inventory = framework_compatibility_inventory(["garak"], find_spec=fake_find_spec)

        self.assertTrue(inventory["garak"]["installed"])
        self.assertFalse(inventory["garak"]["feature_checks"]["rest_generator_available"])
        self.assertTrue(inventory["garak"]["feature_checks"]["ollama_function_bridge_available"])
        self.assertIn("--narrow_output", inventory["garak"]["feature_checks"]["unsupported_flags_avoided"])
        self.assertIn("provenance", inventory["garak"]["provenance_policy"].lower())

    def test_default_options_exposes_tool_compatibility(self) -> None:
        options = default_options()

        self.assertIn("tool_compatibility", options)
        self.assertEqual(options["tool_compatibility"]["textattack"]["execution_boundary"], "built_in_python_process_runner")

    def test_local_service_inventory_reports_ollama_models(self) -> None:
        with patch(
            "whitebox_scan_platform.executor._probe_ollama_tags",
            return_value={
                "service": "ollama",
                "reachable": True,
                "endpoint": "http://127.0.0.1:11434/api/tags",
                "status": "reachable",
                "model_count": 2,
                "models": ["gemma3:4b", "tinyllama:1.1b-chat"],
                "error": "",
            },
        ):
            inventory = local_service_inventory()

        self.assertTrue(inventory["ollama"]["reachable"])
        self.assertEqual(inventory["ollama"]["model_count"], 2)
        self.assertIn("gemma3:4b", inventory["ollama"]["models"])

    def test_preflight_platform_support_blocks_missing_runtime_for_implemented_pyrit_path(self) -> None:
        job = ScanJobCreate(
            job_name="pyrit runtime check",
            model={
                "model_id": "tinyllama:1.1b-chat",
                "source_type": "api",
                "source_value": "http://127.0.0.1:11434/api/generate",
                "task_family": "text-generation",
                "modality": "text",
            },
            configuration={
                "execution_backend": "api_based",
                "scan_modes": ["blackbox"],
                "frameworks": ["pyrit"],
                "reports": ["json", "html", "txt_log"],
                "sample_path": "",
                "min_samples": 1,
                "max_iter": 1,
                "batch_size": 1,
                "include_all_applicable_attacks": True,
                "target_text": None,
                "extra_options": {},
            },
            wrapper_id=None,
        )

        with patch("whitebox_scan_platform.executor.importlib.util.find_spec", return_value=None):
            support = evaluate_platform_support(job)

        joined_blockers = "\n".join(support["blockers"])
        self.assertIn("runtime dependency 'pyrit' is not installed", joined_blockers)
        self.assertEqual(support["supported_frameworks"][0]["status"], "implemented_missing_runtime")

    def test_runtime_readiness_blocks_unreachable_local_ollama_for_pyrit(self) -> None:
        job = ScanJobCreate(
            job_name="pyrit local ollama missing",
            model={
                "model_id": "tinyllama:1.1b-chat",
                "source_type": "api",
                "source_value": "http://127.0.0.1:11434/api/generate",
                "task_family": "text-generation",
                "modality": "text",
            },
            configuration={
                "execution_backend": "api_based",
                "scan_modes": ["blackbox"],
                "frameworks": ["pyrit"],
                "reports": ["json", "html", "txt_log"],
                "sample_path": "",
                "min_samples": 1,
                "max_iter": 1,
                "batch_size": 1,
                "include_all_applicable_attacks": True,
                "target_text": "Return PYRIT_TEST",
                "extra_options": {"pyrit_model_name": "tinyllama:1.1b-chat"},
            },
            wrapper_id=None,
        )

        with patch(
            "whitebox_scan_platform.executor._probe_ollama_tags",
            return_value={
                "service": "ollama",
                "reachable": False,
                "endpoint": "http://127.0.0.1:11434/api/tags",
                "status": "unreachable",
                "model_count": 0,
                "models": [],
                "error": "connection refused",
            },
        ):
            readiness = evaluate_runtime_readiness(job)

        self.assertTrue(any("not reachable" in blocker for blocker in readiness["blockers"]))

    def test_runtime_readiness_blocks_missing_local_ollama_model_for_pyrit(self) -> None:
        job = ScanJobCreate(
            job_name="pyrit local ollama model missing",
            model={
                "model_id": "gemma3:4b",
                "source_type": "api",
                "source_value": "http://127.0.0.1:11434/api/generate",
                "task_family": "multimodal-chat",
                "modality": "multimodal",
            },
            configuration={
                "execution_backend": "api_based",
                "scan_modes": ["blackbox"],
                "frameworks": ["pyrit"],
                "reports": ["json", "html", "txt_log"],
                "sample_path": "/tmp/example.png",
                "min_samples": 1,
                "max_iter": 1,
                "batch_size": 1,
                "include_all_applicable_attacks": True,
                "target_text": "Describe the image and include screenshot.",
                "extra_options": {
                    "pyrit_profile": "multimodal",
                    "pyrit_model_name": "gemma3:4b",
                },
            },
            wrapper_id=None,
        )

        with patch(
            "whitebox_scan_platform.executor._probe_ollama_tags",
            return_value={
                "service": "ollama",
                "reachable": True,
                "endpoint": "http://127.0.0.1:11434/api/tags",
                "status": "reachable",
                "model_count": 1,
                "models": ["tinyllama:1.1b-chat"],
                "error": "",
            },
        ):
            readiness = evaluate_runtime_readiness(job)

        self.assertTrue(any("not currently available" in blocker for blocker in readiness["blockers"]))

    def test_runtime_readiness_blocks_missing_multimodal_seed_image(self) -> None:
        job = ScanJobCreate(
            job_name="pyrit multimodal missing image",
            model={
                "model_id": "gemma3:4b",
                "source_type": "api",
                "source_value": "http://127.0.0.1:11434/api/generate",
                "task_family": "multimodal-chat",
                "modality": "multimodal",
            },
            configuration={
                "execution_backend": "api_based",
                "scan_modes": ["blackbox"],
                "frameworks": ["pyrit"],
                "reports": ["json", "html", "txt_log"],
                "sample_path": "",
                "min_samples": 1,
                "max_iter": 1,
                "batch_size": 1,
                "include_all_applicable_attacks": True,
                "target_text": "Describe the image and include screenshot.",
                "extra_options": {
                    "pyrit_profile": "multimodal",
                    "pyrit_model_name": "gemma3:4b",
                },
            },
            wrapper_id=None,
        )

        with patch(
            "whitebox_scan_platform.executor._probe_ollama_tags",
            return_value={
                "service": "ollama",
                "reachable": True,
                "endpoint": "http://127.0.0.1:11434/api/tags",
                "status": "reachable",
                "model_count": 1,
                "models": ["gemma3:4b"],
                "error": "",
            },
        ):
            readiness = evaluate_runtime_readiness(job)

        self.assertTrue(any("Seed Image Path or Sample Path" in blocker for blocker in readiness["blockers"]))

    def test_runtime_readiness_blocks_textattack_out_of_scope_api_configuration(self) -> None:
        job = ScanJobCreate(
            job_name="textattack api out of scope",
            model={
                "model_id": "demo/api-classifier",
                "source_type": "api",
                "source_value": "http://127.0.0.1:9999/classify",
                "task_family": "text-generation",
                "modality": "text",
            },
            configuration={
                "execution_backend": "api_based",
                "scan_modes": ["blackbox", "whitebox"],
                "frameworks": ["textattack"],
                "reports": ["json", "html", "txt_log"],
                "sample_path": "",
                "min_samples": 1,
                "max_iter": 1,
                "batch_size": 1,
                "include_all_applicable_attacks": True,
                "target_text": "",
                "extra_options": {},
            },
            wrapper_id=None,
        )

        with patch("whitebox_scan_platform.executor.importlib.util.find_spec", return_value=None):
            readiness = evaluate_runtime_readiness(job)

        joined_blockers = "\n".join(readiness["blockers"])
        joined_warnings = "\n".join(readiness["warnings"])
        self.assertIn("python_process_wrapped", joined_blockers)
        self.assertIn("not an API endpoint", joined_blockers)
        self.assertIn("text-classification", joined_blockers)
        self.assertIn("blackbox-only", joined_blockers)
        self.assertIn("TextAttack runtime dependency 'textattack' is not installed", joined_blockers)
        self.assertIn("Provide a Sample Path or Target Text", joined_warnings)


if __name__ == "__main__":
    unittest.main()
