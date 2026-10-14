import shutil
import sqlite3

import pytest

from click.testing import CliRunner

from eacore.cli import cli


def test_diff_command_text_and_json(nafv4_path, tmp_path):
    changed = tmp_path / "changed.qea"
    shutil.copyfile(nafv4_path, changed)
    with sqlite3.connect(changed) as con:
        con.execute("update t_object set Name='Renamed' where Object_ID=(select min(Object_ID) from t_object)")
    runner = CliRunner()
    result = runner.invoke(cli, ["diff", str(nafv4_path), str(changed)])
    assert result.exit_code == 0, result.output
    assert "'Renamed'" in result.output
    result = runner.invoke(cli, ["diff", "--format", "json", str(nafv4_path), str(changed)])
    assert result.exit_code == 0 and '"updates"' in result.output


def test_diff_requires_two_paths():
    result = CliRunner().invoke(cli, ["diff", "only-one.qea"])
    assert result.exit_code != 0


def test_textconv(nafv4_path):
    result = CliRunner().invoke(cli, ["textconv", str(nafv4_path)])
    assert result.exit_code == 0 and "t_object" in result.output


def _bad_files(tmp_path):
    text = tmp_path / "notes.qea"
    text.write_bytes(b"this is not a database\n" * 100)
    other = tmp_path / "other.qea"
    with sqlite3.connect(other) as con:
        con.execute("create table t (x)")
    return {"text": text, "sqlite": other, "missing": tmp_path / "missing.qea"}


@pytest.mark.parametrize("kind", ["text", "sqlite", "missing"])
@pytest.mark.parametrize("command", ["diff", "textconv", "check", "diff-b"])
def test_bad_repository_gives_one_line_error(command, kind, tmp_path, nafv4_path):
    bad = str(_bad_files(tmp_path)[kind])
    args = {
        "diff": ["diff", bad, str(nafv4_path)],
        "diff-b": ["diff", str(nafv4_path), bad],
        "textconv": ["textconv", bad],
        "check": ["check", bad],
    }[command]
    result = CliRunner().invoke(cli, args)
    assert result.exit_code not in (0, None), result.output
    assert isinstance(result.exception, SystemExit), repr(result.exception)
    assert "Traceback" not in result.output
    assert bad in result.output.replace("\n", "")


def test_diff_git_bad_revision_or_path_gives_one_line_error(tmp_path, nafv4_path):
    for args in (
        ["diff", "--git", "no-such-rev", "HEAD", str(nafv4_path)],
        ["diff", "--git", "HEAD", "HEAD", str(nafv4_path.with_name("missing.qea"))],
    ):
        result = CliRunner().invoke(cli, args)
        assert result.exit_code not in (0, None), result.output
        assert isinstance(result.exception, SystemExit), repr(result.exception)
        assert "Traceback" not in result.output
        assert args[-1] in result.output.replace("\n", "")
