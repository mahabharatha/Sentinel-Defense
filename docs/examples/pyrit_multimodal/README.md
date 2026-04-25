## PyRIT Multimodal Smoke Payloads

These payloads mirror the certified Phase 1 smoke matrix for PyRIT multimodal
Vision-Language testing.

Use them with the local app server:

```bash
cd /Users/macmacmac/Documents/whitebox_scan_platform
curl -s http://127.0.0.1:8013/api/scans \
  -H "Content-Type: application/json" \
  --data-binary @docs/examples/pyrit_multimodal/01_prompt_sending_seed_image.json
```

After submission, poll the job:

```bash
curl -s http://127.0.0.1:8013/api/scans/<job_id>
```

Payloads included:

- `01_prompt_sending_seed_image.json`
- `02_prompt_sending_sample_path_fallback.json`
- `03_multi_prompt_sending_seed_image.json`
- `04_multi_prompt_sending_sample_path_fallback.json`

All four payloads assume:

- Ollama is running locally on `127.0.0.1:11434`
- `gemma3:4b` is already available
- the app server is running from the Python 3.11 environment with `pyrit`
- the image path `/Users/macmacmac/Documents/whitebox_scan_platform/docs/images/product-screenshot.png` exists
