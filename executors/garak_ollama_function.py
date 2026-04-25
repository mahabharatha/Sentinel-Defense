from __future__ import annotations

import json
import os
from typing import Any
from urllib import error, request


TARGET_ERROR_PREFIX = "GARAK_TARGET_ERROR:"


def _coerce_positive_int(value: str | None, *, default: int) -> int:
    try:
        parsed = int(value) if value is not None else default
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def generate(prompt: str, **_: Any) -> str:
    endpoint = os.environ.get("GARAK_OLLAMA_ENDPOINT", "http://127.0.0.1:11434/api/generate")
    model = os.environ.get("GARAK_OLLAMA_MODEL", "tinyllama:1.1b-chat")
    timeout = _coerce_positive_int(os.environ.get("GARAK_OLLAMA_TIMEOUT"), default=120)
    num_predict = _coerce_positive_int(os.environ.get("GARAK_OLLAMA_NUM_PREDICT"), default=256)
    payload = json.dumps(
        {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {"num_predict": num_predict},
        }
    ).encode("utf-8")
    req = request.Request(endpoint, data=payload, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with request.urlopen(req, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
    except (TimeoutError, error.URLError, json.JSONDecodeError) as exc:
        return f"{TARGET_ERROR_PREFIX} {type(exc).__name__}: {exc}"
    return str(body.get("response") or body.get("message", {}).get("content") or "")
