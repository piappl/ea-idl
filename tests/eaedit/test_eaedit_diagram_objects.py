import re
from datetime import datetime

import pytest

from eacore.changes import Insert, Update
from eacore.embedded import duid, link_ends
from eacore.records import Ref
from eaedit import InvalidOperationError, Session
from eaedit.diagrams.geometry import from_ea, to_ea
from eaedit.diagrams.svg import export_svg, import_svg

FIXED = datetime(2026, 1, 2, 3, 4, 5)
L7 = "{0BA44FD3-F22C-4f9a-AC35-3BDB736B3C80}"
MESSAGE = "{308FD88F-3514-4a20-942B-5CF2F35B042F}"  # Model::core::message::Message, on L7
DATA_MESSAGE = "{9F3D867F-2B36-4ab7-9F95-7EB442443042}"  # generalizes Message
DIAGRAM_TABLES = {"t_diagram", "t_diagramobjects", "t_diagramlinks", "t_xref"}


def _open(path):
    return Session.open(path, policy="off", clock=lambda: FIXED, author="tester")


def _objects(session, diagram):
    ref = Ref("t_diagram", diagram)
    return [r for r in session.working.records("t_diagramobjects") if r.values["attr_diagram_id"] == ref]


def _links(session, diagram):
    ref = Ref("t_diagram", diagram)
    return [r for r in session.working.records("t_diagramlinks") if r.values["attr_diagramid"] == ref]


def _on(session, diagram, element_guid):
    target = Ref("t_object", element_guid)
    return [r for r in _objects(session, diagram) if r.values["attr_object_id"] == target]


def test_rect_round_trip_and_validation():
    values = to_ea([10, 20, 100, 90])
    assert values == {"attr_rectleft": 10, "attr_recttop": -20, "attr_rectright": 100, "attr_rectbottom": -90}
    assert from_ea(values) == (10, 20, 100, 90)
    with pytest.raises(InvalidOperationError):
        to_ea((10, 20, 5, 90))


def test_place_writes_ea_rows(nafv4_path, qea_copy):
    session = _open(qea_copy(nafv4_path))
    diagram = session.create_diagram("Model::p2", "D").guid
    first = session.place(diagram, MESSAGE, rect=(10, 20, 100, 90)).guid
    second = session.place(diagram, DATA_MESSAGE, rect=[200, 20, 290, 90]).guid
    rows = {duid(r.values["attr_objectstyle"]): r.values for r in _objects(session, diagram)}
    assert set(rows) == {first, second}
    values = rows[first]
    assert (values["attr_rectleft"], values["attr_recttop"], values["attr_rectright"], values["attr_rectbottom"]) == (
        10,
        -20,
        100,
        -90,
    )
    for value in rows.values():
        assert re.fullmatch(r"DUID=[0-9A-F]{8};HideIcon=0;", value["attr_objectstyle"])
        assert value["attr_sequence"] == 1


def test_place_adds_links_for_shown_connectors(nafv4_path, qea_copy):
    session = _open(qea_copy(nafv4_path))
    diagram = session.create_diagram("Model::p2", "D").guid
    message = session.place(diagram, MESSAGE, rect=(300, 20, 390, 90)).guid
    assert _links(session, diagram) == []
    data = session.place(diagram, DATA_MESSAGE, rect=(10, 20, 100, 90)).guid
    links = _links(session, diagram)
    assert len(links) == 1
    values = links[0].values
    assert link_ends(values["attr_style"]) == (data, message)  # generalization: DataMessage is the source
    assert values["attr_geometry"].startswith("SX=0;SY=0;EX=0;EY=0;EDGE=2;")  # the target lies to the right
    assert values["attr_hidden"] == 0


def test_place_again_warns_and_adds_a_second_object(nafv4_path, qea_copy):
    session = _open(qea_copy(nafv4_path))
    diagram = session.create_diagram("Model::p2", "D").guid
    session.place(diagram, MESSAGE, rect=(10, 20, 100, 90))
    result = session.place(diagram, MESSAGE, rect=(10, 120, 100, 190))
    assert [w.code for w in result.warnings] == ["already-on-diagram"]
    assert len(_on(session, diagram, MESSAGE)) == 2


def test_place_without_rect_goes_right_of_existing(nafv4_path, qea_copy):
    session = _open(qea_copy(nafv4_path))
    diagram = session.create_diagram("Model::p2", "D").guid
    session.place(diagram, MESSAGE)
    session.place(diagram, DATA_MESSAGE)
    a, b = (from_ea(r.values) for r in sorted(_objects(session, diagram), key=lambda r: r.values["attr_rectleft"]))
    assert (a[2] - a[0], a[3] - a[1]) == (90, 70)
    assert b[0] > a[2] and b[1] == a[1]


def test_part_kept_inside_owner(nafv4_path, qea_copy):
    session = _open(qea_copy(nafv4_path))
    owner, part = _owner_and_part(session)
    diagram = session.create_diagram("Model::p2", "D").guid
    session.place(diagram, owner, rect=(100, 100, 400, 400))
    result = session.place(diagram, part, rect=(500, 500, 570, 554))
    assert "moved-inside-owner" in [w.code for w in result.warnings]
    inside = from_ea(_on(session, diagram, part)[0].values)
    assert (inside[2] - inside[0], inside[3] - inside[1]) == (70, 54)
    assert 100 <= inside[0] and inside[2] <= 400 and 100 <= inside[1] and inside[3] <= 400
    assert (
        _on(session, diagram, owner)[0].values["attr_sequence"] > _on(session, diagram, part)[0].values["attr_sequence"]
    )


def _owner_and_part(session):
    part = next(r for r in session.working.records("t_object") if r.values["attr_object_type"] == "Part")
    return session.working.resolve(part.values["attr_parentid"]).key, part.key


def test_set_bounds_keeps_link_geometry(nafv4_path, qea_copy):
    session = _open(qea_copy(nafv4_path))
    before = {r.key: r.values["attr_geometry"] for r in _links(session, L7)}
    assert len(before) == 4
    old = from_ea(_on(session, L7, MESSAGE)[0].values)
    session.set_bounds(L7, MESSAGE, rect=(old[0] + 50, old[1] + 40, old[2] + 80, old[3] + 40))
    assert from_ea(_on(session, L7, MESSAGE)[0].values) == (old[0] + 50, old[1] + 40, old[2] + 80, old[3] + 40)
    assert {r.key: r.values["attr_geometry"] for r in _links(session, L7)} == before


def test_set_bounds_needs_duid_for_duplicates(nafv4_path, qea_copy):
    session = _open(qea_copy(nafv4_path))
    diagram = session.create_diagram("Model::p2", "D").guid
    first = session.place(diagram, MESSAGE, rect=(10, 20, 100, 90)).guid
    session.place(diagram, MESSAGE, rect=(10, 120, 100, 190))
    with pytest.raises(InvalidOperationError):
        session.set_bounds(diagram, MESSAGE, rect=(0, 0, 50, 50))
    session.set_bounds(diagram, first, rect=(0, 0, 50, 50))
    rects = {duid(r.values["attr_objectstyle"]): from_ea(r.values) for r in _on(session, diagram, MESSAGE)}
    assert rects[first] == (0, 0, 50, 50)
    assert [r for d, r in rects.items() if d != first] == [(10, 120, 100, 190)]


def test_set_stacking(nafv4_path, qea_copy):
    session = _open(qea_copy(nafv4_path))
    row = _on(session, L7, MESSAGE)[0]
    assert session.set_stacking(L7, MESSAGE, 9).guid == duid(row.values["attr_objectstyle"])
    after = session.working.get("t_diagramobjects", row.key)
    assert after.values == {**row.values, "attr_sequence": 9}
    session.set_stacking(L7, duid(row.values["attr_objectstyle"]), 2)
    assert session.working.get("t_diagramobjects", row.key).values["attr_sequence"] == 2
    for bad in (0, -1, "x", 1.5):
        with pytest.raises(InvalidOperationError):
            session.set_stacking(L7, MESSAGE, bad)


def test_remove_and_hide(nafv4_path, qea_copy):
    session = _open(qea_copy(nafv4_path))
    gone = duid(_on(session, L7, MESSAGE)[0].values["attr_objectstyle"])
    session.remove_from_diagram(L7, MESSAGE)
    assert _on(session, L7, MESSAGE) == []
    remaining = _links(session, L7)
    assert len(remaining) == 2  # the two links at Message went; DataMessage -> other class and the note link stay
    assert gone not in {e for r in remaining for e in link_ends(r.values["attr_style"])}

    connector = remaining[0].key[1]
    session.hide_connector(L7, connector.key)
    hidden = lambda: session.working.get("t_diagramlinks", remaining[0].key).values["attr_hidden"]  # noqa: E731
    assert hidden() == 1
    session.show_connector(L7, connector.key)
    assert hidden() == 0


def test_show_connector_writes_missing_row(nafv4_path, qea_copy):
    session = _open(qea_copy(nafv4_path))
    link = _links(session, L7)[0]
    session.working.remove("t_diagramlinks", link.key)
    assert len(_links(session, L7)) == 3
    session.show_connector(L7, link.key[1].key)
    assert len(_links(session, L7)) == 4


def test_lifeline_style_on_sequence_diagram(nafv4_path, qea_copy):
    session = _open(qea_copy(nafv4_path))
    _, part = _owner_and_part(session)
    diagram = session.create_diagram("Model::p2", "Seq", "Sequence").guid
    session.place(diagram, part)
    style = _on(session, diagram, part)[0].values["attr_objectstyle"]
    assert re.fullmatch(r"DUID=[0-9A-F]{8};NSL=0;BCol=-1;.*HideIcon=0;", style)


def _allowed(session, changes) -> list:
    """Changes outside what diagram operations may write: diagram tables, Note objects, NoteLink connectors, the
    diagram's own t_xref properties, and on a sequence message DiagramID/SeqNo/PDATA5."""
    message_columns = {"attr_diagramid", "attr_seqno", "attr_pdata5"}

    def row(table, key):
        return session.working.get(table, key) or session.original.get(table, key)

    bad = []
    for change in [*changes.inserts, *changes.updates, *changes.deletes]:
        table, key = (
            (change.record.table, change.record.key) if isinstance(change, Insert) else (change.table, change.key)
        )
        values = row(table, key).values
        if table in ("t_diagram", "t_diagramobjects", "t_diagramlinks"):
            continue
        if table == "t_object" and values.get("attr_object_type") == "Note":
            continue
        if table == "t_connector" and values.get("attr_connector_type") == "NoteLink":
            continue
        if table == "t_connector" and values.get("attr_connector_type") == "Sequence" and isinstance(change, Update):
            if set(change.changes) <= message_columns:
                continue
        if table == "t_xref" and values.get("attr_type") == "diagram properties":
            continue
        bad.append((type(change).__name__, table, key))
    return bad


def test_diagram_ops_change_no_model_rows(nafv4_path, qea_copy):
    session = _open(qea_copy(nafv4_path))
    owner, part = _owner_and_part(session)
    session.remove_from_diagram(L7, DATA_MESSAGE)
    session.place(L7, DATA_MESSAGE)
    session.set_bounds(L7, MESSAGE, rect=(0, 0, 60, 60))
    link = _links(session, L7)[0].key[1].key
    session.hide_connector(L7, link)
    session.place(L7, part)
    session.remove_from_diagram(L7, part)
    note = session.add_note(L7, "about it").guid
    session.link_note(note, MESSAGE)
    p6 = "{EB2441A2-EE65-42fe-A5FD-350317D3216F}"
    message = next(
        r.key
        for r in session.working.records("t_connector")
        if r.values["attr_connector_type"] == "Sequence" and r.values["attr_diagramid"] == Ref("t_diagram", p6)
    )
    on_message = session.add_note(p6, "on a message").guid
    session.link_note(on_message, message)
    session.show_message(p6, message, order=9, offset=-120)
    session.layout(L7, {"pattern": "suggest"})
    svg = export_svg(session, L7)
    first = re.search(r'data-ea-rect="(-?\d+),(-?\d+),(-?\d+),(-?\d+)"', svg)
    left, top, right, bottom = (int(v) for v in first.groups())
    svg = svg.replace(first.group(0), f'data-ea-rect="{left + 7},{top},{right + 7},{bottom}"', 1)
    svg = re.sub(r'data-ea-text="about it"', 'data-ea-text="edited"', svg)
    imported = import_svg(session, svg)
    assert [r for r in imported if r.guid is not None]
    changes = session.changes()
    assert not changes.is_empty()
    touched = {c.record.table for c in changes.inserts} | {c.table for c in changes.deletes}
    touched |= {c.table for c in changes.updates}
    assert {"t_object", "t_connector"} <= touched
    assert _allowed(session, changes) == []


def test_parts_without_rect_do_not_overlap_in_owner(nafv4_path, qea_copy):
    session = _open(qea_copy(nafv4_path))
    owner = _owner_and_part(session)[0]
    parts = [
        r.key
        for r in session.working.records("t_object")
        if r.values["attr_object_type"] == "Part" and r.values["attr_parentid"] == Ref("t_object", owner)
    ][:2]
    assert len(parts) == 2
    diagram = session.create_diagram("Model::p2", "D").guid
    session.place(diagram, owner, rect=(100, 100, 400, 400))
    for part in parts:
        assert session.place(diagram, part).warnings == []
    a, b = (from_ea(_on(session, diagram, p)[0].values) for p in parts)
    assert a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1]
    for r in (a, b):
        assert 100 <= r[0] and r[2] <= 400 and 100 <= r[1] and r[3] <= 400


def test_rect_is_logged_as_list(nafv4_path, qea_copy):
    session = _open(qea_copy(nafv4_path))
    diagram = session.create_diagram("Model::p2", "D").guid
    session.place(diagram, MESSAGE, rect=(10, 20, 100, 90))
    assert session.log[-1].args["rect"] == [10, 20, 100, 90]
    session.set_bounds(diagram, MESSAGE, rect=(0, 0, 50, 50))
    assert session.log[-1].args["rect"] == [0, 0, 50, 50]
