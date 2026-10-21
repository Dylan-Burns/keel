"""Tests for the package version and the bare `keel` command."""

import re

import pytest

import keel
import keel.cli


@pytest.mark.unit
def test_version() -> None:
    assert re.fullmatch(r"\d+\.\d+\.\d+", keel.__version__)


@pytest.mark.unit
def test_version_command(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        keel.cli.main(["--version"])
    assert exit_info.value.code == 0
    assert capsys.readouterr().out.strip() == f"keel {keel.__version__}"


@pytest.mark.unit
def test_no_arguments_prints_help(capsys: pytest.CaptureFixture[str]) -> None:
    assert keel.cli.main([]) == 0
    assert "usage: keel" in capsys.readouterr().out
