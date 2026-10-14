import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from eacore.cli import cli
from eacore.history import git_versions, run_history

DATA = Path(__file__).resolve().parents[1] / "data"
NAFV4 = DATA / "nafv4.qea"

try:
    HISTORY = git_versions(NAFV4)
except Exception:
    HISTORY = []


@pytest.mark.skipif(len(HISTORY) < 2, reason="git history not available")
def test_run_history_writes_report_and_all_checks_pass(tmp_path):
    summary = run_history(NAFV4, tmp_path, DATA / "empty.qea")
    assert len(summary["versions"]) == len(HISTORY)
    assert len(summary["pairs"]) == len(HISTORY) - 1
    assert all(v["errors"] == 0 and v["roundtrip"] for v in summary["versions"])
    assert all(p["diff_apply"] for p in summary["pairs"])
    assert "t_diagramobjects.attr_objectstyle" in summary["style_keys"]
    assert json.loads((tmp_path / "summary.json").read_text())["pairs"]
    assert (tmp_path / "summary.md").read_text().startswith("# History of")
    assert len(list(tmp_path.glob("*.txt"))) == len(HISTORY) - 1


@pytest.mark.skipif(len(HISTORY) < 2, reason="git history not available")
def test_history_command(tmp_path, monkeypatch):
    """CLI wiring only, over the last 3 versions; the full history is covered above."""
    import eacore.history

    monkeypatch.setattr(eacore.history, "git_versions", lambda path: HISTORY[-3:])
    result = CliRunner().invoke(cli, ["history", str(NAFV4), "--out", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "3 versions, 2 diffs" in result.output
    assert (tmp_path / "summary.md").exists()


def test_summary_counts_column_updates_not_commits():
    from eacore.history import _summary_md

    md = _summary_md(
        {"file": "x.qea", "versions": [], "pairs": [], "column_changes": {"t_object.attr_name": 3}, "style_keys": {}}
    )
    assert "| column | updates |" in md
    assert "| t_object.attr_name | 3 |" in md
