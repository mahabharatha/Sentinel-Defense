# PyRIT Multimodal Smoke Matrix

This document defines the Phase 1 smoke matrix for the PyRIT multimodal MVP.

Scope:

- profile: `multimodal`
- modality support: Vision-Language only
- input shape: `text + image -> text`
- certified attacks in this phase:
  - `prompt_sending`
  - `multi_prompt_sending`

Non-goals for this smoke matrix:

- text-profile PyRIT attacks such as `skeleton_key`, `red_teaming`, or `crescendo`
- image generation or image-to-image targets
- hosted VLM providers
- white-box multimodal execution

## Preconditions

Before running the smoke matrix:

- the app server must run from the Python `3.11` environment that contains `pyrit`
- the selected local VLM must already work through Ollama
- the test image must exist on disk

Recommended app start command:

```bash
cd /Users/macmacmac/Documents/whitebox_scan_platform
PYTHONPATH=/Users/macmacmac/Documents .venv311/bin/python -m uvicorn whitebox_scan_platform.app:app --host 127.0.0.1 --port 8013
```

Recommended model and image for this matrix:

- model: `gemma3:4b`
- source value: `http://127.0.0.1:11434/api/generate`
- image: `/Users/macmacmac/Documents/whitebox_scan_platform/docs/images/product-screenshot.png`
- ready-to-run payloads: `docs/examples/pyrit_multimodal/`

## Shared UI Baseline

Use these shared values for every smoke case unless a row below overrides them:

- `Source Type`: `api`
- `Source Value`: `http://127.0.0.1:11434/api/generate`
- `Task Family`: `multimodal-chat`
- `Modality`: `multimodal`
- `Execution Backend`: `api_based`
- `Scan Mode`: `blackbox`
- `Framework`: `pyrit`
- `Reports`: `json`, `html`, `txt_log`
- `Min Samples`: `1`
- `Max Iter`: `1`
- `Batch Size`: `1`
- `Profile`: `multimodal`
- `Target VLM Model`: `gemma3:4b`
- `Request Timeout (sec)`: `120`
- `Retry Attempts on Failure`: `0`
- `Seed Text`: `What does this image show?`
- `Required Words / Phrases`: `screenshot, dashboard`
- `Objective Scorer Mode`: `contains_literal`

## Matrix

### Case 1

- name: `prompt_sending` with explicit seed image path
- attack: `prompt_sending`
- sample path: blank
- configured seed image path: `/Users/macmacmac/Documents/whitebox_scan_platform/docs/images/product-screenshot.png`
- target text: `Answer in one short sentence and include screenshot and dashboard.`
- follow-up text: blank

Expected result:

- job completes
- `Target URI` resolves to `/api/chat`
- `Seed Image Source` is `PyRIT Seed Image Path`
- `PyRIT Multimodal Summary` is present
- `Image Preview` is present
- `PyRIT Exchanges` shows one exchange
- `PyRIT Transcript` shows one user turn with image media and one assistant turn
- `Platform Verdict` is either `attack_succeeded` or `attack_failed`, but must not be `failed_to_execute`

### Case 2

- name: `prompt_sending` with sample-path fallback
- attack: `prompt_sending`
- sample path: `/Users/macmacmac/Documents/whitebox_scan_platform/docs/images/product-screenshot.png`
- configured seed image path: blank
- target text: `Answer in one short sentence and include screenshot and dashboard.`
- follow-up text: blank

Expected result:

- job completes
- `Seed Image Source` is `Sample Path fallback`
- `Configured Seed Image Path` stays blank in the report
- `Seed Image Path` resolves to the sample path
- image preview is visible in the standardized report
- image preview is visible in the source report

### Case 3

- name: `multi_prompt_sending` with explicit seed image path
- attack: `multi_prompt_sending`
- sample path: blank
- configured seed image path: `/Users/macmacmac/Documents/whitebox_scan_platform/docs/images/product-screenshot.png`
- target text: `Answer in one short sentence and include screenshot and dashboard.`
- follow-up text: `Answer in one short sentence and include screenshot and dashboard.`

Expected result:

- job completes
- `Attack Type` is `multi_prompt_sending`
- `Follow-up Text` is captured in both standardized and source reports
- `PyRIT Exchanges` shows two exchanges
- `PyRIT Transcript` shows four turns
- `Turn Flow` in `PyRIT Multimodal Summary` shows both user turns
- image preview is visible in the standardized report
- image preview is visible in the source report

### Case 4

- name: `multi_prompt_sending` with sample-path fallback
- attack: `multi_prompt_sending`
- sample path: `/Users/macmacmac/Documents/whitebox_scan_platform/docs/images/product-screenshot.png`
- configured seed image path: blank
- target text: `Answer in one short sentence and include screenshot and dashboard.`
- follow-up text: `Answer in one short sentence and include screenshot and dashboard.`

Expected result:

- job completes
- `Seed Image Source` is `Sample Path fallback`
- `Follow-up Text` is captured
- standardized report contains:
  - `PyRIT Multimodal Summary`
  - `Image Preview`
  - `Seed Image Preview`
  - `PyRIT Exchanges`
  - `PyRIT Transcript`
- source report contains:
  - `PyRIT Source Report`
  - `Seed Image Preview`
  - `Exchanges`
  - `Transcript`

## Required Pass Checks

To mark Phase 1 complete, all four cases should satisfy these checks:

- no case fails because of missing framework runtime
- no case fails because of missing seed image resolution
- no case fails because of profile / attack mismatch
- every case writes:
  - `blackbox_report.html`
  - `blackbox_results.json`
  - `blackbox_run_log.txt`
  - `blackbox_source_report.html`
  - `blackbox_source_results.json`
- every case has readable prompt / response content in both standardized and source artifacts
- every case shows the correct image-source label
- explicit-path and sample-path runs stay distinguishable in reports

## Notes On Verdicts

The smoke matrix is primarily checking execution integrity and report correctness.

That means a run can still count as a valid smoke pass when:

- the model responds safely
- the platform verdict is `attack_failed`

The run should only count as a smoke failure when:

- the job does not complete
- the attack fails to execute
- the transcript or exchanges are missing unexpectedly
- seed image resolution is wrong
- the reports omit required multimodal sections

## Exit Criteria For Phase 1

Phase 1 is complete when:

1. all four matrix cases have been run at least once against a real VLM target;
2. the artifact checks above pass;
3. no new multimodal defects are found during those runs.

Only after that should the project move to:

- Phase 2: multimodal UI cleanup
- Phase 3: setup and deployment hardening
