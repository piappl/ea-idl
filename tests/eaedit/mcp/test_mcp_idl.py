from datetime import datetime

import pytest

from eacore.changes import ChangeSet, Insert
from eacore.records import Record
from eaedit import Session
from eaedit.mcp.idl import _outside_roots, idl_diff

FIXED = datetime(2026, 1, 2, 3, 4, 5)
MESSAGE = "Model::core::message::Message"


@pytest.fixture
def config(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(
        'database_url: "sqlite:///unused.qea"\n'
        'root_packages: ["{753A4DFC-7876-4b00-BB5A-6274AD3817C3}"]\n'
        'template: "idl_just_defs.jinja2"\n'
        'filter_stereotypes: ["lobw"]\n',
        encoding="utf-8",
    )
    return path


def _open(path):
    return Session.open(path, policy="off", clock=lambda: FIXED, author="tester")


def test_added_attribute_shows_in_diff(nafv4_path, qea_copy, config):
    session = _open(qea_copy(nafv4_path))
    session.add_attribute(MESSAGE, name="zazolcMember", type="int")
    result = idl_diff(session, config)
    assert result.error is None and result.outside_roots == []
    assert result.diff.startswith("--- before/copy.idl\n+++ after/copy.idl\n")
    assert any(line.startswith("+") and "zazolcMember" in line for line in result.diff.splitlines())
    assert "changes outside" not in result.text()


def test_no_changes_is_no_diff(nafv4_path, qea_copy, config):
    result = idl_diff(_open(qea_copy(nafv4_path)), config)
    assert result.diff == "" and result.error is None
    assert result.text() == "No IDL differences."


def test_change_outside_roots_is_named(nafv4_path, qea_copy, config):
    session = _open(qea_copy(nafv4_path))
    session.create_package(parent="Model", name="Elsewhere")
    result = idl_diff(session, config)
    assert result.diff == "" and result.outside_roots == ["Model::Elsewhere"]
    assert "changes outside the IDL roots: Model::Elsewhere" in result.text()


def test_delete_in_roots_is_not_outside(nafv4_path, qea_copy, config):
    session = _open(qea_copy(nafv4_path))
    session.delete_element("Model::core::message::MessageHeader")
    assert idl_diff(session, config).outside_roots == []


def test_broken_generation_is_reported_not_raised(nafv4_path, qea_copy, config):
    session = _open(qea_copy(nafv4_path))
    session.add_attribute(MESSAGE, name="broken", type="NoSuchType")
    result = idl_diff(session, config)
    assert result.error and result.diff == ""
    assert "\n" not in result.error
    assert "IDL diff unavailable" in result.text()


def test_missing_config_is_text(nafv4_path, qea_copy, tmp_path):
    result = idl_diff(_open(qea_copy(nafv4_path)), tmp_path / "nope.yaml")
    assert result.error and result.diff == ""
    assert "IDL diff unavailable" in result.text()


def test_invalid_config_is_text(nafv4_path, qea_copy, tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("root_packages: 5\n", encoding="utf-8")
    result = idl_diff(_open(qea_copy(nafv4_path)), bad)
    assert result.error and "\n" not in result.error and result.diff == ""


def test_package_content_change_is_listed(nafv4_path, qea_copy, config):
    session = _open(qea_copy(nafv4_path))
    session.create_package(parent="Model", name="Elsewhere")
    session.create_element(package="Model::Elsewhere", name="Thing", stereotype="DataElement")
    assert idl_diff(session, config).outside_roots == ["Model::Elsewhere"]


def test_repository_wide_rows_are_listed_once(nafv4_path, qea_copy):
    session = _open(qea_copy(nafv4_path))
    rows = [Record("t_stereotypes", f"k{i}", {"attr_stereotype": f"s{i}"}, None) for i in range(2)]
    changes = ChangeSet(inserts=[Insert(row) for row in rows])
    assert _outside_roots(session, changes, ["core"]) == ["(repository-wide)"]


def test_original_is_only_copied(nafv4_path, qea_copy, config, tmp_path, monkeypatch):
    import tempfile

    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(scratch))
    path = qea_copy(nafv4_path)
    before = path.read_bytes()
    session = _open(path)
    session.add_attribute(MESSAGE, name="zazolcMember", type="int")
    assert idl_diff(session, config).diff
    assert path.read_bytes() == before
    assert not path.with_name(path.name + "-wal").exists()
    assert list(scratch.iterdir()) == []


def test_alias_only_change_outside_roots_is_listed(nafv4_path, qea_copy, config):
    session = _open(qea_copy(nafv4_path))
    session.update_package("Model::L7", alias="other alias")
    assert idl_diff(session, config).outside_roots == ["Model::L7"]
    # The twin row alone (as when only EA-side fields change) is enough to name the package.
    changes = session.changes()
    twin_only = ChangeSet(updates=[u for u in changes.updates if u.table == "t_object"])
    assert twin_only.updates
    assert _outside_roots(session, twin_only, ["core"]) == ["Model::L7"]
