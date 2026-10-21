from datetime import datetime

import pytest

from eaedit import Session
from eaedit.mcp.idl import idl_diff

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
    assert result.diff == "" and "Model::Elsewhere" in result.outside_roots
    assert "changes outside the IDL roots: " in result.text() and "Model::Elsewhere" in result.text()


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
    assert "IDL generation failed" in result.text()
