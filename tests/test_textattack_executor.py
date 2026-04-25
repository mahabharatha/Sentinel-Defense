from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch


PACKAGE_DIR = Path(__file__).resolve().parents[1]
PROJECT_PARENT = PACKAGE_DIR.parent
if str(PROJECT_PARENT) not in sys.path:
    sys.path.insert(0, str(PROJECT_PARENT))

from whitebox_scan_platform.executors.textattack_executor import _build_command
from whitebox_scan_platform.executors.textattack_executor import _resolve_textattack_options
from whitebox_scan_platform.executors.textattack_runner import _apply_runtime_safe_recipe_adjustments


class TextAttackExecutorTests(unittest.TestCase):
    def test_resolve_textattack_options_normalizes_text_classification_job(self) -> None:
        job_record = {
            "job_id": "job123",
            "job_name": "textattack smoke",
            "model": {
                "model_id": "distilbert-base-uncased-finetuned-sst-2-english",
                "source_type": "hf",
                "source_value": "distilbert-base-uncased-finetuned-sst-2-english",
                "task_family": "text-classification",
                "modality": "text",
            },
            "configuration": {
                "execution_backend": "python_process_wrapped",
                "scan_modes": ["blackbox"],
                "frameworks": ["textattack"],
                "reports": ["json", "html", "txt_log"],
                "sample_path": "",
                "min_samples": 2,
                "max_iter": 1,
                "batch_size": 1,
                "include_all_applicable_attacks": True,
                "target_text": "This movie was excellent.",
                "extra_options": {
                    "textattack_recipe": "TextFoolerJin2019",
                    "textattack_goal_function": "untargeted-classification",
                    "textattack_max_examples": 2,
                    "textattack_query_budget": 50,
                    "textattack_constraint_mode": "default",
                },
            },
        }

        resolved = _resolve_textattack_options(job_record)

        self.assertEqual(resolved["recipe"], "textfooler")
        self.assertEqual(resolved["goal_function"], "untargeted-classification")
        self.assertEqual(resolved["constraint_mode"], "default")
        self.assertEqual(resolved["max_examples"], 2)
        self.assertEqual(resolved["query_budget"], 50)
        self.assertEqual(resolved["target_text"], "This movie was excellent.")

    def test_build_command_uses_local_textattack_runner(self) -> None:
        command = _build_command(
            runner_config_path=Path("/tmp/textattack-runner.json"),
            reports_dir=Path("/tmp/textattack-reports"),
        )
        self.assertEqual(command[1:3], ["-m", "whitebox_scan_platform.executors.textattack_runner"])
        self.assertEqual(command[3:], ["--config", "/tmp/textattack-runner.json", "--output-dir", "/tmp/textattack-reports"])

    def test_textfooler_runtime_safe_adjustments_remove_missing_optional_constraints(self) -> None:
        PartOfSpeech = type("PartOfSpeech", (), {})
        UniversalSentenceEncoder = type("UniversalSentenceEncoder", (), {})
        KeepMe = type("KeepMe", (), {})
        attack = type("Attack", (), {"constraints": [PartOfSpeech(), UniversalSentenceEncoder(), KeepMe()]})()

        with patch("whitebox_scan_platform.executors.textattack_runner._nltk_resource_available", return_value=False), patch(
            "whitebox_scan_platform.executors.textattack_runner._module_available", return_value=False
        ):
            warnings = _apply_runtime_safe_recipe_adjustments("textfooler", attack)

        self.assertEqual([constraint.__class__.__name__ for constraint in attack.constraints], ["KeepMe"])
        self.assertTrue(any("PartOfSpeech" in warning for warning in warnings))
        self.assertTrue(any("UniversalSentenceEncoder" in warning for warning in warnings))


if __name__ == "__main__":
    unittest.main()
