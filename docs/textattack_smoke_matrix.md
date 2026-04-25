# TextAttack Smoke Matrix

This document records the truthful first landing for TextAttack in this platform.

## Certified scope

- modality: `text`
- task family: `text-classification`
- execution backend: `python_process_wrapped`
- scan mode: `blackbox`
- goal function: `untargeted-classification`
- constraint mode: `default`
- supported model source: Hugging Face model id or local sequence-classification model path

Out of scope for this landing: API targets, text generation, multimodal inputs, targeted classification, and white-box TextAttack execution.

## Certified recipes

| Template | Recipe | Input shape | Certified use |
| --- | --- | --- | --- |
| `builtin_textattack_hf_smoke` | `deepwordbug` | single `target_text` | Lightest first-pass smoke run |
| `builtin_textattack_textfooler_smoke` | `textfooler` | single `target_text` | Stronger semantic substitution smoke run |
| `builtin_textattack_pwws_smoke` | `pwws` | single `target_text` | Synonym-substitution smoke run |
| `builtin_textattack_bae_smoke` | `bae` | single `target_text` | Masked-language-model smoke run |
| `builtin_textattack_sample_pack_smoke` | `deepwordbug` by default | `sample_path=data/demo/textattack_smoke_samples.jsonl` | Repeatable multi-example smoke baseline |

All certified templates use query budget `50`. The single-text templates use `textattack_max_examples=1`. The sample-pack template uses `min_samples=2` and `textattack_max_examples=2`.

## Repeatable sample-pack workflow

1. Start from `TextAttack Sample Pack Smoke`.
2. Keep `frameworks=["textattack"]`, `execution_backend=python_process_wrapped`, `scan_modes=["blackbox"]`, `task_family=text-classification`, and `modality=text`.
3. Keep the bundled sample pack at `data/demo/textattack_smoke_samples.jsonl` for the default repeatable smoke set.
4. Run the baseline once with `deepwordbug`.
5. Duplicate the job or template, then swap only `textattack_recipe` to `textfooler`, `pwws`, or `bae` for separate recipe smoke runs.

## What to check after each run

- preflight passes without scope blockers
- artifacts include `json`, `html`, and `txt_log`
- the HTML artifact renders the Sentinel-styled TextAttack report
- the report includes outcome summary and example rows
- the report renders TextAttack recipe, goal function, constraint mode, query budget, example counts, and success-rate metrics.
  - `TextAttack Success Rate`
  - `TextAttack Avg Queries`
  - `TextAttack Avg Words Changed`
  - `TextAttack Label Flips`

## Truthful operator note

This smoke matrix certifies the built-in first landing only. It does not certify every TextAttack recipe or every text model. Keep claims bounded to the shipped templates, the bundled sample pack, and the narrow text-classification path above.
