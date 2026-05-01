# Sentinel Defense — Troubleshooting Guide

A symptom-to-root-cause-to-fix lookup for every failure mode we have hit
during install, smoke, and operator usage. Every entry includes (a) the
exact diagnostic you should look at first, (b) the underlying cause, and
(c) the remediation. If your problem is not here, see §10 for how to file a
new entry.

---

## 1. Server fails to start

### 1.1 `ModuleNotFoundError: No module named 'sentinel'` or `whitebox_scan_platform`

**Diagnostic.** `python run.py` exits with the trace above.

**Cause.** Either you launched without activating the venv, or you launched
from outside the repo root and the package isn't importable.

**Fix.**

```bash
cd /path/to/sentinel
source venv/bin/activate
python run.py
```

`run.py` is intentionally permissive — it adds the parent of the repo to
`sys.path` and chdirs to the repo root before booting uvicorn — so as long
as you launch it directly the imports resolve. If you're trying to run from
a script that doesn't go through `run.py`, set `PYTHONPATH` to the repo
parent.

### 1.2 `NameError: name 'BUILTIN_WRAPPERS' is not defined` (or any similar name)

**Diagnostic.** Server boot trace points at a line inside `jobs.py`,
`templates.py`, `preflight.py`, or the `reporting/` modules.

**Cause.** A stale `__pycache__/` from a pre-Task-7 layout. The split
modules use lazy imports for executor-resident symbols; an old `.pyc` may
still embed direct top-level imports.

**Fix.**

```bash
find . -type d -name __pycache__ -not -path './venv/*' -exec rm -rf {} +
python run.py
```

### 1.3 `Address already in use` on port 8000

**Cause.** A prior `run.py` is still running.

**Fix.** `pkill -f run.py` then relaunch. Or use a different port:
`python run.py --port 8001`.

---

## 2. Wrappers / templates / runtime status look wrong

### 2.1 Wrapper Capability Matrix is empty or stale

**Cause.** The wrapper cache wasn't invalidated after a registration or
file change.

**Fix.** Click **Refresh Data** in the Create Scan Job toolbar. If that
doesn't pick the new wrapper up, restart the server (the cache is
process-local).

### 2.2 Built-in template doesn't appear in the Template select

**Cause.** `data/builtin_templates.json` is missing or malformed, or
`data/templates.json` shadowed it with an older index.

**Fix.** Verify the file:

```bash
python -c "import json; print(len(json.load(open('data/builtin_templates.json'))))"
```

You should see `15`. If not, restore from git or re-extract via the bundled
copy in `sentinel_patch/`.

### 2.3 Local Service Health says Ollama is unreachable

**Cause.** Ollama daemon isn't running, or it's bound to a different host.

**Fix.**

```bash
ollama serve
curl -sS http://127.0.0.1:11434/api/tags | jq '.models[].name'
```

If the curl returns models, Sentinel will surface them on the next refresh
of `/api/options`. If your daemon binds to a non-default host, set
`extra_options.pyrit_endpoint_uri` / `garak_endpoint_uri` to the matching
URL in your template.

### 2.4 A model is loaded in Ollama but the chips don't show in Local Service Health

**Cause.** The orchestrator probes only the canonical endpoint
`http://127.0.0.1:11434/api/tags`. A non-standard binding won't be picked
up by the always-on probe; only the per-job preflight will then surface it.

**Fix.** Either rebind Ollama to the canonical host or accept that the
status panel is generic and rely on per-job preflight readiness.

---

## 3. Scans fail or produce empty reports

### 3.1 `FileNotFoundError(2, 'No such file or directory')` from a vision wrapper

**Diagnostic.** `data/jobs/<job_id>.json` shows
`framework_runs.art.error = "FileNotFoundError(2, 'No such file or
directory')"` for templates 2/3/5/6 (OCR / vision-classification / Foolbox).

**Cause.** The template references `data/demo/ocr_sample.png`, which is not
shipped — it must be generated. Older versions of the orchestrator chdir'd
to the repo's parent at boot, so the relative path `data/demo/...` resolved
outside the repo.

**Fix.**

1. Confirm `run.py` keeps the CWD at the repo root (it does, post-Task-9).
2. Generate the sample image if missing:
   ```bash
   python -c "
   import struct, zlib
   from pathlib import Path
   def chunk(t,d): return struct.pack('>I', len(d)) + t + d + struct.pack('>I', zlib.crc32(t+d) & 0xffffffff)
   W,H=64,64
   rows=b''
   for y in range(H):
       for x in range(W):
           in_bar=(18<=x<=19 or 32<=x<=33 or 46<=x<=47) and 20<=y<=44
           on_baseline=14<=x<=50 and 47<=y<=48
           rows += b'\\x00\\x00\\x00' if (in_bar or on_baseline) else b'\\xff\\xff\\xff'
   raw=b''.join(b'\\x00'+rows[y*W*3:(y+1)*W*3] for y in range(H))
   p=Path('data/demo/ocr_sample.png'); p.parent.mkdir(parents=True, exist_ok=True)
   p.write_bytes(b'\\x89PNG\\r\\n\\x1a\\n' + chunk(b'IHDR', struct.pack('>IIBBBBB',W,H,8,2,0,0,0)) + chunk(b'IDAT', zlib.compress(raw,9)) + chunk(b'IEND', b''))
   print('wrote', p)
   "
   ```
3. Repeat for the WAV demo if your job uses speech-to-text:
   ```bash
   python -c "
   import math, struct, wave
   from pathlib import Path
   p = Path('rhel_art_audio_demo/samples/demo_tone.wav'); p.parent.mkdir(parents=True, exist_ok=True)
   with wave.open(str(p), 'wb') as wf:
       wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(16000)
       wf.writeframes(b''.join(struct.pack('<h', int(0.3*32767*math.sin(2*math.pi*440*i/16000))) for i in range(16000)))
   print('wrote', p)
   "
   ```

### 3.2 `LocalEntryNotFoundError: ... outgoing traffic has been disabled`

**Diagnostic.** TextAttack / ART / Foolbox subprocess fails with the above
inside `data/<framework>_runs/<job_id>/reports/run_log.txt`.

**Cause.** The framework runner is in `HF_HUB_OFFLINE=1` mode and the
required HF model is not in `data/textattack_cache/`.

**Fix.**

```bash
python scripts/warm_hf_cache.py --include-vision --include-audio
```

If your network blocks `huggingface.co` or the download stalls, install
`hf_transfer` first:

```bash
pip install hf_transfer
HF_HUB_ENABLE_HF_TRANSFER=1 python scripts/warm_hf_cache.py --include-vision --include-audio
```

### 3.3 BAE / TextFooler / PWWS fails with `LookupError: Resource 'averaged_perceptron_tagger_eng' not found`

**Diagnostic.** TextAttack run log ends with the LookupError above.

**Cause.** NLTK's POS tagger corpus is missing. TextAttack's BAE recipe
loads `WordSwapMaskedLM` which in turn loads `bert-base-uncased` *and*
needs the NLTK perceptron tagger for its grammaticality constraint.

**Fix.**

```bash
bash scripts/install_nltk_offline.sh
```

The script uses `curl` (with the OS certificate store) to fetch the
upstream NLTK zip files into `venv/nltk_data/`. Verify with:

```bash
ls venv/nltk_data/taggers/averaged_perceptron_tagger_eng/
```

### 3.4 PyRIT subprocess fails with `ModuleNotFoundError: No module named 'whitebox_scan_platform'`

**Diagnostic.** `data/pyrit_runs/<job_id>/reports/run_log.txt` shows the
above immediately after the `python -m
whitebox_scan_platform.executors.pyrit_runner` command.

**Cause.** The PyRIT subprocess runs with `cwd=attack_dir` (a deep nested
folder under `data/pyrit_runs/...`), which doesn't put the repo root on
sys.path.

**Fix.** Already fixed post-Task-7: `executors/pyrit_executor.py` now
prepends the repo root to `PYTHONPATH` in the subprocess env. If you are
seeing this on a fresh checkout, make sure your `executors/pyrit_executor.py`
contains the `repo_root = str(Path(__file__).resolve().parents[1])` block
near the env setup. If your file predates the fix, pull the latest.

### 3.5 ART/Foolbox/TextAttack speech demo "completes" but produces empty summaries

**Diagnostic.** `framework_runs.art.status == "completed"` but
`result.blackbox.summary` is `{}` and the run is suspiciously fast (< 5
seconds).

**Cause.** The demo audio file (`rhel_art_audio_demo/samples/demo_tone.wav`)
is missing; the speech-to-text adapter swallows missing-input cases without
crashing.

**Fix.** Same as §3.1 step 3 — generate the WAV file.

---

## 4. Smoke driver issues

### 4.1 `smoke_all_builtins.py` looks stuck after launching

**Cause.** Output is piped through `tee` so Python is block-buffering
stdout. Per-template progress only appears after the buffer fills.

**Fix.** `run_full_smoke.sh` already sets `PYTHONUNBUFFERED=1` and `-u`.
You should see `launched job_id=…, polling…` and `… still running at 15s`
heartbeats. If you don't, you're on an older copy — pull the latest.

### 4.2 Validator flags every run with `missing severity_counts/findings keys`

**Cause.** Old validator that used the wrong keys. The real payload uses
`overall_normalized_verdict` and `normalized_findings`.

**Fix.** Pull the latest `scripts/smoke_all_builtins.py`. The current
validator checks `{overall_normalized_verdict, normalized_findings,
framework, scan_mode}` and accepts the rest as optional.

### 4.3 Validator flags Garak template with `ERROR:` markers

**Cause.** Old validator did substring match on `ERROR:`. The real
synthesized log embeds the JSON config string `"target_error_marker":
"GARAK_TARGET_ERROR:"` which is not an actual error.

**Fix.** Pull the latest. The validator now line-anchors and skips JSON
value lines; markers are limited to `Traceback (most recent call last):`,
`Uncaught exception`, `FATAL:`, `AssertionError:`.

### 4.4 Smoke driver complains "server not reachable"

**Cause.** No live server, or Sentinel is bound to a different port.

**Fix.** `bash scripts/run_full_smoke.sh` handles server startup itself.
If you are running the driver directly, start the server first or pass
`--host http://127.0.0.1:8888`.

---

<a id="ssl-certificate-failures"></a>
## 5. SSL / certificate failures

Symptoms include
`CERTIFICATE_VERIFY_FAILED: unable to get local issuer certificate
(_ssl.c:1006)`
during `python -m nltk.download(...)` or HF model downloads.

**Cause.** The Python distribution on macOS (and some Linux builds) does
not ship a CA bundle that NLTK / HF can find through Python's stdlib SSL
stack. Behind corporate proxies, the situation is worse.

**Fix.**

1. Install certifi (already a transitive dep): `pip install certifi`.
2. Export its bundle path before running scripts that touch the network:
   ```bash
   export SSL_CERT_FILE=$(python -m certifi)
   export REQUESTS_CA_BUNDLE=$(python -m certifi)
   ```
3. The cache warmer script does this automatically when `certifi` is
   importable.
4. For NLTK specifically, prefer `bash scripts/install_nltk_offline.sh`
   which uses `curl` (OS cert store) and bypasses Python's SSL stack
   entirely.
5. If you are behind a corporate MITM proxy, get the corporate root
   certificate from your IT team and append it to the certifi bundle.

---

## 6. UI / browser issues

### 6.1 "Live Job Status" stays empty after launching a scan

**Cause.** Auto-refresh is disabled or you're polling the wrong job.

**Fix.** Tick the **Auto refresh every 5s** checkbox at the top of Live
Job Status, or click **Refresh Data**. Job records appear newest-first.

### 6.2 Reports show `Sentinel RedTeam Console` instead of the new brand

**Cause.** Old report HTML was generated under the previous brand. New
scans pick up the rebrand automatically.

**Fix.** Re-run the scan, or accept that historical reports are
immutable evidence (which they should be).

### 6.3 Page looks unstyled / broken

**Cause.** Stale browser cache after a UI refactor.

**Fix.** Hard reload: `Cmd+Shift+R` (macOS) / `Ctrl+Shift+R` (Linux/Windows
WSL).

### 6.4 The Terminal View tree is empty for a job

**Cause.** Either no real text log exists yet (job still running, or
framework wrote no log), or the synthesized log fell into a single
"Header" section with nothing else.

**Fix.** Click **Load Terminal**. If still empty, check
`data/<framework>_runs/<job_id>/reports/run_log.txt` directly.

---

## 7. Performance / capacity

### 7.1 Big scan takes much longer than expected

**Likely cause.** First-time HF download in-line with the run, or a
constraint downgrade triggered by missing optional deps.

**Fix.** Pre-warm with `scripts/warm_hf_cache.py`. For TextAttack
specifically, install `tensorflow_hub` if you want full BAE constraints
(otherwise the runner's `runtime_safe_constraint_downgrade` kicks in).

### 7.2 OS-level "too many open files" during big PyRIT runs

**Cause.** PyRIT spawns one subprocess per attack and each opens log files.

**Fix.** Bump `ulimit -n 4096` in the shell that runs the server.

### 7.3 Atomic write contention warnings

**Cause.** Two writers attempting to update the same job record at the
same time.

**Fix.** Already prevented post-Task-10 via `JOB_WRITE_LOCK` (RLock) +
tempfile + os.replace. If you are seeing the warning anyway, pull the
latest `storage.py` and `executor.py`.

---

## 8. Tests

### 8.1 `pytest` collects nothing

**Cause.** You're outside the repo root, or your venv lacks `pytest`.

**Fix.** `cd` to the repo root, `source venv/bin/activate`, then `pytest
tests/ -v`.

### 8.2 `test_end_to_end.py` or `test_executor_runtime.py` fails

**Cause.** These are integration tests requiring a live server, Ollama,
and warm caches.

**Fix.** Skip them for fast iteration:

```bash
pytest tests/ -v --ignore=tests/test_end_to_end.py --ignore=tests/test_executor_runtime.py
```

Run them once before shipping.

---

## 9. Diagnostics that always help

When filing a bug, include:

```bash
python --version
git rev-parse HEAD
cat requirements.txt | head
pip freeze | grep -E '(fastapi|pydantic|garak|pyrit|textattack|art|foolbox|transformers|torch|nltk)'
ls data/jobs | tail -5
tail -40 data/job_reports/<failing_job_id>/reports/blackbox_summary_run_log.txt
tail -40 data/<framework>_runs/<failing_job_id>/reports/run_log.txt
```

Plus a copy of the failing job's JSON record from `data/jobs/<id>.json`.

---

## 10. Adding a new troubleshooting entry

If you hit something not in this list:

1. Capture the exact stack trace and the offending file:line.
2. Trace the cause to a single file.
3. Add a new section under the most relevant top-level category, in the
   same Diagnostic / Cause / Fix shape.
4. Cross-reference any related code change in [RELEASE_NOTES.md](RELEASE_NOTES.md).
