from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch


PACKAGE_DIR = Path(__file__).resolve().parents[1]
PROJECT_PARENT = PACKAGE_DIR.parent
if str(PROJECT_PARENT) not in sys.path:
    sys.path.insert(0, str(PROJECT_PARENT))

from whitebox_scan_platform.executors.garak_executor import _resolve_generator_options
from whitebox_scan_platform.executors.garak_executor import _build_command
from whitebox_scan_platform.executors.garak_executor import _summarize_jsonl_report
from whitebox_scan_platform.executors.garak_ollama_function import TARGET_ERROR_PREFIX
from whitebox_scan_platform.executors.garak_ollama_function import generate
from whitebox_scan_platform.executors.garak_runner import _resolve_request_timeout


class GarakExecutorTests(unittest.TestCase):
    def test_ollama_endpoint_gets_non_streaming_response_defaults(self) -> None:
        job_record = {
            "job_id": "ollama-defaults",
            "job_name": "ollama defaults",
            "model": {
                "model_id": "tinyllama-ollama",
                "source_type": "api",
                "source_value": "http://127.0.0.1:11434/api/generate",
                "task_family": "text-generation",
                "modality": "text",
            },
            "configuration": {
                "execution_backend": "api_based",
                "frameworks": ["garak"],
                "extra_options": {},
            },
        }

        generator_options, endpoint_uri = _resolve_generator_options(job_record)

        self.assertEqual(endpoint_uri, "http://127.0.0.1:11434/api/generate")
        rest_options = generator_options["rest.RestGenerator"]
        self.assertEqual(rest_options["response_json_field"], "response")
        self.assertTrue(rest_options["response_json"])
        self.assertEqual(rest_options["req_template_json_object"]["prompt"], "$INPUT")
        self.assertFalse(rest_options["req_template_json_object"]["stream"])

    def test_ollama_endpoint_preserves_explicit_stream_setting(self) -> None:
        job_record = {
            "job_id": "ollama-explicit-stream",
            "job_name": "ollama explicit stream",
            "model": {
                "model_id": "tinyllama-ollama",
                "source_type": "api",
                "source_value": "http://127.0.0.1:11434/api/generate",
                "task_family": "text-generation",
                "modality": "text",
            },
            "configuration": {
                "execution_backend": "api_based",
                "frameworks": ["garak"],
                "extra_options": {
                    "garak_request_template_json_object": {
                        "prompt": "$INPUT",
                        "model": "tinyllama:1.1b-chat",
                        "stream": True,
                    },
                    "garak_response_json_field": "response",
                },
            },
        }

        generator_options, _ = _resolve_generator_options(job_record)
        rest_options = generator_options["rest.RestGenerator"]
        self.assertTrue(rest_options["req_template_json_object"]["stream"])

    def test_build_command_uses_local_garak_runner(self) -> None:
        with patch("whitebox_scan_platform.executors.garak_executor._garak_rest_generator_available", return_value=False):
            command = _build_command(
                job_record={
                    "configuration": {
                        "extra_options": {
                            "garak_probes": "test.Blank",
                            "garak_generations": 1,
                        },
                        "batch_size": 1,
                    }
                },
                generator_option_file=Path("/tmp/generator_options.json"),
                report_prefix=Path("/tmp/garak"),
                endpoint_uri="http://127.0.0.1:11434/api/generate",
            )

        self.assertEqual(command[0], sys.executable)
        self.assertEqual(command[1:3], ["-m", "whitebox_scan_platform.executors.garak_runner"])
        self.assertIn("function.Single", command)
        self.assertIn("whitebox_scan_platform.executors.garak_ollama_function#generate", command)
        self.assertNotIn("--generator_option_file", command)
        self.assertNotIn("--narrow_output", command)

    def test_build_command_uses_version_safe_local_test_generator(self) -> None:
        command = _build_command(
            job_record={
                "configuration": {
                    "extra_options": {
                        "garak_model_type": "test.Blank",
                        "garak_model_name": "blank",
                        "garak_probes": "test.Blank",
                        "garak_generations": 1,
                    },
                    "batch_size": 1,
                }
            },
            generator_option_file=Path("/tmp/generator_options.json"),
            report_prefix=Path("/tmp/garak"),
            endpoint_uri="blank",
        )

        self.assertIn("test.Blank", command)
        self.assertIn("blank", command)
        self.assertNotIn("--generator_option_file", command)
        self.assertNotIn("--narrow_output", command)

    def test_resolve_request_timeout_prefers_response_timeout(self) -> None:
        timeout = _resolve_request_timeout({"response_timeout": 120}, 10)
        self.assertEqual(timeout, 120)

    def test_resolve_request_timeout_falls_back_to_current(self) -> None:
        timeout = _resolve_request_timeout({}, 10)
        self.assertEqual(timeout, 10)

    def test_summarize_jsonl_counts_target_errors(self) -> None:
        report_path = PACKAGE_DIR / "data" / "tmp_garak_target_error_report.jsonl"
        self.addCleanup(lambda: report_path.exists() and report_path.unlink())
        report_path.write_text(
            "\n".join(
                [
                    '{"entry_type":"attempt","prompt":"x","outputs":["ok"]}',
                    '{"entry_type":"attempt","prompt":"y","outputs":["GARAK_TARGET_ERROR: TimeoutError: timed out"]}',
                    "",
                ]
            ),
            encoding="utf-8",
        )

        summary = _summarize_jsonl_report(report_path)

        self.assertEqual(summary["prompt_count"], 2)
        self.assertEqual(summary["output_count"], 2)
        self.assertEqual(summary["target_error_count"], 1)

    def test_ollama_bridge_returns_marker_on_timeout(self) -> None:
        with patch("whitebox_scan_platform.executors.garak_ollama_function.request.urlopen", side_effect=TimeoutError("timed out")):
            response = generate("hello")

        self.assertTrue(response.startswith(TARGET_ERROR_PREFIX))
        self.assertIn("TimeoutError", response)


if __name__ == "__main__":
    unittest.main()
