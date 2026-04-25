#!/usr/bin/env python3
"""
Sentinel Adversarial Orchestrator — launcher.

Usage:
    python run.py              # default: http://127.0.0.1:8000
    python run.py --port 9000
    python run.py --host 0.0.0.0 --port 8080
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Ensure the sentinel root is on sys.path so all imports resolve,
# including the whitebox_scan_platform shim.
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> None:
    parser = argparse.ArgumentParser(description="Sentinel Adversarial Orchestrator")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="Bind port (default: 8000)")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload for development")
    args = parser.parse_args()

    try:
        import uvicorn
    except ImportError:
        print("uvicorn is not installed. Run: pip install uvicorn", file=sys.stderr)
        sys.exit(1)

    print(f"Starting Sentinel Adversarial Orchestrator at http://{args.host}:{args.port}")
    uvicorn.run(
        "sentinel.app:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
    )


if __name__ == "__main__":
    main()
