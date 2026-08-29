#!/usr/bin/env python3
"""
Generates an animated GIF of a snake crawling across a GitHub contribution
grid. Unlike the classic "Platane/snk" snake, this snake's length is
PERMANENT and CUMULATIVE: every time it passes over a square that has at
least one contribution, it grows by one segment and never shrinks back down.
By the end of the loop, the snake's final length is a direct visual record
of how many active days you had in the past year.

Usage:
    python generate_growing_snake.py --user elviDev --token $GITHUB_TOKEN --out snake.gif

If --token is omitted, the script falls back to the GITHUB_TOKEN environment
variable (which is what GitHub Actions provides automatically).
"""

import argparse
import json
import math
import os
import sys
import urllib.request
from datetime import datetime

from PIL import Image, ImageDraw

GRAPHQL_URL = "https://api.github.com/graphql"

QUERY = """
query($login: String!) {
  user(login: $login) {
    contributionsCollection {
      contributionCalendar {
        weeks {
          contributionDays {
            date
            contributionCount
          }
        }
      }
    }
  }
}
"""


def fetch_contribution_weeks(username: str, token: str):
    body = json.dumps({"query": QUERY, "variables": {"login": username}}).encode()
    req = urllib.request.Request(
        GRAPHQL_URL,
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "growing-snake-script",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.loads(resp.read().decode())

    if "errors" in payload:
        raise RuntimeError(f"GitHub API error: {payload['errors']}")

    weeks = payload["data"]["user"]["contributionsCollection"]["contributionCalendar"]["weeks"]
    return weeks


def build_synthetic_weeks(num_weeks: int = 53, seed: int = 7):
    """Fallback / demo data generator so the script can be previewed without
    a real token. Produces a plausible, uneven contribution pattern."""
    import random

    random.seed(seed)
    weeks = []
    for w in range(num_weeks):
        days = []
        # bias later weeks to have more activity, like a dev who's been
        # ramping up
        base = 0.15 + 0.55 * (w / num_weeks)
        for d in range(7):
            if random.random() < base:
                count = random.choice([1, 1, 2, 2, 3, 4, 6, 9])
            else:
                count = 0
            days.append({"date": f"synthetic-{w}-{d}", "contributionCount": count})
        weeks.append({"contributionDays": days})
    return weeks


def level_for_count(count: int) -> int:
    """Quantize a raw contribution count into GitHub's familiar 0-4 levels."""
    if count <= 0:
        return 0
    if count <= 2:
        return 1
    if count <= 5:
        return 2
    if count <= 9:
        return 3
    return 4


LEVEL_COLORS = {
    0: (22, 27, 34),
    1: (14, 68, 41),
    2: (0, 109, 50),
    3: (38, 166, 65),
    4: (57, 211, 83),
}

BG_COLOR = (13, 17, 23)
SNAKE_HEAD = (255, 255, 255)
SNAKE_BODY_START = (247, 147, 26)   # bright orange head-end
SNAKE_BODY_END = (155, 89, 255)     # violet tail-end


def lerp_color(c1, c2, t):
    return tuple(int(c1[i] + (c2[i] - c1[i]) * t) for i in range(3))


def build_path(weeks):
    """
    Returns a list of (col, row, level) in boustrophedon order:
    down the first column, up the second, down the third, etc.
    This keeps the snake's motion continuous with no jumps.
    """
    grid_levels = []
    for week in weeks:
        col_levels = []
        for day in week["contributionDays"]:
            col_levels.append(level_for_count(day["contributionCount"]))
        while len(col_levels) < 7:
            col_levels.append(0)
        grid_levels.append(col_levels)

    path = []
    for col, col_levels in enumerate(grid_levels):
        rows = range(7) if col % 2 == 0 else range(6, -1, -1)
        for row in rows:
            path.append((col, row, col_levels[row]))
    return path, len(grid_levels)


def render_gif(weeks, out_path: str, cell=14, gap=3, fps=20, max_frames=None):
    path, num_cols = build_path(weeks)
    num_rows = 7

    grid_w = num_cols * (cell + gap) + gap
    grid_h = num_rows * (cell + gap) + gap
    margin = 20
    img_w = grid_w + margin * 2
    img_h = grid_h + margin * 2

    def cell_rect(col, row):
        x0 = margin + gap + col * (cell + gap)
        y0 = margin + gap + row * (cell + gap)
        return x0, y0, x0 + cell, y0 + cell

    total_steps = len(path)
    stride = max(1, total_steps // max_frames) if max_frames else 1

    # The snake's length only ever increases, and only on a step where it
    # eats (i.e. the square it lands on has at least one contribution). It
    # never shrinks. The body shown at each frame is just the last
    # `earned_length` cells of the path walked so far.
    earned_length = 1
    body = []
    proper_frames = []
    for col, row, level in path:
        body.append((col, row))
        if level > 0:
            earned_length += 1
        if len(body) > earned_length:
            body = body[-earned_length:]
        proper_frames.append((list(body), earned_length))

    if stride > 1:
        proper_frames = proper_frames[::stride] + [proper_frames[-1]]

    gif_frames = []
    for body_cells, earned_length in proper_frames:
        im = Image.new("RGB", (img_w, img_h), BG_COLOR)
        draw = ImageDraw.Draw(im)

        # draw base grid using the precomputed levels
        for c, r, lvl in path:
            x0, y0, x1, y1 = cell_rect(c, r)
            draw.rounded_rectangle([x0, y0, x1, y1], radius=3, fill=LEVEL_COLORS[lvl])

        # draw snake body, tail -> head, with a color gradient
        n = len(body_cells)
        for j, (c, r) in enumerate(body_cells):
            t = j / max(1, n - 1)
            color = lerp_color(SNAKE_BODY_END, SNAKE_BODY_START, t)
            if j == n - 1:
                color = SNAKE_HEAD
            x0, y0, x1, y1 = cell_rect(c, r)
            draw.rounded_rectangle([x0, y0, x1, y1], radius=3, fill=color)

        gif_frames.append(im)

    duration_ms = int(1000 / fps)
    gif_frames[0].save(
        out_path,
        save_all=True,
        append_images=gif_frames[1:],
        duration=duration_ms,
        loop=0,
        disposal=2,
    )
    return len(gif_frames), (img_w, img_h)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--user", required=False, help="GitHub username")
    parser.add_argument("--token", required=False, default=os.environ.get("GITHUB_TOKEN"))
    parser.add_argument("--out", default="growing-snake.gif")
    parser.add_argument("--demo", action="store_true", help="Use synthetic data instead of hitting the API")
    parser.add_argument("--fps", type=int, default=20)
    parser.add_argument("--max-frames", type=int, default=200)
    args = parser.parse_args()

    if args.demo or not args.user or not args.token:
        print("Running in DEMO mode with synthetic contribution data.", file=sys.stderr)
        weeks = build_synthetic_weeks()
    else:
        weeks = fetch_contribution_weeks(args.user, args.token)

    out_dir = os.path.dirname(args.out)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    n_frames, size = render_gif(weeks, args.out, fps=args.fps, max_frames=args.max_frames)
    print(f"Wrote {args.out} ({n_frames} frames, {size[0]}x{size[1]}px)")


if __name__ == "__main__":
    main()
