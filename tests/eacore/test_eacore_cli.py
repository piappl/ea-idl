import shutil
import sqlite3

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
