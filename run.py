#!/usr/bin/env python3
from __future__ import annotations
import argparse, os, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()
    try:
        import uvicorn
    except ImportError:
        print("uvicorn not installed", file=sys.stderr); sys.exit(1)
    parent = ROOT.parent
    # Keep the CWD at the repo root so relative paths in job configurations
    # (e.g. sample_path="data/demo/ocr_sample.png") resolve where users expect
    # them. Add the parent to sys.path so the "{ROOT.name}.app:app" package
    # import path still works under uvicorn's importer.
    os.chdir(str(ROOT))
    if str(parent) not in sys.path:
        sys.path.insert(0, str(parent))
    print(f"Starting Sentinel Defense at http://{args.host}:{args.port}")
    uvicorn.run(f"{ROOT.name}.app:app", host=args.host, port=args.port, reload=args.reload)

if __name__ == "__main__":
    main()
