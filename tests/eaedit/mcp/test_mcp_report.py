import re
from datetime import datetime

from eaedit import Session
from eacore.integrity import Issue
from eaedit.mcp.report import change_report, diagram_file_stem

FIXED = datetime(2026, 1, 2, 3, 4, 5)
L7 = "{0BA44FD3-F22C-4f9a-AC35-3BDB736B3C80}"
MEASUREMENT = "{360F4F18-9BCE-4efe-A337-2958FE3DCA3C}"  # Model::core::data, not on L7
MESSAGE = "Model::core::message::Message"
HEADER = "Model::core::message::MessageHeader"
PACKAGE = "Model::core::message"


def _open(path):
    return Session.open(path, policy="off", clock=lambda: FIXED, author="tester")


def _no_internals(text):
    assert "t_" not in text and "attr_" not in text
    assert not re.search(r"\{[0-9A-Fa-f]{8}-", text)


def test_new_class_with_attributes_and_generalization(nafv4_path, qea_copy):
    session = _open(qea_copy(nafv4_path))
    session.create_element(package=PACKAGE, name="Zażółć", stereotype="DataElement")
    zaz = f"{PACKAGE}::Zażółć"
    session.add_attribute(zaz, name="header", type="MessageHeader")
    session.add_attribute(zaz, name="count", type="int", lower="0", upper="*")
    session.connect(source=zaz, target=MESSAGE, type="Generalization")
    session.set_tag(zaz, "owner", "me")
    text = change_report(session)
    assert text.startswith("# Model changes\n")
    assert f"## {PACKAGE}\n" in text and "### Added" in text
    assert "«DataElement» Zażółć (Class)" in text
    assert "Zażółć.header: MessageHeader [1..1]" in text
    assert "Zażółć.count: int [0..*]" in text
    assert "Generalization Zażółć -> Message" in text
    assert "Zażółć: owner = me" in text
    assert "Removed" not in text and "layout" not in text
    _no_internals(text)


def test_rename_and_stereotype_change(nafv4_path, qea_copy):
    session = _open(qea_copy(nafv4_path))
    session.update_element(HEADER, name="Head")
    session.add_stereotype("Model::core::message::Head", "extra")
    text = change_report(session, title="CP-1")
    assert text.startswith("# CP-1\n")
    assert "### Changed" in text
    assert "  - name: MessageHeader → Head" in text
    assert re.search(r"  - stereotypes: DataElement.* → DataElement.*, extra\n", text)
    assert text.index("Head (Class)") < text.index("  - name:")
    _no_internals(text)


def test_removed_and_tag_changes(nafv4_path, qea_copy):
    session = _open(qea_copy(nafv4_path))
    session.delete_element("Model::core::message::GUID")
    text = change_report(session)
    assert "### Removed" in text and "«DataElement» GUID (Class)" in text
    _no_internals(text)


def test_place_on_diagram_is_layout_changed(nafv4_path, qea_copy):
    session = _open(qea_copy(nafv4_path))
    session.place(L7, MEASUREMENT)
    text = change_report(session)
    assert "L7: diagram layout changed" in text
    _no_internals(text)
    assert "![L7](<diagrams/L7.svg>)" in change_report(session, diagrams_dir="diagrams")


def test_new_diagram_image_and_idl(nafv4_path, qea_copy):
    session = _open(qea_copy(nafv4_path))
    session.create_diagram(PACKAGE, "Overview/1")
    session.add_attribute(MESSAGE, name="x", type="int")
    text = change_report(session, diagrams_dir="diagrams", idl_diffs={"main": "+ a ```\n- b\n"}, idl_files=False)
    assert "Diagram Overview/1 (Class)" in text
    assert "![Overview/1](<diagrams/Overview_1.svg>)" in text
    assert "## IDL" in text and "````diff\n+ a ```\n- b\n````" in text
    pointer = change_report(session, idl_diffs={"main": "x"}, idl_files=True)
    assert "idl-main.diff" in pointer and "```" not in pointer


def test_warnings_and_empty(nafv4_path, qea_copy):
    session = _open(qea_copy(nafv4_path))
    assert "No changes." in change_report(session)
    session.set_tag(MESSAGE, "madeup", "v")
    session.add_stereotype(MESSAGE, "Nope")
    text = change_report(session)
    assert "## Warnings" in text


def test_default_tags_of_new_element_are_folded(nafv4_path, qea_copy, mini_mdg_path):
    session = Session.open(
        qea_copy(nafv4_path), policy="off", clock=lambda: FIXED, author="tester", catalogues=[mini_mdg_path]
    )
    session.create_element(package=PACKAGE, name="Widget", stereotype="MINI::Thing")
    session.set_tag(f"{PACKAGE}::Widget", "owner", "me")
    text = change_report(session)
    assert "- Widget: owner = me" in text
    assert "«Thing» Widget (Class) (+2 default tags)" in text
    assert "kind" not in text and "ref =" not in text
    assert sum(line.startswith("- Widget: ") for line in text.splitlines()) == 1


def test_diagram_name_with_space_links_with_angle_brackets(nafv4_path, qea_copy):
    session = _open(qea_copy(nafv4_path))
    session.create_diagram(PACKAGE, "New view")
    text = change_report(session, diagrams_dir="diagrams")
    assert "![New view](<diagrams/New view.svg>)" in text
    assert diagram_file_stem("a/b", set()) == "a_b"


def test_identical_connectors_are_not_merged(nafv4_path, qea_copy):
    session = _open(qea_copy(nafv4_path))
    for _ in range(2):
        session.connect(source=MESSAGE, target=HEADER, type="Association")
    text = change_report(session)
    assert text.count("- Association Message -> MessageHeader") == 2


def test_tag_value_with_equals_sign(nafv4_path, qea_copy):
    session = _open(qea_copy(nafv4_path))
    session.set_tag(MESSAGE, "URI", "a = b")
    text = change_report(session)
    line = next(x for x in text.splitlines() if x.startswith("- Message: URI: "))
    assert line.endswith(" → a = b")
    session.set_tag(MESSAGE, "URI", "c = d")
    assert "→ c = d" in change_report(session)


def test_removed_attribute_and_connector(nafv4_path, qea_copy):
    session = _open(qea_copy(nafv4_path))
    session.delete_attribute(f"{MESSAGE}.header")
    [link] = session.find_connectors(source=MESSAGE, target=HEADER)
    session.delete_connector(link["guid"])
    text = change_report(session)
    removed = text.split("### Removed")[1]
    assert "- Message.header: MessageHeader [1..1]" in removed
    assert "Association Message -> MessageHeader" in removed
    _no_internals(text)


def test_integrity_and_warnings_sections(nafv4_path, qea_copy, monkeypatch):
    session = _open(qea_copy(nafv4_path))
    session.create_diagram(PACKAGE, "V")
    session.set_tag(MESSAGE, "madeup", "v")
    monkeypatch.setattr(Session, "_new_issues", lambda self: [Issue("error", "rule-x", None, "something broke")])
    text = change_report(session)
    assert "## Integrity\n\n- error: something broke" in text
    warnings = text.split("## Warnings")[1].split("## Integrity")[0]
    assert "- unknown-tag: 'madeup' is not a tag" in warnings
    assert "- unverified-default: no EA-verified defaults for diagram Class" in warnings
    assert "t_diagram" not in text
