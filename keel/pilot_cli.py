"""The pilot commands of chapter 27.2: comp sets, feedback, templates.

`keel compsets add NAME TICKER...` saves a comp set (the firm's sets load
this way in week 0 of the pilot, chapter 27.6), `keel compsets list`
prints them, and `keel compsets remove NAME` deletes 1. `keel feedback`
prints the votes, and `keel feedback --flagged` the thumbs-down answers
that the engineer reviews as candidate golden questions each week.
`keel template` lists the question templates, and `keel template ID
--companies ... --period ...` prints a filled question.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
import dataclasses
import json

from keel import config
from keel import templates
from keel.stores import pilot

COMMANDS = frozenset({"compsets", "feedback", "template"})


def add_parsers(add_command: Callable[..., argparse.ArgumentParser]) -> None:
    """Add the `compsets`, `feedback`, and `template` commands.

    Args:
        add_command: The `add_parser` of the `keel` subcommands.
    """
    sets_parser = add_command(
        "compsets", help="the saved comp sets (chapter 27.2)"
    )
    actions = sets_parser.add_subparsers(
        dest="compsets_command", metavar="action", required=True
    )
    add_parser = actions.add_parser("add", help="create or replace a set")
    add_parser.add_argument("name", help="the name, as in 'my NAME comps'")
    add_parser.add_argument("tickers", nargs="+", help="the tickers")
    remove_parser = actions.add_parser("remove", help="delete a set")
    remove_parser.add_argument("name", help="the name")
    actions.add_parser("list", help="list the sets and their tickers")

    feedback_parser = add_command(
        "feedback", help="the thumbs votes on answers (chapter 27.2)"
    )
    feedback_parser.add_argument(
        "--flagged",
        action="store_true",
        help="only the thumbs-down answers: candidate golden questions",
    )

    template_parser = add_command(
        "template", help="list or fill the question templates (chapter 27.2)"
    )
    template_parser.add_argument(
        "template_id", nargs="?", default=None, help="the template to fill"
    )
    template_parser.add_argument(
        "--companies", default="", help="companies, tickers, or a comp set"
    )
    template_parser.add_argument(
        "--period", default="", help="the time scope (default per template)"
    )


def run(
    settings: config.Settings, args: argparse.Namespace
) -> tuple[int, list[str]]:
    """Run 1 of the pilot commands; `keel.cli` prints the lines.

    Args:
        settings: The loaded settings, with the pilot store and
            `pilot.templates`.
        args: The parsed arguments.

    Returns:
        The exit code (0, or 1 when a comp set to remove does not
        exist) and the lines to print.

    Raises:
        InvalidCompSetError: A comp set name or ticker is not valid.
        PilotStoreError: The pilot store cannot be read or written.
        ConfigError: The templates file is absent or not valid.
        TemplateError: The template is unknown or a value is missing.
    """
    if args.command == "compsets":
        return _compsets(pilot.PilotStore(pilot.db_path(settings)), args)
    if args.command == "feedback":
        store = pilot.PilotStore(pilot.db_path(settings))
        return 0, [
            json.dumps(dataclasses.asdict(entry), ensure_ascii=False)
            for entry in store.feedback(flagged_only=args.flagged)
        ]
    loaded = templates.load(settings.pilot.templates)
    if args.template_id is None:
        return 0, [f"{t.id}\t{t.label}\t{t.text}" for t in loaded]
    template = templates.find(loaded, args.template_id)
    return 0, [templates.fill(template, args.companies, args.period)]


def _joined(tickers: tuple[str, ...]) -> str:
    return " ".join(tickers)


def _compsets(
    store: pilot.PilotStore, args: argparse.Namespace
) -> tuple[int, list[str]]:
    if args.compsets_command == "add":
        entry = store.save_comp_set(
            args.name, args.tickers, editor=None, admin=True
        )
        return 0, [
            f"saved {entry.name}: {_joined(entry.tickers)}",
            f"ask about it as 'my {entry.name} comps'",
        ]
    name = pilot.normalize_name(args.name) if "name" in args else ""
    if args.compsets_command == "remove":
        if store.delete_comp_set(args.name, editor=None, admin=True):
            return 0, [f"removed {name}"]
        return 1, [f"no comp set {name}"]
    return 0, [
        f"{entry.name}\t{_joined(entry.tickers)}"
        for entry in store.comp_sets().values()
    ]
