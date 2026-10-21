"""Command line entry point for Keel.

Stage 0 ships only the version command. Later stages add the commands that
CLAUDE.md lists (inventory, parse, index, ask, serve, and the rest).
"""

import argparse
from collections.abc import Sequence
import sys

import keel


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser for the `keel` command.

    Returns:
        The configured parser.
    """
    parser = argparse.ArgumentParser(
        prog="keel",
        description="Grounded answers to business questions about SEC filings.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"keel {keel.__version__}",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the `keel` command.

    Args:
        argv: The arguments without the program name. None reads sys.argv.

    Returns:
        The process exit code.
    """
    parser = build_parser()
    parser.parse_args(argv)
    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
