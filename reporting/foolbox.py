"""HTML renderer for Foolbox adversarial attack results.

Extracted from executor.py during the reporting-layer split (Task 5).
Callers should import from this module, e.g.
    from sentinel.reporting.foolbox import _render_foolbox_attack_results_html
The old `from sentinel.executor import _render_foolbox_attack_results_html` still works via a re-export
shim in executor.py.
"""
from __future__ import annotations

import base64
import html
import json
import mimetypes
import re
from pathlib import Path
from typing import Any

from .utils import _first_present, _html_scalar, _html_table, _RawHtml, _resolve_mode_framework_payload


def _render_foolbox_attack_results_html(mode_result: dict[str, Any], framework_payload: dict[str, Any]) -> str:
    attack_rows = mode_result.get("attack_results") or framework_payload.get("attack_results") or []
    if not attack_rows:
        return '<p class="muted">No Foolbox attack results were recorded.</p>'

    rows = []
    detail_blocks = []
    for index, attack in enumerate(attack_rows, start=1):
        if not isinstance(attack, dict):
            continue
        attack_name = str(attack.get("attack_name") or f"attack_{index}")
        rows.append(
            [
                attack_name,
                attack.get("status") or "-",
                bool(attack.get("success")),
                bool(attack.get("prediction_changed")),
                attack.get("selected_epsilon") if attack.get("selected_epsilon") is not None else "-",
                attack.get("clean_label_name") or attack.get("clean_label_id") or "-",
                attack.get("adversarial_label_name") or attack.get("adversarial_label_id") or "-",
                attack.get("perturbation_linf") if attack.get("perturbation_linf") is not None else "-",
                attack.get("perturbation_l2") if attack.get("perturbation_l2") is not None else "-",
            ]
        )
        detail_blocks.append(
            "\n".join(
                [
                    "<details>",
                    f"<summary>{html.escape(attack_name)}</summary>",
                    _html_table(
                        ["Field", "Value"],
                        [
                            ["Attack Name", attack_name],
                            ["Status", attack.get("status") or "-"],
                            ["Success", bool(attack.get("success"))],
                            ["Prediction Changed", bool(attack.get("prediction_changed"))],
                            ["Attack Type", attack.get("attack_type") or attack.get("scope") or "-"],
                            ["Rationale", attack.get("rationale") or "-"],
                            ["Selected Epsilon", attack.get("selected_epsilon") if attack.get("selected_epsilon") is not None else "-"],
                            ["Epsilons", ", ".join(str(value) for value in (attack.get("epsilons") or [])) or "-"],
                            ["Success by Epsilon", ", ".join(str(bool(value)) for value in (attack.get("success_by_epsilon") or [])) or "-"],
                            ["Clean Label", attack.get("clean_label_name") or attack.get("clean_label_id") or "-"],
                            ["Adversarial Label", attack.get("adversarial_label_name") or attack.get("adversarial_label_id") or "-"],
                            ["Perturbation L-inf", attack.get("perturbation_linf") if attack.get("perturbation_linf") is not None else "-"],
                            ["Perturbation L2", attack.get("perturbation_l2") if attack.get("perturbation_l2") is not None else "-"],
                        ],
                    ),
                    "</details>",
                ]
            )
        )

    return "".join(
        [
            _html_table(
                [
                    "Attack",
                    "Status",
                    "Success",
                    "Prediction Changed",
                    "Selected Epsilon",
                    "Clean Label",
                    "Adversarial Label",
                    "Perturbation L-inf",
                    "Perturbation L2",
                ],
                rows,
            ),
            "".join(detail_blocks),
        ]
    )
