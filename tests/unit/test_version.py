"""Placeholder test for the stage 0 package; stage 1 adds the real suite."""

import re

import pytest

import keel
from keel import cli


@pytest.mark.unit
def test_version() -> None:
    assert re.fullmatch(r"\d+\.\d+\.\d+", keel.__version__)


@pytest.mark.unit
def test_version_command(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["--version"])
    assert exit_info.value.code == 0
    assert capsys.readouterr().out.strip() == f"keel {keel.__version__}"


@pytest.mark.unit
def test_no_arguments_prints_help(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main([]) == 0
    assert "usage: keel" in capsys.readouterr().out
