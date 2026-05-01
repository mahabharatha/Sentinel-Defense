#!/usr/bin/env python3
"""Convert near-white pixels in the brand octopus PNG to fully transparent.

The image as uploaded ships as RGB (no alpha), so any CSS / SVG recolor
filter that relies on the alpha channel ends up tinting the WHOLE
rectangle (including the background) instead of just the silhouette.
This script:

  1. Loads docs/images/sentinel-octopus.png
  2. Converts the image mode to RGBA so alpha exists
  3. For every pixel where (r, g, b) is approximately white, sets a = 0
  4. Saves the file in place (RGBA PNG)

Idempotent — running it again on an already-processed PNG is a no-op.

Usage:
    cd /Users/macmacmac/Documents/sentinel
    source venv/bin/activate
    python scripts/make_logo_transparent.py
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCE = REPO_ROOT / "docs" / "images" / "sentinel-octopus.png"
WHITE_THRESHOLD = 240  # pixel is "white" when r,g,b are all >= this


def main() -> int:
    try:
        from PIL import Image
    except ImportError:
        print("[make_logo_transparent] Pillow not installed in this venv.")
        print("                        Run: pip install Pillow")
        return 1

    if not SOURCE.exists():
        print(f"[make_logo_transparent] {SOURCE} does not exist.")
        return 1

    img = Image.open(SOURCE).convert("RGBA")
    pixels = img.getdata()

    new_pixels = []
    near_white = 0
    for r, g, b, a in pixels:
        if r >= WHITE_THRESHOLD and g >= WHITE_THRESHOLD and b >= WHITE_THRESHOLD:
            new_pixels.append((r, g, b, 0))
            near_white += 1
        else:
            new_pixels.append((r, g, b, a))

    img.putdata(new_pixels)
    img.save(SOURCE, format="PNG")

    pct = (near_white / len(pixels)) * 100
    print(f"[make_logo_transparent] processed {len(pixels):,} pixels")
    print(f"[make_logo_transparent] {near_white:,} near-white pixels made transparent ({pct:.1f}%)")
    print(f"[make_logo_transparent] saved RGBA PNG -> {SOURCE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
