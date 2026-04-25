from __future__ import annotations

import json
import sys
import unittest
import uuid
from pathlib import Path


PACKAGE_DIR = Path(__file__).resolve().parents[1]
PROJECT_PARENT = PACKAGE_DIR.parent
if str(PROJECT_PARENT) not in sys.path:
    sys.path.insert(0, str(PROJECT_PARENT))

from whitebox_scan_platform.executor import _build_normalized_severity_payload, _mode_specific_rows, _render_mode_summary_html, _render_normalized_severity_html


class NormalizedSeverityTests(unittest.TestCase):
    def test_foolbox_normalized_payload_uses_mode_attack_scope(self) -> None:
        job_record = {
            "job_id": f"foolbox_scope_{uuid.uuid4().hex[:8]}",
            "job_name": "foolbox scope fixture",
            "wrapper_id": "hf_vision_foolbox_adapter",
            "model": {
                "model_id": "microsoft/resnet-18",
                "source_type": "hf",
                "source_value": "microsoft/resnet-18",
                "task_family": "vision-classification",
                "modality": "vision",
            },
            "configuration": {
                "execution_backend": "python_process_wrapped",
                "scan_modes": ["blackbox", "whitebox"],
                "frameworks": ["foolbox"],
                "reports": ["json", "html", "txt_log"],
                "sample_path": "data/demo/ocr_sample.png",
                "min_samples": 1,
                "max_iter": 1,
                "batch_size": 1,
                "include_all_applicable_attacks": True,
                "target_text": None,
                "extra_options": {},
            },
        }
        blackbox_attacks = [
            {"attack_name": "LinfFastGradientAttack", "status": "completed", "success": False, "prediction_changed": False, "selected_epsilon": 0.03, "perturbation_linf": 0.03, "adversarial_confidence": 0.6},
            {"attack_name": "LinfProjectedGradientDescentAttack", "status": "completed", "success": True, "prediction_changed": True, "selected_epsilon": 0.03, "perturbation_linf": 0.03, "adversarial_confidence": 0.1},
        ]
        whitebox_attacks = [
            {"attack_name": "SaltAndPepperNoiseAttack", "status": "completed", "success": False, "prediction_changed": False, "selected_epsilon": 0.1, "perturbation_linf": 0.2, "adversarial_confidence": 0.5},
            {"attack_name": "L2AdditiveGaussianNoiseAttack", "status": "completed", "success": True, "prediction_changed": True, "selected_epsilon": 0.1, "perturbation_linf": 0.15, "adversarial_confidence": 0.2},
        ]
        full_result = {
            "framework_runs": {
                "foolbox": {
                    "status": "completed",
                    "framework": "foolbox",
                    "clean_prediction": {"confidence": 0.95},
                    "attack_results": blackbox_attacks + whitebox_attacks,
                    "artifacts": {},
                }
            }
        }
        blackbox_mode = {
            "status": "completed",
            "framework": "foolbox",
            "clean_prediction": {"confidence": 0.95},
            "attack_results": blackbox_attacks,
            "artifacts": {},
        }
        whitebox_mode = {
            "status": "completed",
            "framework": "foolbox",
            "clean_prediction": {"confidence": 0.95},
            "attack_results": whitebox_attacks,
            "artifacts": {},
        }

        blackbox_payload = _build_normalized_severity_payload(job_record, full_result, "blackbox", blackbox_mode)
        whitebox_payload = _build_normalized_severity_payload(job_record, full_result, "whitebox", whitebox_mode)

        self.assertEqual(blackbox_payload["overall_normalized_verdict"]["finding_count"], 2)
        self.assertEqual(whitebox_payload["overall_normalized_verdict"]["finding_count"], 2)
        self.assertEqual(
            [row["tool_attack_label"] for row in blackbox_payload["normalized_findings"]],
            ["LinfFastGradientAttack", "LinfProjectedGradientDescentAttack"],
        )
        self.assertEqual(
            [row["tool_attack_label"] for row in whitebox_payload["normalized_findings"]],
            ["SaltAndPepperNoiseAttack", "L2AdditiveGaussianNoiseAttack"],
        )
        self.assertTrue(
            all(row["mapping_details"]["finding_scope"] == "mode" for row in blackbox_payload["normalized_findings"])
        )

    def test_foolbox_mode_summary_rows_include_attack_counts(self) -> None:
        job_record = {
            "job_id": f"foolbox_rows_{uuid.uuid4().hex[:8]}",
            "job_name": "foolbox rows fixture",
            "wrapper_id": "hf_vision_foolbox_adapter",
            "model": {
                "model_id": "microsoft/resnet-18",
                "source_type": "hf",
                "source_value": "microsoft/resnet-18",
                "task_family": "vision-classification",
                "modality": "vision",
            },
            "configuration": {
                "execution_backend": "python_process_wrapped",
                "scan_modes": ["blackbox", "whitebox"],
                "frameworks": ["foolbox"],
                "reports": ["json", "html", "txt_log"],
                "sample_path": "data/demo/ocr_sample.png",
                "min_samples": 1,
                "max_iter": 10,
                "batch_size": 1,
                "include_all_applicable_attacks": True,
                "target_text": None,
                "extra_options": {},
            },
        }
        full_result = {
            "framework_runs": {
                "foolbox": {
                    "status": "completed",
                    "framework": "foolbox",
                    "attack_results": [],
                }
            }
        }
        blackbox_mode = {
            "status": "completed",
            "framework": "foolbox",
            "attack_count": 2,
            "successful_attack_count": 0,
            "clean_prediction": {"label_name": "website"},
            "attack_results": [
                {"attack_name": "SaltAndPepperNoiseAttack", "success": False},
                {"attack_name": "L2AdditiveGaussianNoiseAttack", "success": False},
            ],
        }
        whitebox_mode = {
            "status": "completed",
            "framework": "foolbox",
            "attack_count": 2,
            "successful_attack_count": 2,
            "attack_results": [
                {"attack_name": "LinfFastGradientAttack", "success": True},
                {"attack_name": "LinfProjectedGradientDescentAttack", "success": True},
            ],
        }

        blackbox_rows = _mode_specific_rows(job_record, full_result, "blackbox", blackbox_mode)
        whitebox_rows = _mode_specific_rows(job_record, full_result, "whitebox", whitebox_mode)

        self.assertIn(["Attack Count", 2], blackbox_rows)
        self.assertIn(["Successful Attack Count", 0], blackbox_rows)
        self.assertIn(["Attack Names", "SaltAndPepperNoiseAttack, L2AdditiveGaussianNoiseAttack"], blackbox_rows)
        self.assertIn(["Attack Count", 2], whitebox_rows)
        self.assertIn(["Successful Attack Count", 2], whitebox_rows)
        self.assertIn(["Attack Names", "LinfFastGradientAttack, LinfProjectedGradientDescentAttack"], whitebox_rows)

    def test_foolbox_original_report_includes_attack_details_section(self) -> None:
        job_record = {
            "job_id": f"foolbox_html_{uuid.uuid4().hex[:8]}",
            "job_name": "foolbox html fixture",
            "wrapper_id": "hf_vision_foolbox_adapter",
            "model": {
                "model_id": "microsoft/resnet-18",
                "source_type": "hf",
                "source_value": "microsoft/resnet-18",
                "task_family": "vision-classification",
                "modality": "vision",
            },
            "configuration": {
                "execution_backend": "python_process_wrapped",
                "scan_modes": ["blackbox", "whitebox"],
                "frameworks": ["foolbox"],
                "reports": ["json", "html", "txt_log"],
                "sample_path": "data/demo/ocr_sample.png",
                "min_samples": 1,
                "max_iter": 10,
                "batch_size": 1,
                "include_all_applicable_attacks": True,
                "target_text": None,
                "extra_options": {},
            },
        }
        full_result = {
            "framework_runs": {
                "foolbox": {
                    "status": "completed",
                    "framework": "foolbox",
                    "attack_results": [],
                }
            },
            "notes": [],
        }
        mode_result = {
            "status": "completed",
            "framework": "foolbox",
            "attack_count": 2,
            "successful_attack_count": 0,
            "clean_prediction": {"label_name": "website"},
            "attack_results": [
                {
                    "attack_name": "SaltAndPepperNoiseAttack",
                    "status": "completed",
                    "success": False,
                    "prediction_changed": False,
                    "selected_epsilon": 0.16,
                    "epsilons": [0.02, 0.08, 0.16],
                    "success_by_epsilon": [False, False, False],
                    "clean_label_name": "website",
                    "adversarial_label_name": "website",
                    "perturbation_linf": 0.09,
                    "perturbation_l2": 0.16,
                    "rationale": "Decision-based attack.",
                },
                {
                    "attack_name": "L2AdditiveGaussianNoiseAttack",
                    "status": "completed",
                    "success": False,
                    "prediction_changed": False,
                    "selected_epsilon": 1.0,
                    "epsilons": [0.25, 0.5, 1.0],
                    "success_by_epsilon": [False, False, False],
                    "clean_label_name": "website",
                    "adversarial_label_name": "website",
                    "perturbation_linf": 0.01,
                    "perturbation_l2": 0.70,
                    "rationale": "Noise attack.",
                },
            ],
            "artifacts": {},
        }

        html = _render_mode_summary_html(job_record, full_result, "blackbox", mode_result)

        self.assertIn("Foolbox Attack Results", html)
        self.assertIn("SaltAndPepperNoiseAttack", html)
        self.assertIn("L2AdditiveGaussianNoiseAttack", html)
        self.assertIn("Selected Epsilon", html)
        self.assertIn("Success by Epsilon", html)

    def test_pyrit_mode_summary_rows_include_behavior_classification(self) -> None:
        job_record = {
            "job_id": f"pyrit_rows_{uuid.uuid4().hex[:8]}",
            "job_name": "pyrit rows fixture",
            "wrapper_id": None,
            "model": {
                "model_id": "tinyllama:1.1b-chat",
                "source_type": "api",
                "source_value": "http://127.0.0.1:11434/api/generate",
                "task_family": "text-generation",
                "modality": "text",
            },
            "configuration": {
                "execution_backend": "api_based",
                "scan_modes": ["blackbox"],
                "frameworks": ["pyrit"],
                "reports": ["json", "html", "txt_log"],
                "sample_path": "",
                "min_samples": 1,
                "max_iter": 1,
                "batch_size": 1,
                "include_all_applicable_attacks": True,
                "target_text": "PYRIT TEST",
                "extra_options": {},
            },
        }
        framework_payload = {
            "status": "completed",
            "framework": "pyrit",
            "attack_type": "multi_prompt_sending",
            "attack_types": ["multi_prompt_sending"],
            "turn_count": 4,
            "artifacts": {},
        }
        full_result = {"framework_runs": {"pyrit": framework_payload}, "notes": []}
        mode_result = {
            "status": "completed",
            "framework": "pyrit",
            "attack_type": "multi_prompt_sending",
            "attack_types": ["multi_prompt_sending"],
            "turn_count": 4,
            "artifacts": {},
        }

        rows = _mode_specific_rows(job_record, full_result, "blackbox", mode_result)

        self.assertIn(["Behavior Classification", "multi_turn_jailbreak"], rows)
        self.assertIn(["Behavior Classification Source", "module_or_class_family_match"], rows)

    def test_pyrit_original_report_includes_behavior_classification(self) -> None:
        job_record = {
            "job_id": f"pyrit_html_{uuid.uuid4().hex[:8]}",
            "job_name": "pyrit html fixture",
            "wrapper_id": None,
            "model": {
                "model_id": "tinyllama:1.1b-chat",
                "source_type": "api",
                "source_value": "http://127.0.0.1:11434/api/generate",
                "task_family": "text-generation",
                "modality": "text",
            },
            "configuration": {
                "execution_backend": "api_based",
                "scan_modes": ["blackbox"],
                "frameworks": ["pyrit"],
                "reports": ["json", "html", "txt_log"],
                "sample_path": "",
                "min_samples": 1,
                "max_iter": 1,
                "batch_size": 1,
                "include_all_applicable_attacks": True,
                "target_text": "PYRIT TEST",
                "extra_options": {},
            },
        }
        framework_payload = {
            "status": "completed",
            "framework": "pyrit",
            "attack_type": "multi_prompt_sending",
            "attack_types": ["multi_prompt_sending"],
            "objective": "PYRIT TEST",
            "turn_count": 4,
            "profile": "text",
            "artifacts": {},
        }
        full_result = {"framework_runs": {"pyrit": framework_payload}, "notes": []}
        mode_result = {
            "status": "completed",
            "framework": "pyrit",
            "attack_type": "multi_prompt_sending",
            "attack_types": ["multi_prompt_sending"],
            "objective": "PYRIT TEST",
            "turn_count": 4,
            "profile": "text",
            "artifacts": {},
        }

        html = _render_mode_summary_html(job_record, full_result, "blackbox", mode_result)

        self.assertIn("Behavior Classification", html)
        self.assertIn("multi_turn_jailbreak", html)

    def test_art_mode_summary_rows_include_attack_counts(self) -> None:
        job_record = {
            "job_id": f"art_rows_{uuid.uuid4().hex[:8]}",
            "job_name": "art rows fixture",
            "wrapper_id": "hf_ocr_art_adapter",
            "model": {
                "model_id": "microsoft/trocr-small-printed",
                "source_type": "hf",
                "source_value": "microsoft/trocr-small-printed",
                "task_family": "ocr",
                "modality": "vision",
            },
            "configuration": {
                "execution_backend": "python_process_wrapped",
                "scan_modes": ["blackbox", "whitebox"],
                "frameworks": ["art"],
                "reports": ["json", "html", "txt_log"],
                "sample_path": "data/demo/ocr_sample.png",
                "min_samples": 1,
                "max_iter": 5,
                "batch_size": 1,
                "include_all_applicable_attacks": True,
                "target_text": "ATTACK TEST",
                "extra_options": {},
            },
        }
        framework_payload = {
            "status": "completed",
            "framework": "art",
            "report": {
                "attack_inventory": [
                    {"attack_name": "FastGradientMethod", "decision": "RUN", "reason": "Supported."},
                    {"attack_name": "ProjectedGradientDescent", "decision": "RUN", "reason": "Supported."},
                ],
                "per_attack_results": [
                    {"attack_name": "FastGradientMethod", "status": "RUN", "transcript_changed": True, "target_matched": False},
                    {"attack_name": "ProjectedGradientDescent", "status": "RUN", "transcript_changed": True, "target_matched": False},
                ],
            },
        }
        full_result = {"framework_runs": {"art": framework_payload}}
        mode_result = {"status": "completed", "framework": "art", "artifacts": {}}

        rows = _mode_specific_rows(job_record, full_result, "whitebox", mode_result)

        self.assertIn(["Attack Count", 2], rows)
        self.assertIn(["Attack Inventory Count", 2], rows)
        self.assertIn(["Changed Output Count", 2], rows)
        self.assertIn(["Target Matched Count", 0], rows)

    def test_art_original_report_includes_attack_details_section(self) -> None:
        job_record = {
            "job_id": f"art_html_{uuid.uuid4().hex[:8]}",
            "job_name": "art html fixture",
            "wrapper_id": "hf_ocr_art_adapter",
            "model": {
                "model_id": "microsoft/trocr-small-printed",
                "source_type": "hf",
                "source_value": "microsoft/trocr-small-printed",
                "task_family": "ocr",
                "modality": "vision",
            },
            "configuration": {
                "execution_backend": "python_process_wrapped",
                "scan_modes": ["blackbox", "whitebox"],
                "frameworks": ["art"],
                "reports": ["json", "html", "txt_log"],
                "sample_path": "data/demo/ocr_sample.png",
                "min_samples": 1,
                "max_iter": 5,
                "batch_size": 1,
                "include_all_applicable_attacks": True,
                "target_text": "ATTACK TEST",
                "extra_options": {},
            },
        }
        framework_payload = {
            "status": "completed",
            "framework": "art",
            "report": {
                "attack_inventory": [
                    {"attack_name": "FastGradientMethod", "decision": "RUN", "reason": "Supported."},
                    {"attack_name": "ProjectedGradientDescent", "decision": "RUN", "reason": "Supported."},
                ],
                "per_attack_results": [
                    {
                        "attack_name": "FastGradientMethod",
                        "status": "RUN",
                        "clean_transcript": "HELLO",
                        "adversarial_transcript": "HXLLO",
                        "transcript_changed": True,
                        "target_matched": False,
                        "perturbation_linf": 0.005,
                        "runtime_sec": 0.5,
                        "attack_parameters": {"eps": 0.005},
                    },
                    {
                        "attack_name": "ProjectedGradientDescent",
                        "status": "RUN",
                        "clean_transcript": "HELLO",
                        "adversarial_transcript": "WORLD",
                        "transcript_changed": True,
                        "target_matched": False,
                        "perturbation_linf": 0.005,
                        "runtime_sec": 0.8,
                        "attack_parameters": {"eps": 0.005, "max_iter": 5},
                    },
                ],
            },
        }
        full_result = {"framework_runs": {"art": framework_payload}, "notes": []}
        mode_result = {"status": "completed", "framework": "art", "artifacts": {}}

        html = _render_mode_summary_html(job_record, full_result, "whitebox", mode_result)

        self.assertIn("ART Attack Results", html)
        self.assertIn("FastGradientMethod", html)
        self.assertIn("ProjectedGradientDescent", html)
        self.assertIn("Attack Parameters", html)
        self.assertIn("Perturbation L-inf", html)

    def test_art_normalized_payload_respects_mode_scope(self) -> None:
        job_record = {
            "job_id": f"art_scope_{uuid.uuid4().hex[:8]}",
            "job_name": "art scope fixture",
            "wrapper_id": "hf_ocr_art_adapter",
            "model": {
                "model_id": "microsoft/trocr-small-printed",
                "source_type": "hf",
                "source_value": "microsoft/trocr-small-printed",
                "task_family": "ocr",
                "modality": "vision",
            },
            "configuration": {
                "execution_backend": "python_process_wrapped",
                "scan_modes": ["blackbox", "whitebox"],
                "frameworks": ["art"],
                "reports": ["json", "html", "txt_log"],
                "sample_path": "data/demo/ocr_sample.png",
                "min_samples": 1,
                "max_iter": 5,
                "batch_size": 1,
                "include_all_applicable_attacks": True,
                "target_text": "ATTACK TEST",
                "extra_options": {},
            },
        }
        framework_payload = {
            "status": "completed",
            "framework": "art",
            "report": {
                "attack_inventory": [
                    {"attack_name": "FastGradientMethod", "decision": "RUN", "reason": "Supported."},
                    {"attack_name": "ProjectedGradientDescent", "decision": "RUN", "reason": "Supported."},
                ],
                "per_attack_results": [
                    {"attack_name": "FastGradientMethod", "status": "RUN", "transcript_changed": True, "target_matched": False, "perturbation_linf": 0.02},
                    {"attack_name": "ProjectedGradientDescent", "status": "RUN", "transcript_changed": True, "target_matched": False, "perturbation_linf": 0.02},
                ],
            },
            "artifacts": {},
        }
        full_result = {"framework_runs": {"art": framework_payload}}
        blackbox_mode = {
            "status": "completed",
            "message": "Recorded the clean vision-classification baseline used by the ART run.",
            "clean_result": {"label": "website"},
            "artifacts": {},
        }
        whitebox_mode = {
            "status": "completed",
            "framework": "art",
            "report": framework_payload["report"],
            "artifacts": {},
        }

        blackbox_payload = _build_normalized_severity_payload(job_record, full_result, "blackbox", blackbox_mode)
        whitebox_payload = _build_normalized_severity_payload(job_record, full_result, "whitebox", whitebox_mode)

        self.assertEqual(blackbox_payload["overall_normalized_verdict"]["finding_count"], 0)
        self.assertEqual(whitebox_payload["overall_normalized_verdict"]["finding_count"], 2)
        self.assertEqual(whitebox_payload["normalized_findings"][0]["tool_attack_label"], "FastGradientMethod")

    def test_art_blackbox_original_report_does_not_render_whitebox_attack_section(self) -> None:
        job_record = {
            "job_id": f"art_blackbox_{uuid.uuid4().hex[:8]}",
            "job_name": "art blackbox baseline fixture",
            "wrapper_id": "hf_ocr_art_adapter",
            "model": {
                "model_id": "microsoft/trocr-small-printed",
                "source_type": "hf",
                "source_value": "microsoft/trocr-small-printed",
                "task_family": "ocr",
                "modality": "vision",
            },
            "configuration": {
                "execution_backend": "python_process_wrapped",
                "scan_modes": ["blackbox", "whitebox"],
                "frameworks": ["art"],
                "reports": ["json", "html", "txt_log"],
                "sample_path": "data/demo/ocr_sample.png",
                "min_samples": 1,
                "max_iter": 5,
                "batch_size": 1,
                "include_all_applicable_attacks": True,
                "target_text": "ATTACK TEST",
                "extra_options": {},
            },
        }
        framework_payload = {
            "status": "completed",
            "framework": "art",
            "report": {
                "attack_inventory": [
                    {"attack_name": "FastGradientMethod", "decision": "RUN", "reason": "Supported."},
                    {"attack_name": "ProjectedGradientDescent", "decision": "RUN", "reason": "Supported."},
                ],
                "per_attack_results": [
                    {"attack_name": "FastGradientMethod", "status": "RUN", "transcript_changed": True},
                    {"attack_name": "ProjectedGradientDescent", "status": "RUN", "transcript_changed": True},
                ],
            },
        }
        full_result = {"framework_runs": {"art": framework_payload}, "notes": []}
        blackbox_mode = {
            "status": "completed",
            "message": "Recorded the clean vision-classification baseline used by the ART run.",
            "clean_result": {"label": "website"},
            "artifacts": {},
        }
        html = _render_mode_summary_html(job_record, full_result, "blackbox", blackbox_mode)

        self.assertNotIn("ART Attack Results", html)
        self.assertIn("Mode Role", html)
        self.assertIn("baseline only", html)

    def test_art_normalized_report_includes_blocked_skipped_attacks(self) -> None:
        job_record = {
            "job_id": f"art_skipped_{uuid.uuid4().hex[:8]}",
            "job_name": "art skipped fixture",
            "wrapper_id": "hf_speech_to_text_art_adapter",
            "model": {
                "model_id": "openai/whisper-tiny.en",
                "source_type": "hf",
                "source_value": "openai/whisper-tiny.en",
                "task_family": "speech-to-text",
                "modality": "audio",
            },
            "configuration": {
                "execution_backend": "python_process_wrapped",
                "scan_modes": ["whitebox"],
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
        }
        framework_payload = {
            "status": "completed",
            "framework": "art",
            "report": {
                "attack_inventory": [
                    {"attack_name": "ImperceptibleASRPyTorch", "decision": "BLOCKED_BY_RESOURCES", "reason": "CUDA required."},
                ],
                "per_attack_results": [],
                "skipped_attacks": [
                    {"attack_name": "ImperceptibleASRPyTorch", "decision": "BLOCKED_BY_RESOURCES", "reason": "CUDA required."},
                ],
            },
            "artifacts": {},
        }
        full_result = {"framework_runs": {"art": framework_payload}, "notes": []}
        whitebox_mode = {
            "status": "completed",
            "framework": "art",
            "report": framework_payload["report"],
            "artifacts": {},
        }

        payload = _build_normalized_severity_payload(job_record, full_result, "whitebox", whitebox_mode)
        normalized_html = _render_normalized_severity_html(payload)

        self.assertEqual(payload["overall_normalized_verdict"]["finding_count"], 0)
        self.assertEqual(payload["non_scored_attacks"][0]["tool_attack_label"], "ImperceptibleASRPyTorch")
        self.assertEqual(payload["severity_mapping_log"][0]["final_severity"], "not_scored")
        self.assertIn("Blocked / Skipped Attacks", normalized_html)
        self.assertIn("ImperceptibleASRPyTorch", normalized_html)
        self.assertIn("CUDA required.", normalized_html)


if __name__ == "__main__":
    unittest.main()
