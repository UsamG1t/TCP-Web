#!/usr/bin/env python3
"""Assemble README.md from the documentation chapters in docs/info/.

The chapters are the single source of truth. Each chapter is a Jekyll page with
front matter (`title`, `nav_order`, ...); this script strips the front matter,
inserts a `## <title>` heading, concatenates the chapters in nav order, and
prepends a generated title block and table of contents.

Run after editing any chapter:  python3 docs/_tools/build_readme.py [REPO_ROOT]
"""

from __future__ import annotations
import re
import sys
from pathlib import Path

FRONT = re.compile(r"^---\n(.*?)\n---\n?", re.S)

INTRO = """# TCP Sliding-Window Simulator

An educational simulator of TCP sliding-window flow control and congestion
control. The backend computes a run as a discrete-event trace; the `/latest`
frontend replays it, and the `/old` page runs the same rules live in the browser
with click-to-drop packets.

> **This file is generated.** Edit the chapters in [`docs/info/`](docs/info) and
> run `python3 docs/_tools/build_readme.py`. Do not edit README.md by hand.

Full documentation site: the chapters below are also published via Jekyll /
GitHub Pages under `docs/`.
"""


def slug(title: str) -> str:
    s = title.strip().lower()
    s = re.sub(r"[^\w\s-]", "", s)
    return re.sub(r"\s+", "-", s)


def parse_front(text: str) -> tuple[dict, str]:
    m = FRONT.match(text)
    meta: dict[str, str] = {}
    if m:
        for line in m.group(1).splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip()] = v.strip()
        body = text[m.end():]
    else:
        body = text
    return meta, body.strip()


def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    info = root / "docs" / "info"

    chapters = []
    for path in info.glob("*.md"):
        if path.name == "index.md":
            continue
        meta, body = parse_front(path.read_text(encoding="utf-8"))
        title = meta.get("title", path.stem.replace("-", " ").title())
        order = int(meta.get("nav_order", 999))
        chapters.append((order, title, body))
    chapters.sort(key=lambda c: c[0])

    toc = "\n".join(f"- [{title}](#{slug(title)})" for _, title, _ in chapters)

    parts = [INTRO, "## Table of Contents\n", toc, ""]
    for _, title, body in chapters:
        parts.append(f"## {title}\n")
        parts.append(body)
        parts.append("")

    (root / "README.md").write_text("\n".join(parts).rstrip() + "\n", encoding="utf-8")
    print(f"wrote README.md from {len(chapters)} chapter(s):",
          ", ".join(t for _, t, _ in chapters))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
