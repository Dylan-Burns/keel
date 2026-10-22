"""Tests of the golden set file, its subsets, and the grades parser."""

import pathlib

import pytest

import conftest
from keel import errors
from keel.evaluation import golden
from keel.evaluation import labels

pytestmark = pytest.mark.unit

GOLDEN = conftest.REPO_ROOT / "eval" / "golden.yaml"
LABELS = conftest.REPO_ROOT / "eval" / "labels"


def test_golden_set_has_28_questions() -> None:
    golden_set = golden.load_golden(GOLDEN)
    ids = [q.id for q in golden_set.questions]
    assert ids == [f"G-{n:02d}" for n in range(1, 29)]
    chunk_level = {q.id for q in golden_set.questions if q.labels == "chunk"}
    # Chapter 18.2 names these 10 for chunk-level labels.
    assert chunk_level == {
        "G-01",
        "G-03",
        "G-05",
        "G-06",
        "G-09",
        "G-11",
        "G-15",
        "G-16",
        "G-19",
        "G-21",
    }
    refusals = {q.id for q in golden_set.questions if q.expect_out_of_scope}
    assert refusals == {"G-22", "G-23", "G-24", "G-25"}
    assert [q.id for q in golden_set.questions if q.answer_only] == ["G-28"]
    for question in golden_set.questions:
        assert question.scored == bool(question.expected)


def test_every_scored_question_has_a_label_file() -> None:
    golden_set = golden.load_golden(GOLDEN)
    scored = [q.id for q in golden_set.questions if q.scored]
    found = golden.load_labels(LABELS, scored)
    assert sorted(found) == sorted(scored)
    for question_id, label in found.items():
        assert label.index_version == golden_set.index_version, question_id
        assert label.sections, question_id


def test_select_subsets() -> None:
    golden_set = golden.load_golden(GOLDEN)
    assert [q.id for q in golden_set.select("demo")] == ["G-06", "G-11", "G-19"]
    assert [q.id for q in golden_set.select("G-02, G-01")] == ["G-01", "G-02"]
    assert len(golden_set.select(None)) == 28
    assert {q.id for q in golden_set.select("ci")} >= {"G-15", "G-22"}
    with pytest.raises(errors.GoldenSetError):
        golden_set.select("nothing")


def test_invalid_golden_set(tmp_path: pathlib.Path) -> None:
    bad = tmp_path / "golden.yaml"
    bad.write_text("version: 1\nquestions: [{id: G-01}]\n", encoding="utf-8")
    with pytest.raises(errors.GoldenSetError, match="not a valid golden set"):
        golden.load_golden(bad)
    with pytest.raises(errors.GoldenSetError):
        golden.load_golden(tmp_path / "absent.yaml")
    duplicate = tmp_path / "duplicate.yaml"
    duplicate.write_text(
        "version: 1.0.0\ncreated: x\nindex_version: 1.0.0\nquestions:\n"
        "  - {id: G-01, type: numeric, question: q}\n"
        "  - {id: G-01, type: numeric, question: q}\n",
        encoding="utf-8",
    )
    with pytest.raises(errors.GoldenSetError):
        golden.load_golden(duplicate)


def test_invalid_label_file(tmp_path: pathlib.Path) -> None:
    (tmp_path / "G-01.yaml").write_text("level: nonsense\n", encoding="utf-8")
    with pytest.raises(errors.GoldenSetError, match="not a valid label"):
        golden.load_labels(tmp_path, ["G-01"])
    (tmp_path / "G-02.yaml").write_text(
        "question_id: G-09\nlevel: section\nindex_version: '1'\nbuild_id: b\n"
        "chunks_sha256: c\ncreated: d\n",
        encoding="utf-8",
    )
    with pytest.raises(errors.GoldenSetError, match="labels of G-09"):
        golden.load_labels(tmp_path, ["G-02"])
    assert golden.load_labels(tmp_path, ["G-03"]) == {}


def test_parse_grades() -> None:
    text = "# comment\n\nA_1 2 the risk list\nA_2 0\nA_3 1 partly\n"
    assert labels.parse_grades(text) == {
        "A_1": (2, "the risk list"),
        "A_2": (0, ""),
        "A_3": (1, "partly"),
    }
    with pytest.raises(errors.GoldenSetError, match="line 1"):
        labels.parse_grades("A_1 3")
    with pytest.raises(errors.GoldenSetError, match="repeats"):
        labels.parse_grades("A_1 2\nA_1 0")


def test_pool_ids() -> None:
    text = "# header\n=== A_1 | risk_factors | found by: x\ntext\n"
    text += "=== B_2 | mdna | found by: y\nmore\n"
    assert labels.pool_ids(text) == ["A_1", "B_2"]
