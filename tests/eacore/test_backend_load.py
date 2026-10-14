import sqlite3

import pytest

from eacore.backends.sql import NotAnEaRepositoryError, SqlBackend, load_file
from eacore.records import Ref

ROOT_CORE = "{753A4DFC-7876-4b00-BB5A-6274AD3817C3}"


def test_loads_all_mapped_rows(nafv4_path):
    rs = load_file(nafv4_path)
    with sqlite3.connect(nafv4_path) as con:
        for table, expected in [("t_object", 50), ("t_connector", 43), ("t_diagramobjects", 50), ("t_xref", 65)]:
            assert con.execute(f"select count(*) from {table}").fetchone()[0] == expected
            assert len(list(rs.records(table))) == expected
    assert "sqlite_sequence" not in rs.tables()
    assert not [t for t in rs.tables() if t.lower().startswith("usys")]


def test_integer_ids_become_refs(nafv4_path):
    rs = load_file(nafv4_path)
    core = rs.get("t_package", ROOT_CORE)
    assert core.values["attr_name"] == "core"
    assert isinstance(core.values["attr_parent_id"], Ref)
    assert "attr_package_id" not in core.values  # surrogate column is not a value
    package_elements = [o for o in rs.records("t_object") if o.values["attr_object_type"] == "Package"]
    assert all(isinstance(o.values["attr_pdata1"], Ref) for o in package_elements)
    for link in rs.records("t_diagramlinks"):
        assert isinstance(link.key[0], Ref) and isinstance(link.key[1], Ref)


def test_load_problems_on_clean_file_are_none(nafv4_path):
    rs = load_file(nafv4_path)
    assert [i for i in rs.issues if i.kind in ("dangling", "unexplained", "missing_guid")] == []
    assert rs.meta["unmapped_tables"] == []
    assert rs.meta["sequences"]["t_object"] >= rs.meta["max_ids"]["t_object"]


def test_missing_file_and_non_ea_file_fail_clearly(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_file(tmp_path / "missing.qea")
    other = tmp_path / "other.sqlite"
    with sqlite3.connect(other) as con:
        con.execute("create table foo(x)")
    with pytest.raises(NotAnEaRepositoryError):
        load_file(other)


def test_duplicates_and_missing_duid_do_not_crash(nafv4_path, qea_copy):
    path = qea_copy(nafv4_path)
    with sqlite3.connect(path) as con:
        con.execute(
            "insert into t_diagramlinks(DiagramID, ConnectorID, Geometry, Style, Hidden, Path) "
            "select DiagramID, ConnectorID, Geometry, Style, Hidden, Path from t_diagramlinks "
            "where Instance_ID = (select min(Instance_ID) from t_diagramlinks)"
        )
        con.execute(
            "update t_diagramobjects set ObjectStyle = 'HideIcon=0;' "
            "where Instance_ID = (select min(Instance_ID) from t_diagramobjects)"
        )
    rs = load_file(path)
    assert any(i.kind == "duplicate_key" and i.table == "t_diagramlinks" for i in rs.issues)
    assert any(isinstance(r.key, tuple) and r.key[-1] == "#no-duid" for r in rs.records("t_diagramobjects"))


def test_sqlalchemy_url_form(nafv4_path):
    backend = SqlBackend(f"sqlite+pysqlite:///{nafv4_path.as_posix()}")
    assert backend.path == nafv4_path
    assert len(backend.load()) > 0


def test_columns_lists_column_keys(nafv4_path):
    backend = SqlBackend.for_file(nafv4_path)
    backend.load()
    columns = backend.columns("t_object")
    assert "attr_name" in columns
    assert "attr_object_id" not in columns
