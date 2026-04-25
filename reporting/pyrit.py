"""HTML renderers for PyRIT attack output, transcripts, and multimodal context.

Extracted from executor.py during the reporting-layer split (Task 5).
Callers should import from this module, e.g.
    from sentinel.reporting.pyrit import _render_pyrit_outcome_html
The old `from sentinel.executor import _render_pyrit_outcome_html` still works via a re-export
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

from .utils import _first_present, _html_scalar, _html_table, _RawHtml


def _html_block(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return '<span class="muted">-</span>'
    return f"<div class='cell-block'>{html.escape(text)}</div>"


def _render_local_image_preview_html(path_value: Any, *, alt_text: str) -> str:
    path_text = str(path_value or "").strip()
    if not path_text:
        return '<span class="muted">Preview unavailable</span>'

    image_path = Path(path_text).expanduser()
    try:
        if not image_path.exists() or not image_path.is_file():
            return '<span class="muted">Preview unavailable</span>'
        if image_path.stat().st_size > 5 * 1024 * 1024:
            return '<span class="muted">Preview unavailable (image exceeds 5 MB embed limit)</span>'
        mime_type, _ = mimetypes.guess_type(image_path.name)
        if not mime_type or not mime_type.startswith("image/"):
            return '<span class="muted">Preview unavailable</span>'
        encoded_image = base64.b64encode(image_path.read_bytes()).decode("ascii")
    except OSError:
        return '<span class="muted">Preview unavailable</span>'

    return "".join(
        [
            "<div class='image-preview'>",
            f"<img src='data:{html.escape(mime_type)};base64,{encoded_image}' alt='{html.escape(alt_text)}' />",
            "</div>",
        ]
    )


def _render_pyrit_media_block(media_items: Any) -> str:
    if not isinstance(media_items, list) or not media_items:
        return '<span class="muted">-</span>'
    html_parts: list[str] = []
    for item in media_items:
        if not isinstance(item, dict):
            html_parts.append(_html_block(item))
            continue
        data_type = str(item.get("data_type") or "media")
        value = str(item.get("value") or item.get("image_path") or "").strip()
        label = f"[{data_type}] {value}" if value else f"[{data_type}]"
        item_parts = [_html_block(label)]
        if data_type == "image_path" and value:
            item_parts.append(_render_local_image_preview_html(value, alt_text="PyRIT media preview"))
        html_parts.append("".join(item_parts))
    return "".join(html_parts)


def _render_pyrit_attack_runs_html(sample_bundle: dict[str, Any] | None) -> str:
    if not sample_bundle:
        return '<p class="muted">No PyRIT attack-run details were recorded.</p>'
    attack_runs = sample_bundle.get("attack_runs") or []
    if not attack_runs:
        return '<p class="muted">No PyRIT attack-run details were recorded.</p>'
    rows = []
    for attack_run in attack_runs:
        if not isinstance(attack_run, dict):
            continue
        platform = attack_run.get("platform_evaluation") or {}
        metadata = attack_run.get("result_metadata") or {}
        rows.append(
            [
                attack_run.get("attack_type") or "-",
                attack_run.get("status") or "-",
                metadata.get("outcome") or "-",
                platform.get("verdict") or "-",
                platform.get("severity") or "-",
                attack_run.get("target_uri") or "-",
            ]
        )
    heading = f"Selected transcript source: {sample_bundle.get('selected_attack_type') or '-'}"
    return f"<p class='section-note'>{html.escape(heading)}</p>" + _html_table(
        ["Attack", "Status", "Raw Outcome", "Platform Verdict", "Severity", "Target URI"],
        rows,
    )


def _render_pyrit_conversation_topology_html(sample_bundle: dict[str, Any] | None) -> str:
    if not sample_bundle:
        return '<p class="muted">No PyRIT conversation topology details were recorded.</p>'

    metadata = sample_bundle.get("result_metadata") or {}
    related_conversations = metadata.get("related_conversations") or []
    rows = [
        ["Primary Conversation ID", sample_bundle.get("conversation_id") or "-"],
        ["Active Conversation IDs", ", ".join(metadata.get("active_conversation_ids") or []) or "-"],
        ["All Conversation IDs", ", ".join(metadata.get("all_conversation_ids") or []) or "-"],
        ["Pruned Conversation IDs", ", ".join(metadata.get("pruned_conversation_ids") or []) or "-"],
        ["Related Conversation Count", len(related_conversations)],
    ]
    html_parts = [_html_table(["Field", "Value"], rows)]
    if related_conversations:
        related_rows = [
            [
                item.get("conversation_id") or "-",
                item.get("conversation_type") or "-",
                item.get("description") or "-",
            ]
            for item in related_conversations
        ]
        html_parts.append(_html_table(["Conversation ID", "Type", "Description"], related_rows))
    return "".join(html_parts)


def _render_pyrit_console_output_html(sample_bundle: dict[str, Any] | None) -> str:
    if not sample_bundle:
        return '<p class="muted">No PyRIT console output was recorded.</p>'
    printer_output = str(sample_bundle.get("printer_output") or "").strip()
    if not printer_output:
        return '<p class="muted">No PyRIT console output was recorded.</p>'
    return f"<pre>{html.escape(printer_output)}</pre>"


def _render_pyrit_transcript_html(sample_bundle: dict[str, Any] | None) -> str:
    if not sample_bundle or not sample_bundle.get("samples"):
        return '<p class="muted">No PyRIT transcript entries were recorded.</p>'

    note_parts = [
        f"Showing {sample_bundle.get('displayed_turns', 0)} of {sample_bundle.get('total_turns', 0)} transcript entries."
    ]
    if sample_bundle.get("path"):
        note_parts.append(f"Source: {sample_bundle['path']}")

    header_html = "".join(
        f"<th>{html.escape(header)}</th>"
        for header in ["Seq", "Role", "Text", "Media", "Response Error", "Metadata"]
    )
    rows_html = []
    for sample in sample_bundle["samples"]:
        metadata = sample.get("metadata") or {}
        rows_html.append(
            "".join(
                [
                    "<tr>",
                    f"<td>{html.escape(str(sample.get('sequence', '-')))}</td>",
                    f"<td>{html.escape(str(sample.get('role', 'unknown')))}</td>",
                    f"<td>{_html_block(sample.get('text'))}</td>",
                    f"<td>{_render_pyrit_media_block(sample.get('media'))}</td>",
                    f"<td>{_html_block(sample.get('response_error'))}</td>",
                    f"<td>{_html_block(json.dumps(metadata, indent=2, sort_keys=True) if metadata else '-')}</td>",
                    "</tr>",
                ]
            )
        )

    return "".join(
        [
            f"<p class='section-note'>{html.escape(' '.join(note_parts))}</p>",
            "<table>",
            f"<thead><tr>{header_html}</tr></thead>",
            "<tbody>",
            "".join(rows_html),
            "</tbody></table>",
        ]
    )


def _render_pyrit_outcome_html(sample_bundle: dict[str, Any] | None) -> str:
    if not sample_bundle:
        return '<p class="muted">No PyRIT outcome details were recorded.</p>'

    metadata = sample_bundle.get("result_metadata") or {}
    platform_evaluation = sample_bundle.get("platform_evaluation") or {}
    objective_scorer = metadata.get("objective_scorer") or {}
    last_score = metadata.get("last_score") or {}
    profile = str(sample_bundle.get("profile") or "text").strip().lower() or "text"
    is_multimodal = profile == "multimodal"
    expected_response_label = "Primary Required Word / Phrase" if is_multimodal else "Expected Response"
    expected_literal_label = "Primary Required Literal" if is_multimodal else "Expected Literal"
    required_literals_label = "Required Words / Phrases" if is_multimodal else "Required Literals"
    matched_required_literals_label = "Matched Required Words / Phrases" if is_multimodal else "Matched Required Literals"
    missing_required_literals_label = "Missing Required Words / Phrases" if is_multimodal else "Missing Required Literals"
    all_required_literals_label = "All Required Words / Phrases Present" if is_multimodal else "All Required Literals Present"
    seed_image_source = str(sample_bundle.get("seed_image_source") or "").strip()
    if seed_image_source == "sample_path_fallback":
        seed_image_source_display = "Sample Path fallback"
    elif seed_image_source == "pyrit_seed_image_path":
        seed_image_source_display = "PyRIT Seed Image Path"
    else:
        seed_image_source_display = seed_image_source or "-"
    required_literals = platform_evaluation.get("required_literals") or sample_bundle.get("expected_responses") or []
    matched_required_literals = platform_evaluation.get("matched_required_literals") or []
    missing_required_literals = platform_evaluation.get("missing_required_literals") or []
    forbidden_literals = platform_evaluation.get("forbidden_literals") or sample_bundle.get("forbidden_literals") or []
    matched_forbidden_literals = platform_evaluation.get("matched_forbidden_literals") or []
    rows = [
        ["Status", sample_bundle.get("status") or "-"],
        ["Profile", sample_bundle.get("profile") or "text"],
        ["Attack Type", sample_bundle.get("attack_type") or "-"],
        ["Attacks Requested", ", ".join(sample_bundle.get("attack_types") or []) or "-"],
        ["Attack Run Count", sample_bundle.get("attack_run_count") or 0],
        ["Objective", sample_bundle.get("objective") or "-"],
        ["Seed Text", sample_bundle.get("seed_text") or "-"],
        ["Configured Seed Image Path", sample_bundle.get("configured_seed_image_path") or "-"],
        ["Seed Image Path", sample_bundle.get("seed_image_path") or "-"],
        ["Seed Image Source", seed_image_source_display],
        ["Follow-up Text", sample_bundle.get("follow_up_text") or "-"],
        ["Max Turns", sample_bundle.get("max_turns") or "-"],
        [expected_response_label, sample_bundle.get("expected_response") or "-"],
        ["Target URI", sample_bundle.get("target_uri") or "-"],
        ["Model Name", sample_bundle.get("model_name") or "-"],
        ["Objective Scorer Mode", sample_bundle.get("objective_scorer_mode") or "auto"],
        ["Configured Request Timeout (sec)", sample_bundle.get("request_timeout_sec") or "-"],
        ["Retry Attempts on Failure", sample_bundle.get("max_attempts_on_failure") or 0],
        ["Conversation ID", sample_bundle.get("conversation_id") or "-"],
        ["Total Turns", sample_bundle.get("total_turns", 0)],
        ["Displayed Turns", sample_bundle.get("displayed_turns", 0)],
        ["Total Exchanges", sample_bundle.get("total_exchanges", 0)],
        ["Attack Identifier", metadata.get("attack_identifier") or "-"],
        ["Executed Turns", metadata.get("executed_turns") or "-"],
        ["Execution Time (ms)", metadata.get("execution_time_ms") or "-"],
        ["PyRIT Raw Outcome", metadata.get("outcome") or "-"],
        ["PyRIT Raw Outcome Reason", metadata.get("outcome_reason") or "-"],
        ["Objective Scorer Enabled", objective_scorer.get("enabled") if objective_scorer.get("enabled") is not None else "-"],
        ["Objective Scorer Reason", objective_scorer.get("reason") or "-"],
        ["Objective Scorer Expected Literal", objective_scorer.get("expected_literal") or "-"],
        [f"Objective Scorer {required_literals_label}", ", ".join(objective_scorer.get("required_literals") or []) or "-"],
        ["PyRIT Raw Score Value", last_score.get("score_value") if last_score else "-"],
        ["PyRIT Raw Score Description", last_score.get("score_value_description") if last_score else "-"],
        ["PyRIT Raw Score Rationale", last_score.get("score_rationale") if last_score else "-"],
        ["Platform Verdict", platform_evaluation.get("verdict") or "-"],
        ["Platform Severity", platform_evaluation.get("severity") or "-"],
        ["Platform Score", platform_evaluation.get("score") if platform_evaluation.get("score") is not None else "-"],
        ["Platform Rationale", platform_evaluation.get("rationale") or "-"],
        [expected_literal_label, platform_evaluation.get("expected_literal") or "-"],
        [required_literals_label, ", ".join(required_literals) or "-"],
        [matched_required_literals_label, ", ".join(matched_required_literals) or "-"],
        [missing_required_literals_label, ", ".join(missing_required_literals) or "-"],
        [all_required_literals_label, platform_evaluation.get("all_required_literals_present") if platform_evaluation.get("all_required_literals_present") is not None else "-"],
        ["Any Required Literal Present", platform_evaluation.get("any_required_literal_present") if platform_evaluation.get("any_required_literal_present") is not None else "-"],
        ["Required Literals In Order", platform_evaluation.get("ordered_required_literals_present") if platform_evaluation.get("ordered_required_literals_present") is not None else "-"],
        ["Contains Expected Literal", platform_evaluation.get("contains_expected_literal") if platform_evaluation.get("contains_expected_literal") is not None else "-"],
        ["Matched Expected Literal", platform_evaluation.get("matched_expected_literal") if platform_evaluation.get("matched_expected_literal") is not None else "-"],
        ["Forbidden Literals", ", ".join(forbidden_literals) or "-"],
        ["Matched Forbidden Literals", ", ".join(matched_forbidden_literals) or "-"],
        ["Max Words Allowed", platform_evaluation.get("expected_max_words") if platform_evaluation.get("expected_max_words") is not None else sample_bundle.get("expected_max_words") or "-"],
        ["Observed Word Count", platform_evaluation.get("word_count") if platform_evaluation.get("word_count") is not None else "-"],
        ["Within Word Limit", platform_evaluation.get("within_word_limit") if platform_evaluation.get("within_word_limit") is not None else "-"],
        ["Max Sentences Allowed", platform_evaluation.get("expected_max_sentences") if platform_evaluation.get("expected_max_sentences") is not None else sample_bundle.get("expected_max_sentences") or "-"],
        ["Observed Sentence Count", platform_evaluation.get("sentence_count") if platform_evaluation.get("sentence_count") is not None else "-"],
        ["Within Sentence Limit", platform_evaluation.get("within_sentence_limit") if platform_evaluation.get("within_sentence_limit") is not None else "-"],
        ["Structure Checks Passed", platform_evaluation.get("structure_passed") if platform_evaluation.get("structure_passed") is not None else "-"],
        ["Structure Violations", ", ".join(platform_evaluation.get("structure_violations") or []) or "-"],
        ["Refusal Detected", platform_evaluation.get("refusal_detected") if platform_evaluation.get("refusal_detected") is not None else "-"],
        ["Final Assistant Response", platform_evaluation.get("final_response") or "-"],
        ["Scored Final Response", platform_evaluation.get("scored_response_text") or "-"],
        ["Ignored Response Segments", ", ".join(platform_evaluation.get("ignored_response_segments") or []) or "-"],
        ["Source Results JSON", sample_bundle.get("path") or "-"],
    ]
    if not is_multimodal:
        rows[10:10] = [
            ["Max Backtracks", sample_bundle.get("max_backtracks") or "-"],
            ["Adversarial Target URI", sample_bundle.get("adversarial_target_uri") or "-"],
            ["Adversarial Model Name", sample_bundle.get("adversarial_model_name") or "-"],
            ["Skeleton Key Prompt Override", sample_bundle.get("skeleton_key_prompt") or "-"],
        ]
        rows.insert(19, ["Many-Shot Example Count", sample_bundle.get("many_shot_example_count") or "-"])
    return _html_table(["Field", "Value"], rows)


def _render_pyrit_multimodal_summary_html(sample_bundle: dict[str, Any] | None) -> str:
    if not sample_bundle or str(sample_bundle.get("profile") or "text").strip().lower() != "multimodal":
        return '<p class="muted">This PyRIT run used the text profile.</p>'

    platform_evaluation = sample_bundle.get("platform_evaluation") or {}
    seed_image_source = str(sample_bundle.get("seed_image_source") or "").strip()
    if seed_image_source == "sample_path_fallback":
        seed_image_source_display = "Sample Path fallback"
    elif seed_image_source == "pyrit_seed_image_path":
        seed_image_source_display = "PyRIT Seed Image Path"
    else:
        seed_image_source_display = seed_image_source or "-"

    exchanges = sample_bundle.get("exchanges") or []
    turn_flow_lines: list[str] = []
    for exchange in exchanges:
        if not isinstance(exchange, dict):
            continue
        index = exchange.get("index") or len(turn_flow_lines) + 1
        prompt = str(exchange.get("user_prompt") or "").strip()
        prompt_preview = " ".join(prompt.split())
        if len(prompt_preview) > 120:
            prompt_preview = prompt_preview[:117].rstrip() + "..."
        media_items = exchange.get("user_media") or []
        media_label = ""
        if isinstance(media_items, list) and media_items:
            media_types = []
            for item in media_items:
                if isinstance(item, dict):
                    media_types.append(str(item.get("data_type") or "media"))
            if media_types:
                media_label = f" [{', '.join(media_types)}]"
        turn_flow_lines.append(f"Turn {index}: {prompt_preview or '-'}{media_label}")

    scored_response = str(platform_evaluation.get("scored_response_text") or platform_evaluation.get("final_response") or "").strip() or "-"
    rows = [
        ["Attack", sample_bundle.get("attack_type") or "-"],
        ["Image Used", sample_bundle.get("seed_image_path") or "-"],
        ["Image Preview", _RawHtml(_render_local_image_preview_html(sample_bundle.get("seed_image_path"), alt_text="PyRIT multimodal seed image preview"))],
        ["Image Source", seed_image_source_display],
        ["Configured Image Path", sample_bundle.get("configured_seed_image_path") or "-"],
        ["Turn Flow", "\n".join(turn_flow_lines) or "-"],
        ["Required Words / Phrases", ", ".join(platform_evaluation.get("required_literals") or sample_bundle.get("expected_responses") or []) or "-"],
        ["Matched Words / Phrases", ", ".join(platform_evaluation.get("matched_required_literals") or []) or "-"],
        ["Missing Words / Phrases", ", ".join(platform_evaluation.get("missing_required_literals") or []) or "-"],
        ["Forbidden Words / Phrases", ", ".join(platform_evaluation.get("forbidden_literals") or sample_bundle.get("forbidden_literals") or []) or "-"],
        ["Matched Forbidden Words / Phrases", ", ".join(platform_evaluation.get("matched_forbidden_literals") or []) or "-"],
        ["Max Words Allowed", platform_evaluation.get("expected_max_words") if platform_evaluation.get("expected_max_words") is not None else sample_bundle.get("expected_max_words") or "-"],
        ["Observed Word Count", platform_evaluation.get("word_count") if platform_evaluation.get("word_count") is not None else "-"],
        ["Max Sentences Allowed", platform_evaluation.get("expected_max_sentences") if platform_evaluation.get("expected_max_sentences") is not None else sample_bundle.get("expected_max_sentences") or "-"],
        ["Observed Sentence Count", platform_evaluation.get("sentence_count") if platform_evaluation.get("sentence_count") is not None else "-"],
        ["Structure Checks Passed", platform_evaluation.get("structure_passed") if platform_evaluation.get("structure_passed") is not None else "-"],
        ["Verdict", platform_evaluation.get("verdict") or "-"],
        ["Severity", platform_evaluation.get("severity") or "-"],
        ["Scored Response", scored_response],
    ]
    return _html_table(["Field", "Value"], rows)


def _render_pyrit_multimodal_context_html(sample_bundle: dict[str, Any] | None) -> str:
    if not sample_bundle or str(sample_bundle.get("profile") or "text").strip().lower() != "multimodal":
        return '<p class="muted">This PyRIT run used the text profile.</p>'

    platform_evaluation = sample_bundle.get("platform_evaluation") or {}
    seed_image_source = str(sample_bundle.get("seed_image_source") or "").strip()
    if seed_image_source == "sample_path_fallback":
        seed_image_source_display = "Sample Path fallback"
    elif seed_image_source == "pyrit_seed_image_path":
        seed_image_source_display = "PyRIT Seed Image Path"
    else:
        seed_image_source_display = seed_image_source or "-"
    rows = [
        ["Profile", "multimodal (Vision-Language support only)"],
        ["Selected Transcript Source", sample_bundle.get("selected_attack_type") or "-"],
        ["Seed Text", sample_bundle.get("seed_text") or "-"],
        ["Configured Seed Image Path", sample_bundle.get("configured_seed_image_path") or "-"],
        ["Seed Image Path", sample_bundle.get("seed_image_path") or "-"],
        ["Seed Image Preview", _RawHtml(_render_local_image_preview_html(sample_bundle.get("seed_image_path"), alt_text="PyRIT multimodal context seed image preview"))],
        ["Seed Image Source", seed_image_source_display],
        ["Follow-up Text", sample_bundle.get("follow_up_text") or "-"],
        ["Required Words / Phrases", ", ".join(platform_evaluation.get("required_literals") or sample_bundle.get("expected_responses") or []) or "-"],
        ["Matched Required Words / Phrases", ", ".join(platform_evaluation.get("matched_required_literals") or []) or "-"],
        ["Missing Required Words / Phrases", ", ".join(platform_evaluation.get("missing_required_literals") or []) or "-"],
        ["All Required Words / Phrases Present", platform_evaluation.get("all_required_literals_present") if platform_evaluation.get("all_required_literals_present") is not None else "-"],
        ["Forbidden Words / Phrases", ", ".join(platform_evaluation.get("forbidden_literals") or sample_bundle.get("forbidden_literals") or []) or "-"],
        ["Matched Forbidden Words / Phrases", ", ".join(platform_evaluation.get("matched_forbidden_literals") or []) or "-"],
        ["Max Words Allowed", platform_evaluation.get("expected_max_words") if platform_evaluation.get("expected_max_words") is not None else sample_bundle.get("expected_max_words") or "-"],
        ["Observed Word Count", platform_evaluation.get("word_count") if platform_evaluation.get("word_count") is not None else "-"],
        ["Max Sentences Allowed", platform_evaluation.get("expected_max_sentences") if platform_evaluation.get("expected_max_sentences") is not None else sample_bundle.get("expected_max_sentences") or "-"],
        ["Observed Sentence Count", platform_evaluation.get("sentence_count") if platform_evaluation.get("sentence_count") is not None else "-"],
        ["Structure Checks Passed", platform_evaluation.get("structure_passed") if platform_evaluation.get("structure_passed") is not None else "-"],
        ["Structure Violations", ", ".join(platform_evaluation.get("structure_violations") or []) or "-"],
    ]
    return _html_table(["Field", "Value"], rows)


def _render_pyrit_exchange_html(sample_bundle: dict[str, Any] | None) -> str:
    if not sample_bundle or not sample_bundle.get("exchanges"):
        return '<p class="muted">No prompt / response exchanges were recorded.</p>'

    note_parts = [
        f"Showing {sample_bundle.get('displayed_exchanges', 0)} of {sample_bundle.get('total_exchanges', 0)} prompt / response exchanges."
    ]
    if sample_bundle.get("path"):
        note_parts.append(f"Source: {sample_bundle['path']}")

    header_html = "".join(
        f"<th>{html.escape(header)}</th>"
        for header in ["Exchange", "Prompt", "Prompt Media", "Response", "Response Error", "Assistant Metadata"]
    )
    rows_html = []
    for exchange in sample_bundle["exchanges"]:
        metadata = exchange.get("assistant_metadata") or {}
        rows_html.append(
            "".join(
                [
                    "<tr>",
                    f"<td>{html.escape(str(exchange.get('index', '-')))}</td>",
                    f"<td>{_html_block(exchange.get('user_prompt'))}</td>",
                    f"<td>{_render_pyrit_media_block(exchange.get('user_media'))}</td>",
                    f"<td>{_html_block(exchange.get('assistant_response'))}</td>",
                    f"<td>{_html_block(exchange.get('response_error'))}</td>",
                    f"<td>{_html_block(json.dumps(metadata, indent=2, sort_keys=True) if metadata else '-')}</td>",
                    "</tr>",
                ]
            )
        )

    return "".join(
        [
            f"<p class='section-note'>{html.escape(' '.join(note_parts))}</p>",
            "<table>",
            f"<thead><tr>{header_html}</tr></thead>",
            "<tbody>",
            "".join(rows_html),
            "</tbody></table>",
        ]
    )
