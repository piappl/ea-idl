from datetime import datetime

import pytest

from eaedit import NotFoundError, Session

MESSAGE = "{3522A830-8853-4c52-9908-40871435BB3B}"  # Model::core::message
FIXED = datetime(2026, 1, 2, 3, 4, 5)


@pytest.fixture
def path(nafv4_path, qea_copy):
    return qea_copy(nafv4_path)


def _open(path, **kwargs):
    return Session.open(path, clock=lambda: FIXED, author="tester", **kwargs)


def _names(rows):
    return {row["qualified_name"] for row in rows}


def test_search_and_list_respect_focus(path):
    focused = _open(path, focus=[MESSAGE])
    everywhere = _open(path)

    listed = _names(focused.list())
    assert "Model::core::message::Message" in listed
    assert all(name.startswith("Model::core::message::") for name in listed)
    assert "Model::core::data::Measurement" in _names(everywhere.list())

    assert focused.search("measurement") == []
    found = _names(everywhere.search("MEASUREMENT"))
    assert {"Model::core::data::Measurement", "Model::core::data::MeasurementTypeEnum"} <= found
    assert _names(focused.search("message", type="Class")) >= {
        "Model::core::message::Message",
        "Model::core::message::DataMessage",
    }
    assert focused.search("message", type="Note") == []

    # an explicit package overrides the focus
    assert "Model::core::data::Measurement" in _names(focused.list("Model::core::data"))
    direct = _names(everywhere.list("Model::core", recursive=False))
    assert "Model::core::message" in direct and "Model::core::message::Message" not in direct


def test_queries_are_not_logged_and_see_working_changes(path, mini_mdg_path):
    session = _open(path, focus=[MESSAGE], catalogues=[mini_mdg_path])
    session.create_element(package="Model::core::message", name="Gadget", stereotype="MINI::Thing")
    session.set_tag(target="Model::core::message::Gadget", name="kind", value="b")
    assert [op.name for op in session.log] == ["create_element", "set_tag"]

    got = session.get("Model::core::message::Gadget")
    assert got["kind"] == "element"
    assert got["qualified_name"] == "Model::core::message::Gadget"
    assert got["name"] == "Gadget" and got["type"] == "Class"
    assert got["stereotypes"] == ["MINI::Thing"]
    assert got["tags"]["kind"] == "b"
    assert _names(session.search("gadget", stereotype="Thing")) == {"Model::core::message::Gadget"}
    assert session.search("gadget", stereotype="Other") == []
    assert len(session.log) == 2

    tree = session.tree()
    assert tree.splitlines()[0] == "Model::core::message"
    assert "  Gadget [Class] «Thing»" in tree.splitlines()


def test_get_package_attribute_and_connectors(path):
    session = _open(path)
    package = session.get("Model::core::message")
    assert package["kind"] == "package" and package["guid"] == MESSAGE
    assert package["name"] == "message"

    message = session.get("Model::core::message::Message")
    header = session.get("Model::core::message::Message.header")
    assert header["kind"] == "attribute" and header["type"] == "MessageHeader"
    assert header["qualified_name"] == "Model::core::message::Message.header"
    connectors = session.find_connectors(source="Model::core::message::Message")
    assert connectors and all(c["source"] == "Model::core::message::Message" for c in connectors)
    assert all(c["kind"] == "connector" for c in connectors)
    one = connectors[0]
    assert session.find_connectors(source=one["source"], target=one["target"], type=one["type"])
    assert session.find_connectors(source=one["source"], type="NoSuchType") == []
    assert session.get(one["guid"])["source"] == message["qualified_name"]

    with pytest.raises(NotFoundError):
        session.get("Model::nowhere")
