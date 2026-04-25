from __future__ import annotations

import sys
from typing import Any


def _coerce_timeout(value: Any) -> int | None:
    if value is None:
        return None
    try:
        timeout = int(value)
    except (TypeError, ValueError):
        return None
    return timeout if timeout > 0 else None


def _resolve_request_timeout(configured: dict[str, Any], current_timeout: Any) -> int | None:
    return _coerce_timeout(
        configured.get("request_timeout")
        or configured.get("response_timeout")
        or current_timeout
    )


def _patch_rest_generator_timeout() -> None:
    from garak import _config
    try:
        from garak.generators.rest import RestGenerator
    except ModuleNotFoundError:
        return

    original_init = RestGenerator.__init__

    if getattr(original_init, "_whitebox_timeout_patch", False):
        return

    def patched_init(self, uri=None, generations=10):
        original_init(self, uri=uri, generations=generations)
        configured = (_config.plugins.generators or {}).get("rest.RestGenerator") or {}
        timeout = _resolve_request_timeout(configured, getattr(self, "request_timeout", None))
        if timeout is not None:
            self.request_timeout = timeout

    patched_init._whitebox_timeout_patch = True  # type: ignore[attr-defined]
    RestGenerator.__init__ = patched_init


def main(argv: list[str] | None = None) -> int:
    _patch_rest_generator_timeout()
    from garak import cli

    cli.main(sys.argv[1:] if argv is None else argv)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
