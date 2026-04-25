"""HTML renderer for IBM Adversarial Robustness Toolbox attack results.

Extracted from executor.py during the reporting-layer split (Task 5).
Callers should import from this module, e.g.
    from sentinel.reporting.art import _render_art_attack_results_html
The old `from sentinel.executor import _render_art_attack_results_html` still works via a re-export
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


def _render_art_attack_results_html(framework_payload: dict[str, Any]) -> str:
    report = framework_payload.get("report") or {}
    attack_inventory = report.get("attack_inventory") or []
    per_attack_results = report.get("per_attack_results") or []
    if not attack_inventory and not per_attack_results:
        return '<p class="muted">No ART attack results were recorded.</p>'

    parts: list[str] = []
    if attack_inventory:
        parts.append(
            _html_table(
                ["Attack", "Decision", "Reason"],
                [
                    [
                        attack.get("attack_name") if isinstance(attack, dict) else "-",
                        attack.get("decision") if isinstance(attack, dict) else "-",
                        attack.get("reason") if isinstance(attack, dict) else "-",
                    ]
                    for attack in attack_inventory
                ],
            )
        )
    if per_attack_results:
        rows = []
        detail_blocks = []
        for index, attack in enumerate(per_attack_results, start=1):
            if not isinstance(attack, dict):
                continue
            attack_name = str(attack.get("attack_name") or f"attack_{index}")
            rows.append(
                [
                    attack_name,
                    attack.get("status") or "-",
                    bool(attack.get("target_matched")),
                    bool(attack.get("prediction_changed") or attack.get("transcript_changed")),
                    attack.get("clean_transcript") or attack.get("clean_label") or "-",
                    attack.get("adversarial_transcript") or attack.get("adversarial_label") or "-",
                    attack.get("perturbation_linf") if attack.get("perturbation_linf") is not None else "-",
                ]
            )
            parameters = attack.get("attack_parameters") or {}
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
                                ["Target Matched", bool(attack.get("target_matched"))],
                                ["Prediction Changed", bool(attack.get("prediction_changed"))],
                                ["Transcript Changed", bool(attack.get("transcript_changed"))],
                                ["Clean Transcript", attack.get("clean_transcript") or "-"],
                                ["Adversarial Transcript", attack.get("adversarial_transcript") or "-"],
                                ["Perturbation L-inf", attack.get("perturbation_linf") if attack.get("perturbation_linf") is not None else "-"],
                                ["Perturbation L2", attack.get("perturbation_l2") if attack.get("perturbation_l2") is not None else "-"],
                                ["Runtime (sec)", attack.get("runtime_sec") if attack.get("runtime_sec") is not None else "-"],
                                ["Attack Parameters", json.dumps(parameters, indent=2, sort_keys=True) if parameters else "-"],
                            ],
                        ),
                        "</details>",
                    ]
                )
            )
        parts.append(
            _html_table(
                [
                    "Attack",
                    "Status",
                    "Target Matched",
                    "Changed",
                    "Clean Output",
                    "Adversarial Output",
                    "Perturbation L-inf",
                ],
                rows,
            )
        )
        parts.append("".join(detail_blocks))
    return "".join(parts)
