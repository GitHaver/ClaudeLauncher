"""Generate claude_launcher.ico — an original, Claude-flavoured launcher mark.

A terracotta radiating "spark" (evoking Claude's look) on a warm-dark app tile,
with a small cream list/menu badge in the corner to signal "this is a *menu*
of Claude projects" rather than Claude itself. Original artwork, not the
official trademarked logo.

Run:  python generate_icon.py
"""

import math
import os

from PIL import Image, ImageDraw

APP_DIR = os.path.dirname(os.path.abspath(__file__))
ICO_PATH = os.path.join(APP_DIR, "claude_launcher.ico")
PNG_PREVIEW = os.path.join(APP_DIR, "claude_launcher.png")

S = 1024                      # master canvas (super-sampled, then downscaled)
TILE_BG = (32, 31, 29, 255)   # warm near-black
TERRA = (217, 119, 87, 255)   # Claude terracotta
CREAM = (240, 238, 230, 255)  # badge background
INK = (32, 31, 29, 255)       # badge lines


def capsule(draw, x0, y0, x1, y1, w, fill):
    """A line with rounded caps."""
    draw.line((x0, y0, x1, y1), fill=fill, width=w)
    r = w / 2
    for x, y in ((x0, y0), (x1, y1)):
        draw.ellipse((x - r, y - r, x + r, y + r), fill=fill)


def main():
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # --- app tile -------------------------------------------------------- #
    pad = int(S * 0.05)
    d.rounded_rectangle((pad, pad, S - pad, S - pad),
                        radius=int(S * 0.22), fill=TILE_BG)

    # --- radiating spark ------------------------------------------------- #
    cx, cy = S * 0.47, S * 0.45
    n = 12
    inner = S * 0.015
    spoke_w = int(S * 0.052)
    # Slightly varying arm lengths for an organic, non-mechanical burst.
    lengths = [0.255, 0.205, 0.235, 0.205]
    for i in range(n):
        ang = math.radians(i * (360 / n) - 90)
        outer = S * lengths[i % len(lengths)]
        x0 = cx + math.cos(ang) * inner
        y0 = cy + math.sin(ang) * inner
        x1 = cx + math.cos(ang) * outer
        y1 = cy + math.sin(ang) * outer
        capsule(d, x0, y0, x1, y1, spoke_w, TERRA)

    # --- menu / list badge (bottom-right corner) ------------------------- #
    bx0, by0, bx1, by1 = S * 0.58, S * 0.58, S * 0.90, S * 0.90
    d.rounded_rectangle((bx0, by0, bx1, by1), radius=int(S * 0.06), fill=CREAM)
    # three list rows
    lw = int(S * 0.028)
    lx0, lx1 = bx0 + S * 0.055, bx1 - S * 0.055
    for j in range(3):
        ly = by0 + S * 0.085 + j * S * 0.075
        capsule(d, lx0, ly, lx1, ly, lw, INK)

    # --- output ---------------------------------------------------------- #
    img.save(PNG_PREVIEW)
    sizes = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)]
    img.save(ICO_PATH, format="ICO", sizes=sizes)
    print("wrote", ICO_PATH)
    print("wrote", PNG_PREVIEW)


if __name__ == "__main__":
    main()
