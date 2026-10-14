import sqlite3
from pathlib import Path

import pytest
from click.testing import CliRunner

from eacore.backends.sql import load_file
from eacore.cli import cli
from eacore.history import extract_version, git_versions
from eacore.integrity import check

NAFV4 = Path(__file__).resolve().parents[1] / "data" / "nafv4.qea"
try:
    HISTORY = git_versions(NAFV4)
except Exception:
    HISTORY = []

FIRST_CLASS = "(select min(Object_ID) from t_object where Object_Type='Class')"
NEW_GUID = "'{0000AAAA-0000-0000-0000-000000000001}'"


def _two_objects_same_diagram(con):
    diagram = con.execute(
        "select Diagram_ID from t_diagramobjects group by Diagram_ID having count(*) > 1 limit 1"
    ).fetchone()[0]
    first, second = con.execute(
        "select Instance_ID, ObjectStyle from t_diagramobjects where Diagram_ID=? order by Instance_ID limit 2",
        (diagram,),
    ).fetchall()
    con.execute("update t_diagramobjects set ObjectStyle=? where Instance_ID=?", (first[1], second[0]))


CORRUPTIONS = {
    "dangling-reference": "update t_attribute set Object_ID=999999 where ID=(select min(ID) from t_attribute)",
    "unexplained-value": f"update t_object set PDATA1='abc' where Object_ID={FIRST_CLASS}",
    "missing-guid": f"update t_object set ea_guid=NULL where Object_ID={FIRST_CLASS}",
    "duplicate-guid": "update t_attribute set ea_guid=(select ea_guid from t_object where Object_Type='Class' limit 1) "
    "where ID=(select min(ID) from t_attribute)",
    "malformed-guid": f"update t_object set ea_guid='not-a-guid' where Object_ID={FIRST_CLASS}",
    "package-pair": f"update t_object set ea_guid={NEW_GUID} "
    "where Object_ID=(select min(Object_ID) from t_object where Object_Type='Package')",
    "stereotype-mismatch": "update t_object set Stereotype='Wrong' where ea_guid=(select Client from t_xref "
    "where Name='Stereotypes' and Type='element property' limit 1)",
    "stereotype-format": "update t_xref set Description='@STEREO;Name=X;' "
    "where XrefID=(select XrefID from t_xref where Name='Stereotypes' limit 1)",
    "duplicate-duid": _two_objects_same_diagram,
    "link-duid": "update t_diagramlinks set Style='Mode=3;EOID=DEADBEEF;SOID=DEADBEEF;' "
    "where Instance_ID=(select min(Instance_ID) from t_diagramlinks where Style like '%SOID=%')",
    "sqlite-sequence": "update sqlite_sequence set seq=1 where name='t_object'",
    "unmapped-table": "create table t_custom(x INTEGER); insert into t_custom values (1)",
    "duplicate-key": "insert into t_diagramlinks(DiagramID, ConnectorID, Geometry, Style, Hidden, Path) "
    "select DiagramID, ConnectorID, Geometry, Style, Hidden, Path from t_diagramlinks "
    "where Instance_ID=(select min(Instance_ID) from t_diagramlinks)",
}


@pytest.mark.parametrize("rule", sorted(CORRUPTIONS))
def test_each_rule_fires_on_its_corruption(rule, nafv4_path, qea_copy):
    path = qea_copy(nafv4_path)
    with sqlite3.connect(path) as con:
        corruption = CORRUPTIONS[rule]
        con.executescript(corruption) if isinstance(corruption, str) else corruption(con)
    issues = check(load_file(path))
    assert rule in {i.rule for i in issues}, sorted({i.rule for i in issues})


@pytest.mark.parametrize("index", range(len(HISTORY)) if HISTORY else [None])
def test_ea_made_versions_have_no_errors_or_unexplained_values(index, tmp_path):
    path = NAFV4 if index is None else extract_version(HISTORY[index][0], NAFV4, tmp_path / "v.qea")
    issues = check(load_file(path))
    bad = [i for i in issues if i.severity == "error" or i.rule == "unexplained-value"]
    assert bad == [], [f"{i.rule}: {i.message}" for i in bad]


def test_check_command_exit_codes(nafv4_path, qea_copy):
    runner = CliRunner()
    assert runner.invoke(cli, ["check", str(nafv4_path)]).exit_code == 0
    broken = qea_copy(nafv4_path)
    with sqlite3.connect(broken) as con:
        con.execute(CORRUPTIONS["dangling-reference"])
    result = runner.invoke(cli, ["check", str(broken)])
    assert result.exit_code == 1 and "dangling-reference" in result.output
    assert '"rule"' in runner.invoke(cli, ["check", "--format", "json", str(broken)]).output


@pytest.mark.parametrize("object_type", ["Package", "Part", "InteractionFragment"])
def test_numeric_pdata4_on_non_class_element_is_unexplained_not_dangling(object_type, tmp_path):
    path = tmp_path / "copy.qea"
    path.write_bytes(NAFV4.read_bytes())
    with sqlite3.connect(path) as con:
        con.execute(
            "update t_object set PDATA4='999999' where Object_ID="
            "(select min(Object_ID) from t_object where Object_Type=?)",
            (object_type,),
        )
        assert con.total_changes == 1
    issues = [i for i in check(load_file(path)) if "attr_pdata4" in i.message]
    assert [(i.severity, i.rule) for i in issues] == [("warning", "unexplained-value")]


def test_numeric_pdata4_on_class_is_still_a_connector_reference(tmp_path):
    path = tmp_path / "copy.qea"
    path.write_bytes(NAFV4.read_bytes())
    with sqlite3.connect(path) as con:
        con.execute(f"update t_object set PDATA4='999999' where Object_ID={FIRST_CLASS}")
    issues = [i for i in check(load_file(path)) if "attr_pdata4" in i.message]
    assert [(i.severity, i.rule) for i in issues] == [("error", "dangling-reference")]
