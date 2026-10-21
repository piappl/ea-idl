import re

import pytest

from eaedit.errors import InvalidOperationError
from eaedit.mcp import explore
from eaedit.mcp.workspace import Config, Workspace

MSG = "Model::core::message"


def _snapshot(path, tmp_path):
    return Workspace(Config(path, out_dir=tmp_path / "out")).snapshot()


def test_overview_lists_children_with_counts(nafv4_path, tmp_path):
    text = explore.overview(_snapshot(nafv4_path, tmp_path), "Model")
    first, *rest = text.splitlines()
    assert first.startswith("Model")
    names = {line.strip().split("  ")[0] for line in rest}
    assert {"core", "L7", "p2", "p6"} <= names
    assert re.search(r"\(\d+ elements: .*\)  \{[0-9A-Fa-f-]+\}", text)
    # depth 1 shows only the package itself
    assert len(explore.overview(_snapshot(nafv4_path, tmp_path), "Model", depth=1).splitlines()) == 1


def test_search_finds_message_with_guid_and_short_lines(nafv4_path, tmp_path):
    session = _snapshot(nafv4_path, tmp_path)
    text = explore.search(session, "Message", kind="element")
    line = next(x for x in text.splitlines() if x.split("  ")[1] == f"{MSG}::Message")
    assert re.search(r"\{[0-9A-Fa-f-]+\}$", line)
    assert line.startswith("element  ")
    assert all(len(x) <= 200 for x in text.splitlines())
    assert explore.search(session, "/^message$/", kind="element").count(f"{MSG}::Message") == 1
    assert explore.search(session, "message", kind="package").startswith("package  ")


def test_paging(nafv4_path, tmp_path):
    session = _snapshot(nafv4_path, tmp_path)
    one = explore.search(session, "e", kind="element", page_size=2).splitlines()
    assert len(one) == 3 and re.fullmatch(r"… \d+ more \(page=2\)", one[-1])
    two = explore.search(session, "e", kind="element", page=2, page_size=2).splitlines()
    assert two[0] != one[0] and two[0] != one[1]
    assert explore.page_lines(["a", "b", "c"], 2, 2) == "c"
    assert explore.page_lines(["a", "b", "c"], 1, 2) == "a\nb\n… 1 more (page=2)"


def test_describe_element(nafv4_path, tmp_path):
    session = _snapshot(nafv4_path, tmp_path)
    text = explore.describe(session, f"{MSG}::Message")
    assert f"{MSG}::Message" in text.splitlines()[0]
    assert re.search(r"header: MessageHeader .*\{[0-9A-Fa-f-]+\}", text)
    assert "diagrams:" in text
    assert all(len(x) <= 200 for x in text.splitlines())
    # by GUID too
    guid = re.search(r"\{[0-9A-Fa-f-]+\}", text.splitlines()[0]).group(0)
    assert explore.describe(session, guid) == text


def test_describe_package_and_attribute(nafv4_path, tmp_path):
    session = _snapshot(nafv4_path, tmp_path)
    pkg = explore.describe(session, MSG)
    assert "contents:" in pkg and f"{MSG}::Message" in pkg
    attr = explore.describe(session, f"{MSG}::Message.header")
    assert "MessageHeader" in attr and "attribute" in attr.splitlines()[0]


def test_describe_connector_and_diagram(nafv4_path, tmp_path):
    session = _snapshot(nafv4_path, tmp_path)
    conn = session.find_connectors(type="Generalization")[0]
    text = explore.describe(session, conn["guid"])
    assert "source:" in text and "target:" in text
    rs = session.working
    diagram = next(iter(rs.records("t_diagram")))
    from eaedit.resolve import guid_of

    text = explore.describe(session, guid_of(diagram))
    assert text.splitlines()[0].startswith("diagram")
    assert "obj " in text


def test_usages(nafv4_path, tmp_path):
    session = _snapshot(nafv4_path, tmp_path)
    text = explore.usages(session, f"{MSG}::MessageHeader")
    assert f"{MSG}::Message.header" in text
    assert "attributes typed by it:" in text


def test_stereotype_info(nafv4_path, tmp_path):
    text = explore.stereotype_info(_snapshot(nafv4_path, tmp_path), "DataElement")
    assert "applies to:" in text and "tags:" in text
    assert explore.stereotype_info(_snapshot(nafv4_path, tmp_path), "NoSuchThing").startswith("no stereotype")


def test_ambiguity_reply(qea_copy, nafv4_path, tmp_path):
    path = qea_copy(nafv4_path)
    ws = Workspace(Config(path, out_dir=tmp_path / "out"))
    ws.open_session(focus=[MSG])
    ws.run("create_package", {"parent": MSG, "name": "Dup"})
    ws.run("create_element", {"package": MSG, "name": "Dup"})
    ws.commit()
    text = explore.describe(ws.snapshot(), f"{MSG}::Dup")
    lines = text.splitlines()
    assert lines[0] == f"ambiguous: {MSG}::Dup"
    assert len(lines) == 3 and all(re.search(r"\{[0-9A-Fa-f-]+\}$", x) for x in lines[1:])
    assert {x.split("  ")[0] for x in lines[1:]} == {"package", "element"}


def test_non_ascii_name(qea_copy, nafv4_path, tmp_path):
    path = qea_copy(nafv4_path)
    ws = Workspace(Config(path, out_dir=tmp_path / "out"))
    ws.open_session(focus=[MSG])
    ws.run("create_element", {"package": MSG, "name": "Zażółć_gęślą"})
    ws.commit()
    snap = ws.snapshot()
    assert f"{MSG}::Zażółć_gęślą" in explore.search(snap, "gęślą")
    assert "Zażółć_gęślą" in explore.describe(snap, f"{MSG}::Zażółć_gęślą")


def test_ambiguity_lists_no_bare_keys(qea_copy, nafv4_path, tmp_path):
    from eacore.records import Record

    assert explore._braced(Record("t_object", 7, {"attr_name": "x"})) == "-"
    path = qea_copy(nafv4_path)
    ws = Workspace(Config(path, out_dir=tmp_path / "out"))
    ws.open_session(focus=[MSG])
    ws.run("create_package", {"parent": MSG, "name": "Dup"})
    ws.run("create_element", {"package": MSG, "name": "Dup"})
    ws.commit()
    text = explore.usages(ws.snapshot(), f"{MSG}::Dup")
    assert text.startswith("ambiguous:") and all(re.search(r"\{[0-9A-Fa-f-]+\}$", x) for x in text.splitlines()[1:])


def test_long_names_keep_the_guid(nafv4_path, tmp_path):
    out = explore.page_lines([f"element  {'N' * 300}  Class  {{ABC-1}}", "x" * 300 + "  [+3 packages]"], 1, 5)
    first, second = out.splitlines()
    assert len(first) <= 200 and first.endswith("…  {ABC-1}") and "…" in first
    assert len(second) <= 200 and second.endswith("[+3 packages]")


def test_stereotype_info_has_real_tag(nafv4_path, tmp_path):
    text = explore.stereotype_info(_snapshot(nafv4_path, tmp_path), "DataElement")
    assert "  min_items: - default=16" in text


def test_search_filters_and_errors(nafv4_path, tmp_path):
    session = _snapshot(nafv4_path, tmp_path)
    by_stereo = explore.search(session, "", kind="element", stereotype="idlEnum")
    assert f"{MSG}::MessageTypeEnum" in by_stereo and f"{MSG}::Message  " not in by_stereo
    in_p2 = explore.search(session, "", kind="element", package="Model::p2")
    assert in_p2 != "no matches" and all("Model::p2" in x for x in in_p2.splitlines())
    with pytest.raises(InvalidOperationError, match="bad pattern"):
        explore.search(session, "/(/")
    assert explore.search(session, "x", kind="nope").startswith("unknown kind")
    assert explore.search(session, "e", kind="element", page=999).startswith("no page 999")


def test_missing_bounds_are_not_invented():
    from eacore.records import Record

    assert explore._bounds(Record("t_attribute", 1, {})) == ""
    assert explore._bounds(Record("t_attribute", 1, {"attr_lowerbound": "0", "attr_upperbound": "*"})) == "[0..*]"


def test_root_package_without_element_row(nafv4_path, tmp_path):
    session = _snapshot(nafv4_path, tmp_path)
    for text in (
        explore.search(session, ""),
        explore.search(session, "", kind="package"),
        explore.search(session, "Model"),
    ):
        assert any(line.startswith("package  Model  ") for line in text.splitlines()), text
    described = explore.describe(session, "Model")
    assert described.startswith("package  Model  ") and "contents:" in described
    assert explore.usages(session, "Model").startswith("package  Model  ")


def test_orphan_diagram_object_does_not_break_describe_or_usages(nafv4_path, qea_copy, tmp_path):
    # EA models keep diagram-object rows whose diagram was deleted (an "orphan"); its diagram reference stays a raw
    # ID. One such row used to make describe and usages fail for every element.
    import sqlite3

    path = qea_copy(nafv4_path)
    with sqlite3.connect(path) as con:
        con.execute(
            "update t_diagramobjects set Diagram_ID=999999 where Instance_ID=(select min(Instance_ID) from t_diagramobjects)"
        )
    session = _snapshot(path, tmp_path)
    described = explore.describe(session, f"{MSG}::Message")
    used = explore.usages(session, f"{MSG}::MessageHeader")
    assert "Error" not in described and "Error" not in used
    assert "diagrams:" in described
