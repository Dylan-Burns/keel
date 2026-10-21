#!/usr/bin/env python3
"""Split the exported Keel plan (one Markdown file) into one file per chapter.

Usage: python scripts/split_plan.py plan.md docs/

Chapters start with a level-2 heading of the form "## N. Title". Everything
before the first chapter heading goes to docs/00_front_matter.md. Fenced
code blocks are respected, so a "## " line inside a code fence does not
split the file.
"""

from __future__ import annotations

import pathlib
import re
import sys

CHAPTER = re.compile(r"^## (\d{1,2})\. (.+?)\s*$")
FENCE = re.compile(r"^```")


def slug(title: str) -> str:
    """Returns a file-name slug for a chapter title.

    Args:
        title: The chapter title as written in the heading.

    Returns:
        Lowercase ASCII letters, digits, and underscores, at most 60 long.
    """
    text = title.lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    text = text.strip("_")
    return text[:60] or "chapter"


def split(source: pathlib.Path, out_dir: pathlib.Path) -> list[pathlib.Path]:
    """Writes one file per chapter and returns the paths in order.

    Args:
        source: The exported plan as one Markdown file.
        out_dir: The directory that receives the chapter files.

    Returns:
        The paths written, front matter first.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    lines = source.read_text(encoding="utf-8").splitlines(keepends=True)

    written: list[pathlib.Path] = []
    current_name = "00_front_matter.md"
    buffer: list[str] = []
    in_fence = False

    def flush() -> None:
        if not buffer:
            return
        path = out_dir / current_name
        path.write_text("".join(buffer).rstrip() + "\n", encoding="utf-8")
        written.append(path)
        buffer.clear()

    for line in lines:
        if FENCE.match(line):
            in_fence = not in_fence
        match = None if in_fence else CHAPTER.match(line)
        if match:
            flush()
            number = int(match.group(1))
            current_name = f"{number:02d}_{slug(match.group(2))}.md"
        buffer.append(line)
    flush()
    return written


def main(argv: list[str]) -> int:
    """Runs the split from the command line.

    Args:
        argv: The process arguments: the plan path and the output directory.

    Returns:
        The process exit code.
    """
    if len(argv) != 3:
        print(__doc__)
        return 2
    source = pathlib.Path(argv[1])
    out_dir = pathlib.Path(argv[2])
    if not source.exists():
        print(f"not found: {source}")
        return 1
    paths = split(source, out_dir)
    for path in paths:
        print(path)
    print(f"{len(paths)} files written to {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
