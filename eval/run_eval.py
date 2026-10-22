#!/usr/bin/env python3
"""Run the golden set: the same as `keel eval` (chapter 18).

Usage:
    uv run python eval/run_eval.py --report eval/report.md

The harness lives in the package (keel/evaluation/), so the command, this
script, and the nightly workflow run the same code; this file keeps the
entry point that chapter 17.6 names.
"""

from __future__ import annotations

import sys

from keel import cli


def main() -> int:
    """Run `keel eval` with the arguments of this script.

    Returns:
        The exit code of `keel eval`.
    """
    return cli.main(["eval", *sys.argv[1:]])


if __name__ == "__main__":
    sys.exit(main())
