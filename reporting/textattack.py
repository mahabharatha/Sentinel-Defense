"""HTML renderers for TextAttack outcome summaries and perturbation examples.

Extracted from executor.py during the reporting-layer split (Task 5).
Callers should import from this module, e.g.
    from sentinel.reporting.textattack import _render_textattack_examples_html
The old `from sentinel.executor import _render_textattack_examples_html` still works via a re-export
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

from .pyrit import _html_block
from .utils import _first_present, _html_scalar, _html_table, _RawHtml


def _render_textattack_outcome_html(sample_bundle: dict[str, Any] | None) -> str:
    if not sample_bundle:
        return '<p class="muted">No TextAttack outcome summary was recorded.</p>'
    summary = sample_bundle.get("summary") or {}
    rows = [
        ["Model Name", sample_bundle.get("model_name") or "-"],
        ["Recipe", sample_bundle.get("recipe") or "-"],
        ["Goal Function", sample_bundle.get("goal_function") or "-"],
        ["Constraint Mode", sample_bundle.get("constraint_mode") or "-"],
        ["Max Examples", sample_bundle.get("max_examples") or "-"],
        ["Query Budget", sample_bundle.get("query_budget") or "-"],
        ["Input Source", sample_bundle.get("input_source") or "-"],
        ["Input Preview", sample_bundle.get("input_preview") or "-"],
        ["Total Examples", summary.get("total_examples", sample_bundle.get("total_examples", 0))],
        ["Successful", summary.get("successful", 0)],
        ["Failed", summary.get("failed", 0)],
        ["Skipped", summary.get("skipped", 0)],
        ["Maximized", summary.get("maximized", 0)],
        ["Success Rate", summary.get("success_rate") if summary.get("success_rate") is not None else "-"],
        ["Average Queries", summary.get("average_queries") if summary.get("average_queries") is not None else "-"],
        ["Average Words Changed", summary.get("average_word_changes") if summary.get("average_word_changes") is not None else "-"],
        ["Average Change Ratio", summary.get("average_word_change_ratio") if summary.get("average_word_change_ratio") is not None else "-"],
        ["Label Flips", summary.get("label_flip_count") if summary.get("label_flip_count") is not None else "-"],
        ["Source Results JSON", sample_bundle.get("path") or "-"],
    ]
    return _html_table(["Field", "Value"], rows)


def _render_textattack_examples_html(sample_bundle: dict[str, Any] | None) -> str:
    if not sample_bundle or not sample_bundle.get("examples"):
        return '<p class="muted">No TextAttack examples were recorded.</p>'

    total_examples = sample_bundle.get("total_examples", 0)
    displayed_examples = sample_bundle.get("displayed_examples", 0)
    note_parts = [f"Showing {displayed_examples} of {total_examples} attacked examples."]
    report_path = sample_bundle.get("path")
    if report_path:
        note_parts.append(f"Source: {report_path}")

    rows = []
    for example in sample_bundle.get("examples") or []:
        rows.append(
            [
                example.get("index") or "-",
                example.get("status") or "-",
                example.get("original_label_text") or example.get("original_label") or "-",
                example.get("perturbed_label_text") or example.get("perturbed_output") or "-",
                example.get("num_queries") or "-",
                example.get("word_changes") or "-",
                example.get("word_change_ratio") if example.get("word_change_ratio") is not None else "-",
                example.get("result_class") or "-",
                example.get("original_output") or "-",
                example.get("perturbed_output") or "-",
                _RawHtml(_html_block(example.get("original_text"))),
                _RawHtml(_html_block(example.get("perturbed_text"))),
            ]
        )

    return "".join(
        [
            f"<p class='section-note'>{html.escape(' '.join(note_parts))}</p>",
            _html_table(
                ["#", "Status", "Original Label", "Adversarial Label", "Queries", "Words Changed", "Change Ratio", "Result Class", "Original Output", "Adversarial Output", "Original Text", "Adversarial Text"],
                rows,
            ),
        ]
    )
