from __future__ import annotations

import argparse
import csv
import html
import importlib.util
import json
from pathlib import Path
from typing import Any


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a narrow TextAttack text-classification job.")
    parser.add_argument("--config", required=True, help="Path to the normalized runner config JSON file.")
    parser.add_argument("--output-dir", required=True, help="Directory where TextAttack artifacts should be written.")
    return parser.parse_args()


def _read_config(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _recipe_builder(recipe_name: str):
    from textattack.attack_recipes import BAEGarg2019
    from textattack.attack_recipes import DeepWordBugGao2018
    from textattack.attack_recipes import PWWSRen2019
    from textattack.attack_recipes import TextFoolerJin2019

    mapping = {
        "textfooler": TextFoolerJin2019,
        "pwws": PWWSRen2019,
        "bae": BAEGarg2019,
        "deepwordbug": DeepWordBugGao2018,
    }
    builder = mapping.get(recipe_name)
    if builder is None:
        supported = ", ".join(sorted(mapping))
        raise ValueError(f"Unsupported TextAttack recipe '{recipe_name}'. Supported values: {supported}.")
    return builder


def _nltk_resource_available(resource_path: str) -> bool:
    try:
        import nltk

        nltk.data.find(resource_path)
        return True
    except LookupError:
        return False


def _remove_constraint_by_class_name(attack: Any, class_name: str) -> bool:
    constraints = list(getattr(attack, "constraints", []) or [])
    filtered = [constraint for constraint in constraints if constraint.__class__.__name__ != class_name]
    if len(filtered) == len(constraints):
        return False
    attack.constraints = filtered
    return True


def _module_available(module_name: str) -> bool:
    return importlib.util.find_spec(module_name) is not None


def _apply_runtime_safe_recipe_adjustments(recipe_name: str, attack: Any) -> list[str]:
    warnings: list[str] = []
    if recipe_name in {"textfooler", "pwws"} and not _nltk_resource_available("taggers/averaged_perceptron_tagger_eng/"):
        if _remove_constraint_by_class_name(attack, "PartOfSpeech"):
            warnings.append(
                "Removed TextAttack PartOfSpeech constraint because NLTK resource "
                "'averaged_perceptron_tagger_eng' is not installed."
            )
    if recipe_name in {"textfooler", "bae"} and not _module_available("tensorflow_hub"):
        if _remove_constraint_by_class_name(attack, "UniversalSentenceEncoder"):
            warnings.append(
                "Removed TextAttack UniversalSentenceEncoder constraint because optional dependency "
                "'tensorflow_hub' is not installed."
            )
    return warnings


def _load_text_examples(config: dict[str, Any]) -> list[dict[str, Any]]:
    target_text = str(config.get("target_text") or "").strip()
    if target_text:
        return [{"text": target_text, "label": None}]

    sample_path = Path(str(config.get("sample_path") or "")).expanduser()
    if not sample_path.exists() or not sample_path.is_file():
        raise ValueError(f"TextAttack sample path was not found: {sample_path}")

    suffix = sample_path.suffix.lower()
    if suffix == ".txt":
        rows = [line.strip() for line in sample_path.read_text(encoding="utf-8", errors="replace").splitlines()]
        return [{"text": row, "label": None} for row in rows if row]
    if suffix == ".json":
        payload = json.loads(sample_path.read_text(encoding="utf-8"))
        if isinstance(payload, list):
            examples = []
            for row in payload:
                if isinstance(row, str):
                    text = row.strip()
                    if text:
                        examples.append({"text": text, "label": None})
                elif isinstance(row, dict):
                    text = str(row.get("text") or "").strip()
                    if text:
                        examples.append({"text": text, "label": row.get("label")})
            return examples
        raise ValueError("TextAttack JSON sample files must contain a list of strings or objects with 'text'.")
    if suffix == ".jsonl":
        examples = []
        for raw_line in sample_path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            row = json.loads(line)
            if isinstance(row, str):
                text = row.strip()
                if text:
                    examples.append({"text": text, "label": None})
            elif isinstance(row, dict):
                text = str(row.get("text") or "").strip()
                if text:
                    examples.append({"text": text, "label": row.get("label")})
        return examples
    if suffix == ".csv":
        examples = []
        with sample_path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                text = str(row.get("text") or row.get("input") or "").strip()
                if text:
                    examples.append({"text": text, "label": row.get("label")})
        return examples
    raise ValueError("TextAttack sample path currently supports .txt, .json, .jsonl, and .csv files.")


def _predict_label(model, tokenizer, text: str) -> tuple[int, str]:
    import torch

    encoded = tokenizer(text, return_tensors="pt", truncation=True)
    with torch.no_grad():
        outputs = model(**encoded)
    logits = outputs.logits
    label_idx = int(logits.argmax(dim=-1).item())
    label_text = str((getattr(model.config, "id2label", {}) or {}).get(label_idx, label_idx))
    return label_idx, label_text


def _attack_status(result: Any) -> str:
    class_name = result.__class__.__name__.lower()
    if "successful" in class_name:
        return "successful"
    if "maximized" in class_name:
        return "maximized"
    if "skip" in class_name:
        return "skipped"
    if "fail" in class_name:
        return "failed"
    return class_name or "unknown"


def _safe_output_text(result_payload: Any) -> str:
    if result_payload is None:
        return ""
    output = getattr(result_payload, "output", None)
    if output is None:
        return ""
    if isinstance(output, (list, tuple)):
        return ", ".join(str(item) for item in output)
    return str(output)


def _safe_attacked_text(result_payload: Any) -> str:
    if result_payload is None:
        return ""
    attacked_text = getattr(result_payload, "attacked_text", None)
    text = getattr(attacked_text, "text", None)
    return str(text or "")


def _word_change_count(original_text: str, perturbed_text: str) -> int:
    original_tokens = original_text.split()
    perturbed_tokens = perturbed_text.split()
    limit = max(len(original_tokens), len(perturbed_tokens))
    changed = 0
    for index in range(limit):
        left = original_tokens[index] if index < len(original_tokens) else ""
        right = perturbed_tokens[index] if index < len(perturbed_tokens) else ""
        if left != right:
            changed += 1
    return changed


def _word_change_ratio(original_text: str, perturbed_text: str) -> float:
    original_token_count = max(len(original_text.split()), 1)
    return round(_word_change_count(original_text, perturbed_text) / original_token_count, 3)


def _summarize_examples(examples: list[dict[str, Any]]) -> dict[str, Any]:
    summary = {
        "total_examples": len(examples),
        "successful": 0,
        "failed": 0,
        "skipped": 0,
        "maximized": 0,
        "other": 0,
        "label_flip_count": 0,
        "success_rate": 0.0,
        "average_queries": 0.0,
        "average_word_changes": 0.0,
        "average_word_change_ratio": 0.0,
    }
    query_values: list[float] = []
    changed_word_values: list[float] = []
    changed_ratio_values: list[float] = []
    for row in examples:
        status = str(row.get("status") or "").strip().lower()
        if status in summary:
            summary[status] += 1
        else:
            summary["other"] += 1
        if row.get("label_flipped"):
            summary["label_flip_count"] += 1
        queries = row.get("num_queries")
        if isinstance(queries, (int, float)):
            query_values.append(float(queries))
        changed_words = row.get("word_changes")
        if isinstance(changed_words, (int, float)):
            changed_word_values.append(float(changed_words))
        change_ratio = row.get("word_change_ratio")
        if isinstance(change_ratio, (int, float)):
            changed_ratio_values.append(float(change_ratio))
    total_examples = summary["total_examples"]
    if total_examples:
        summary["success_rate"] = round((summary["successful"] + summary["maximized"]) / total_examples, 3)
    if query_values:
        summary["average_queries"] = round(sum(query_values) / len(query_values), 2)
    if changed_word_values:
        summary["average_word_changes"] = round(sum(changed_word_values) / len(changed_word_values), 2)
    if changed_ratio_values:
        summary["average_word_change_ratio"] = round(sum(changed_ratio_values) / len(changed_ratio_values), 3)
    return summary


def _write_html_report(destination: Path, payload: dict[str, Any]) -> None:
    summary = payload.get("summary") or {}
    examples = payload.get("examples") or []
    def cell(value: Any) -> str:
        return html.escape("" if value is None else str(value))

    def block(value: Any) -> str:
        return f"<div class='cell-block'>{cell(value or '-')}</div>"

    rows = [
        "<!DOCTYPE html>",
        "<html lang='en'>",
        "<head>",
        "<meta charset='utf-8' />",
        "<meta name='viewport' content='width=device-width, initial-scale=1' />",
        "<title>TextAttack Report</title>",
        "<style>",
        "/* Bharath Srinivasan | Sentinel Adversarial Orchestrator TextAttack report presentation. Proprietary material. */",
        ":root { --bg: #07111f; --panel: rgba(11, 23, 39, 0.94); --panel-strong: #10233a; --ink: #eef7ff; --ink-soft: #a9bfd6; --line: rgba(112, 170, 221, 0.16); --line-strong: rgba(112, 170, 221, 0.28); --accent: #2fb6ff; --success: #23c788; --warn: #ffb347; --danger: #ff6a7c; }",
        "* { box-sizing: border-box; }",
        "body { margin: 0; font-family: 'Avenir Next', 'Segoe UI', sans-serif; color: var(--ink); background: radial-gradient(circle at top left, rgba(47, 182, 255, 0.16), transparent 24%), linear-gradient(180deg, #040a14 0%, #081323 46%, #0a1729 100%); }",
        ".page { max-width: 1180px; margin: 0 auto; padding: 24px; }",
        ".hero { background: radial-gradient(circle at top right, rgba(94, 204, 255, 0.24), transparent 32%), linear-gradient(135deg, rgba(255,255,255,0.08), transparent 34%), linear-gradient(135deg, #071323 0%, #0d233e 38%, #103157 72%, #0a6db3 100%); color: white; border: 1px solid rgba(122, 191, 255, 0.18); border-radius: 24px; padding: 28px; margin-bottom: 18px; box-shadow: 0 24px 72px rgba(0, 0, 0, 0.32); }",
        ".hero h1 { margin: 0 0 8px; font-size: 30px; }",
        ".hero-meta { display: flex; gap: 12px; flex-wrap: wrap; color: rgba(238, 247, 255, 0.78); font-size: 14px; }",
        ".status { display: inline-block; margin-top: 12px; padding: 8px 14px; border-radius: 999px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em; font-size: 12px; background: rgba(47, 182, 255, 0.14); border: 1px solid rgba(47, 182, 255, 0.2); color: var(--accent); }",
        "section { background: var(--panel); border: 1px solid var(--line); border-radius: 18px; padding: 18px; margin-bottom: 16px; box-shadow: 0 22px 54px rgba(2, 7, 15, 0.34); }",
        "table { width: 100%; border-collapse: collapse; font-size: 14px; background: rgba(8, 18, 31, 0.34); border-radius: 14px; overflow: hidden; }",
        "th, td { border-bottom: 1px solid var(--line); padding: 10px 12px; text-align: left; vertical-align: top; }",
        "th { background: rgba(16, 35, 58, 0.92); text-transform: uppercase; font-size: 12px; letter-spacing: 0.05em; color: var(--ink-soft); }",
        ".cell-block { white-space: pre-wrap; word-break: break-word; max-height: 280px; overflow: auto; background: rgba(6, 17, 31, 0.92); border: 1px solid var(--line); border-radius: 12px; padding: 10px; font-family: ui-monospace, 'SFMono-Regular', Menlo, monospace; font-size: 12px; color: #d8e9fb; }",
        "</style>",
        "</head>",
        "<body><div class='page'>",
        "<header class='hero'>",
        "<h1>TextAttack Report</h1>",
        f"<div class='hero-meta'><span>Recipe: {cell(payload.get('recipe', ''))}</span><span>Goal Function: {cell(payload.get('goal_function', ''))}</span><span>Input Source: {cell(payload.get('input_source', ''))}</span></div>",
        f"<div class='status'>{cell(payload.get('status', 'unknown'))}</div>",
        "</header>",
        "<section><h2>Summary</h2>",
        "<table>",
        "<tr><th>Field</th><th>Value</th></tr>",
    ]
    for key in (
        "total_examples",
        "successful",
        "failed",
        "skipped",
        "maximized",
        "other",
        "label_flip_count",
        "success_rate",
        "average_queries",
        "average_word_changes",
        "average_word_change_ratio",
    ):
        rows.append(f"<tr><td>{cell(key)}</td><td>{cell(summary.get(key, 0))}</td></tr>")
    rows.extend(
        [
            "</table></section>",
            "<section><h2>Examples</h2>",
            "<table>",
            "<tr><th>#</th><th>Status</th><th>Original Text</th><th>Adversarial Text</th><th>Original Label</th><th>Adversarial Label</th><th>Queries</th><th>Words Changed</th><th>Change Ratio</th><th>Label Flipped</th></tr>",
        ]
    )
    for row in examples:
        rows.append(
            "<tr>"
            f"<td>{cell(row.get('index'))}</td>"
            f"<td>{cell(row.get('status'))}</td>"
            f"<td>{block(row.get('original_text', ''))}</td>"
            f"<td>{block(row.get('perturbed_text', ''))}</td>"
            f"<td>{cell(row.get('original_label_text', ''))}</td>"
            f"<td>{cell(row.get('perturbed_label_text', ''))}</td>"
            f"<td>{cell(row.get('num_queries', ''))}</td>"
            f"<td>{cell(row.get('word_changes', ''))}</td>"
            f"<td>{cell(row.get('word_change_ratio', ''))}</td>"
            f"<td>{cell(row.get('label_flipped', ''))}</td>"
            "</tr>"
        )
    rows.extend(
        [
            "</table></section>",
            "<section><h2>Raw Result JSON</h2>",
            f"<div class='cell-block'>{cell(json.dumps(payload, indent=2, sort_keys=True))}</div>",
            "</section>",
            "</div></body></html>",
            "",
        ]
    )
    destination.write_text("\n".join(rows), encoding="utf-8")


def main() -> int:
    args = _parse_args()
    config_path = Path(args.config).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    config = _read_config(config_path)

    from textattack.attack_args import AttackArgs
    from textattack.attacker import Attacker
    from textattack.datasets import Dataset
    from textattack.models.wrappers import HuggingFaceModelWrapper
    from transformers import AutoModelForSequenceClassification
    from transformers import AutoTokenizer

    model_info = config.get("model") or {}
    model_source = str(model_info.get("source_value") or model_info.get("model_id") or "").strip()
    if not model_source:
        raise ValueError("TextAttack runner requires a model source value.")

    model = AutoModelForSequenceClassification.from_pretrained(model_source)
    tokenizer = AutoTokenizer.from_pretrained(model_source)
    model.eval()
    model_wrapper = HuggingFaceModelWrapper(model, tokenizer)

    recipe_name = str(config.get("recipe") or "textfooler")
    recipe_builder = _recipe_builder(recipe_name)
    attack = recipe_builder.build(model_wrapper)
    dependency_warnings = _apply_runtime_safe_recipe_adjustments(recipe_name, attack)
    query_budget = config.get("query_budget")
    if query_budget is not None and hasattr(getattr(attack, "goal_function", None), "query_budget"):
        attack.goal_function.query_budget = int(query_budget)

    examples = _load_text_examples(config)
    max_examples = int(config.get("max_examples") or 1)
    examples = examples[:max_examples]
    if not examples:
        raise ValueError("TextAttack runner received zero attackable examples.")
    input_source = "target_text" if str(config.get("target_text") or "").strip() else str(config.get("sample_path") or "sample_path")

    dataset_rows = []
    resolved_examples = []
    for example in examples:
        text = str(example.get("text") or "").strip()
        if not text:
            continue
        label = example.get("label")
        if label is None or str(label).strip() == "":
            label_idx, label_text = _predict_label(model, tokenizer, text)
        else:
            label_idx = int(label)
            label_text = str((getattr(model.config, "id2label", {}) or {}).get(label_idx, label_idx))
        dataset_rows.append((text, label_idx))
        resolved_examples.append({"text": text, "label": label_idx, "label_text": label_text})

    dataset = Dataset(dataset_rows)
    attack_args = AttackArgs(
        num_examples=len(dataset_rows),
        query_budget=int(query_budget) if query_budget is not None else None,
        disable_stdout=True,
        silent=True,
    )
    attacker = Attacker(attack, dataset, attack_args)
    serialized_examples: list[dict[str, Any]] = []
    for index, result in enumerate(attacker.attack_dataset(), start=1):
        original_result = getattr(result, "original_result", None)
        perturbed_result = getattr(result, "perturbed_result", None)
        original_text = _safe_attacked_text(original_result) or resolved_examples[index - 1]["text"]
        perturbed_text = _safe_attacked_text(perturbed_result) or original_text
        original_label_idx = resolved_examples[index - 1]["label"]
        original_label_text = resolved_examples[index - 1]["label_text"]
        perturbed_output = _safe_output_text(perturbed_result)
        label_flipped = bool(perturbed_output) and str(perturbed_output).strip() != str(original_label_text).strip()
        serialized_examples.append(
            {
                "index": index,
                "status": _attack_status(result),
                "original_text": original_text,
                "perturbed_text": perturbed_text,
                "original_label": original_label_idx,
                "original_label_text": original_label_text,
                "perturbed_label_text": perturbed_output,
                "num_queries": getattr(result, "num_queries", None),
                "word_changes": _word_change_count(original_text, perturbed_text),
                "word_change_ratio": _word_change_ratio(original_text, perturbed_text),
                "label_flipped": label_flipped,
                "original_output": _safe_output_text(original_result),
                "perturbed_output": perturbed_output,
                "result_class": result.__class__.__name__,
            }
        )

    payload = {
        "framework": "textattack",
        "status": "completed",
        "job_id": config.get("job_id"),
        "job_name": config.get("job_name"),
        "recipe": config.get("recipe"),
        "goal_function": config.get("goal_function"),
        "constraint_mode": config.get("constraint_mode"),
        "max_examples": max_examples,
        "query_budget": config.get("query_budget"),
        "model": model_info,
        "input_source": input_source,
        "input_preview": resolved_examples[0]["text"] if resolved_examples else "",
        "summary": _summarize_examples(serialized_examples),
        "examples": serialized_examples,
        "dependency_warnings": dependency_warnings,
    }

    results_json_path = output_dir / "results.json"
    report_html_path = output_dir / "report.html"
    results_json_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    _write_html_report(report_html_path, payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
