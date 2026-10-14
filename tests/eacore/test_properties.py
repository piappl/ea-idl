"""Spec success criteria 1-3, over every version of nafv4.qea in git history."""

import sqlite3
from pathlib import Path

import pytest

from eacore.backends.sql import load_file
from eacore.history import extract_version, git_versions
from eacore.verify import diff_apply, roundtrip

DATA = Path(__file__).resolve().parents[1] / "data"
NAFV4 = DATA / "nafv4.qea"
try:
    HISTORY = git_versions(NAFV4)
except Exception:  # not a git checkout
    HISTORY = []


@pytest.fixture
def version(tmp_path):
    def _version(index: int) -> Path:
        sha, _ = HISTORY[index]
        return extract_version(sha, NAFV4, tmp_path / f"v{index:03d}.qea")

    return _version


def test_roundtrip_current_file_with_new_ids(tmp_path):
    source, rebuilt = roundtrip(NAFV4, DATA / "empty.qea", tmp_path)
    assert rebuilt.same_records(source)
    with sqlite3.connect(tmp_path / "roundtrip.qea") as con:
        assert con.execute("select min(Object_ID) from t_object").fetchone()[0] > 100000


@pytest.mark.skipif(not HISTORY, reason="git history not available")
@pytest.mark.parametrize("index", range(len(HISTORY)))
def test_roundtrip_every_version(index, version, tmp_path):
    source, rebuilt = roundtrip(version(index), DATA / "empty.qea", tmp_path / "rt")
    assert rebuilt.same_records(source), HISTORY[index]


@pytest.mark.skipif(len(HISTORY) < 2, reason="git history not available")
@pytest.mark.parametrize("index", range(1, len(HISTORY)))
def test_diff_apply_every_pair(index, version, tmp_path):
    expected, actual = diff_apply(version(index - 1), version(index), tmp_path / "da")
    assert actual.same_records(expected), HISTORY[index]


def test_noop_apply_of_self_diff_is_byte_identical(tmp_path):
    from eacore.backends.sql import SqlBackend
    from eacore.diff import diff

    path = tmp_path / "copy.qea"
    path.write_bytes(NAFV4.read_bytes())
    backend = SqlBackend.for_file(path)
    backend.apply(diff(backend.load(), load_file(NAFV4)))
    assert path.read_bytes() == NAFV4.read_bytes()
