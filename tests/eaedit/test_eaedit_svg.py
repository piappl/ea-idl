import hashlib
import xml.etree.ElementTree as ET
from datetime import datetime

import pytest

from eacore.records import Ref
from eaedit import InvalidOperationError, Session
from eaedit.diagrams.render import render_working
from eaedit.diagrams.svg import export_svg, import_svg

FIXED = datetime(2026, 1, 2, 3, 4, 5)
L7 = "{0BA44FD3-F22C-4f9a-AC35-3BDB736B3C80}"
P6 = "{EB2441A2-EE65-42fe-A5FD-350317D3216F}"
UNKNOWN = "{00000000-1111-2222-3333-444444444444}"


def _open(path):
    return Session.open(path, policy="off", clock=lambda: FIXED, author="tester")


def _groups(root):
    return [e for e in root.iter() if e.get("data-ea-kind") or e.get("data-ea-guid")]


def _parse(svg):
    return ET.fromstring(svg.encode("utf-8"))


def _remove(root, element):
    for parent in root.iter():
        if element in list(parent):
            parent.remove(element)
            return
    raise AssertionError("element not found")


def _text(root):
    return ET.tostring(root, encoding="unicode")


def _link_ends(session, diagram):
    """``(connector GUID, start GUID, end GUID)`` of each link row on ``diagram`` whose connector is not a NoteLink."""
    this = Ref("t_diagram", session.find(diagram, kinds=("diagram",)).key)
    found = []
    for link in session.working.records("t_diagramlinks"):
        if link.values["attr_diagramid"] != this:
            continue
        connector = session.working.resolve(link.values["attr_connectorid"])
        start = session.working.resolve(connector.values["attr_start_object_id"])
        end = session.working.resolve(connector.values["attr_end_object_id"])
        found.append((connector.values["attr_connector_type"], connector.key, start.key, end.key))
    return found


def test_round_trip_every_nafv4_diagram(nafv4_path, qea_copy):
    session = _open(qea_copy(nafv4_path))
    diagrams = [r.key for r in session.working.records("t_diagram")]
    assert len(diagrams) == 11
    for diagram in diagrams:
        svg = export_svg(session, diagram)
        root = _parse(svg)
        assert root.get("data-ea-diagram") == diagram
        import_svg(session, svg)
        assert session.changes().is_empty(), diagram
        assert not session.log, diagram


def test_export_markup(nafv4_path, qea_copy):
    session = _open(qea_copy(nafv4_path))
    root = _parse(export_svg(session, P6))
    assert root.get("data-ea-name") == "p6"
    # The MDG view, as create_diagram takes it.
    assert root.get("data-ea-type") == "NAFv4-Core Physical Resource Specification Viewpoints::P6 - Resource Sequence"
    kinds = sorted(g.get("data-ea-kind") or "" for g in _groups(root))
    # Two lifelines, one interaction fragment (read-only), two notes, three messages, one NoteLink and
    # note 77's attachment to a message.
    assert kinds == [
        "element",
        "element",
        "message",
        "message",
        "message",
        "note",
        "note",
        "notelink",
        "notelink",
        "readonly",
    ]
    for group in _groups(root):
        if group.get("data-ea-kind") in ("element", "note", "readonly"):
            assert len(group.get("data-ea-rect").split(",")) == 4 and group.get("data-ea-duid")


def test_import_moves_and_removes(nafv4_path, qea_copy):
    session = _open(qea_copy(nafv4_path))
    root = _parse(export_svg(session, L7))
    objects = [g for g in _groups(root) if g.get("data-ea-kind") == "element"]
    moved, removed = objects[0], objects[1]
    left, top, right, bottom = (int(v) for v in moved.get("data-ea-rect").split(","))
    moved.set("data-ea-rect", f"{left + 40},{top + 10},{right + 40},{bottom + 10}")
    gone = removed.get("data-ea-guid")
    links = [c for _, c, s, e in _link_ends(session, L7) if gone in (s, e)]
    assert links
    _remove(root, removed)
    for group in _groups(root):
        if group.get("data-ea-guid") in links:
            _remove(root, group)
    import_svg(session, _text(root))
    changes = session.changes()
    assert not changes.inserts
    rect = ["attr_rectbottom", "attr_rectleft", "attr_rectright", "attr_recttop"]
    assert [(u.table, sorted(u.changes)) for u in changes.updates] == [("t_diagramobjects", rect)]
    assert changes.updates[0].key[1] == moved.get("data-ea-duid")
    assert [d.key[1] for d in changes.deletes if d.table == "t_diagramobjects"] == [removed.get("data-ea-duid")]
    assert sorted(d.key[1].key for d in changes.deletes if d.table == "t_diagramlinks") == sorted(links)
    assert {d.table for d in changes.deletes} == {"t_diagramobjects", "t_diagramlinks"}


def test_import_new_diagram_from_scratch(nafv4_path, qea_copy):
    session = _open(qea_copy(nafv4_path))
    package = session.working.resolve(session.find(L7, kinds=("diagram",))).values["attr_package_id"].key
    kind, connector, start, end = next(t for t in _link_ends(session, L7) if t[0] != "NoteLink")
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" data-ea-name="V" data-ea-type="Class">'
        f'<g data-ea-guid="{start}" data-ea-rect="30,30,150,100" data-ea-kind="element"/>'
        f'<g data-ea-guid="{end}" data-ea-rect="300,30,420,100" data-ea-kind="element"/>'
        "</svg>"
    )
    import_svg(session, svg, owner=package)
    created = [r for r in session.working.records("t_diagram") if r.values["attr_name"] == "V"]
    assert len(created) == 1
    this = Ref("t_diagram", created[0].key)
    assert len([o for o in session.working.records("t_diagramobjects") if o.values["attr_diagram_id"] == this]) == 2
    links = [r for r in session.working.records("t_diagramlinks") if r.values["attr_diagramid"] == this]
    assert [r.values["attr_connectorid"] for r in links] == [Ref("t_connector", connector)]
    # The new diagram exports and re-imports without changes.
    before = len(session.log)
    import_svg(session, export_svg(session, created[0].key))
    assert len(session.log) == before


def test_import_from_scratch_twice_is_idempotent(nafv4_path, qea_copy):
    session = _open(qea_copy(nafv4_path))
    package = session.working.resolve(session.find(L7, kinds=("diagram",))).values["attr_package_id"].key
    _, _, start, _ = next(t for t in _link_ends(session, L7) if t[0] != "NoteLink")
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" data-ea-name="V" data-ea-type="Class">'
        f'<g data-ea-guid="{start}" data-ea-rect="30,30,150,100" data-ea-kind="element" data-ea-z="2"/>'
        '<g data-ea-id="n1" data-ea-rect="300,30,415,85" data-ea-kind="note" data-ea-text="hi" data-ea-z="7"/>'
        "</svg>"
    )
    import_svg(session, svg, owner=package)
    created = next(r.key for r in session.working.records("t_diagram") if r.values["attr_name"] == "V")
    note = next(
        r.key
        for r in session.working.records("t_object")
        if r.values["attr_object_type"] == "Note" and r.values["attr_note"] == "hi"
    )
    # The same file again, now naming the diagram and the note it made: nothing left to stage.
    again = svg.replace("<svg ", f'<svg data-ea-diagram="{created}" ').replace(
        'data-ea-id="n1"', f'data-ea-guid="{note}"'
    )
    before = len(session.log)
    import_svg(session, again)
    assert len(session.log) == before


def test_import_refuses_unknown_guid(nafv4_path, qea_copy):
    session = _open(qea_copy(nafv4_path))
    root = _parse(export_svg(session, L7))
    # A valid move first, so a refusal that staged anything would show.
    first = next(g for g in _groups(root) if g.get("data-ea-kind") == "element")
    left, top, right, bottom = (int(v) for v in first.get("data-ea-rect").split(","))
    first.set("data-ea-rect", f"{left + 5},{top},{right + 5},{bottom}")
    ET.SubElement(root, "g", {"data-ea-guid": UNKNOWN, "data-ea-kind": "element", "data-ea-rect": "0,0,10,10"})
    with pytest.raises(InvalidOperationError, match=UNKNOWN.strip("{}")):
        import_svg(session, _text(root))
    assert session.changes().is_empty() and not session.log


@pytest.mark.parametrize("missing", ["data-ea-rect", "data-ea-guid"])
def test_import_refuses_shape_without(nafv4_path, qea_copy, missing):
    session = _open(qea_copy(nafv4_path))
    root = _parse(export_svg(session, L7))
    group = next(g for g in _groups(root) if g.get("data-ea-kind") == "element")
    guid = group.get("data-ea-guid")
    del group.attrib[missing]
    # The message names the group by its GUID, or says which attribute it lacks.
    with pytest.raises(InvalidOperationError, match=guid.strip("{}") if missing == "data-ea-rect" else missing):
        import_svg(session, _text(root))
    assert session.changes().is_empty()


def test_import_refuses_connector_without_ends(nafv4_path, qea_copy):
    session = _open(qea_copy(nafv4_path))
    root = _parse(export_svg(session, L7))
    _, connector, start, _ = next(t for t in _link_ends(session, L7) if t[0] != "NoteLink")
    _remove(root, next(g for g in _groups(root) if g.get("data-ea-guid") == start))
    with pytest.raises(InvalidOperationError, match=connector.strip("{}")):
        import_svg(session, _text(root))
    assert session.changes().is_empty()


def test_import_refuses_part_outside_owner(nafv4_path, qea_copy):
    session = _open(qea_copy(nafv4_path))
    p2 = next(r.key for r in session.working.records("t_diagram") if r.values["attr_name"] == "p2")
    root = _parse(export_svg(session, p2))
    part = next(
        g
        for g in _groups(root)
        if session.working.resolve(session.find(g.get("data-ea-guid"), kinds=("element",))).values["attr_object_type"]
        == "Part"
    )
    part.set("data-ea-rect", "5000,5000,5070,5054")
    with pytest.raises(InvalidOperationError, match=part.get("data-ea-guid").strip("{}")):
        import_svg(session, _text(root))
    assert session.changes().is_empty()


def test_round_trip_diagrams_built_by_ops(nafv4_path, qea_copy):
    session = _open(qea_copy(nafv4_path))
    part = next(r for r in session.working.records("t_object") if r.values["attr_object_type"] == "Part")
    owner = part.values["attr_parentid"].key
    # A Part placed before its owner, and an owner moved away from its Part: both leave the Part outside.
    before_owner = session.create_diagram("Model::p2", "A").guid
    session.place(before_owner, part.key, rect=(500, 500, 570, 554))
    session.place(before_owner, owner, rect=(10, 10, 200, 200))
    moved_away = session.create_diagram("Model::p2", "B").guid
    session.place(moved_away, owner, rect=(10, 10, 300, 300))
    session.place(moved_away, part.key)
    session.set_bounds(moved_away, owner, rect=(1000, 1000, 1290, 1290))
    for diagram in (before_owner, moved_away):
        svg = export_svg(session, diagram)
        before = len(session.log)
        import_svg(session, svg)
        assert len(session.log) == before, diagram
        # The break is carried as it is; a file that moves the Part (still outside) is refused.
        root = _parse(svg)
        shape = next(g for g in _groups(root) if g.get("data-ea-guid") == part.key)
        shape.set("data-ea-rect", "700,700,770,754")
        with pytest.raises(InvalidOperationError, match="inside its owner"):
            import_svg(session, _text(root))
        assert len(session.log) == before


def test_readonly_objects_kept(nafv4_path, qea_copy):
    session = _open(qea_copy(nafv4_path))
    root = _parse(export_svg(session, P6))
    fragment = next(g for g in _groups(root) if g.get("data-ea-kind") == "readonly")
    _remove(root, fragment)
    results = import_svg(session, _text(root))
    assert session.changes().is_empty()
    assert any(w.code == "readonly-kept" for r in results for w in r.warnings)


def test_note_text_round_trip_non_ascii(nafv4_path, qea_copy):
    session = _open(qea_copy(nafv4_path))
    text = 'Zażółć gęślą jaźń\r\nline two & <three> "quoted"\ttab'
    root = _parse(export_svg(session, L7))
    note = next(g for g in _groups(root) if g.get("data-ea-kind") == "note")
    target = next(g for g in _groups(root) if g.get("data-ea-kind") == "element").get("data-ea-guid")
    note.set("data-ea-text", text)
    ET.SubElement(
        root, "g", {"data-ea-kind": "note", "data-ea-id": "n1", "data-ea-rect": "400,400,515,455", "data-ea-text": text}
    )
    ET.SubElement(root, "g", {"data-ea-kind": "notelink", "data-ea-from": target, "data-ea-to": "n1"})
    import_svg(session, _text(root))
    notes = [r for r in session.working.records("t_object") if r.values.get("attr_note") == text]
    assert len(notes) == 2
    new = next(n for n in notes if n.values["attr_name"] is None and n.key not in _text(root))
    links = [
        r
        for r in session.working.records("t_connector")
        if r.values["attr_connector_type"] == "NoteLink"
        and r.values["attr_start_object_id"] == Ref("t_object", target)
        and r.values["attr_end_object_id"] == Ref("t_object", new.key)
    ]
    assert len(links) == 1
    # Exported again, the text survives the SVG attribute exactly, and re-importing changes nothing.
    svg = export_svg(session, L7)
    texts = [g.get("data-ea-text") for g in _groups(_parse(svg)) if g.get("data-ea-kind") == "note"]
    assert texts.count(text) == 2
    before = len(session.log)
    import_svg(session, svg)
    assert len(session.log) == before


def test_render_working_shows_staged_changes(nafv4_path, qea_copy):
    path = qea_copy(nafv4_path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    session = _open(path)
    element = next(
        r.key
        for r in session.working.records("t_object")
        if r.values["attr_object_type"] == "Class" and r.key not in export_svg(session, L7)
    )
    session.place(L7, element, rect=(600, 50, 700, 120))
    rendered = render_working(session, [L7])
    assert list(rendered) == [L7]
    assert element in rendered[L7].svg and rendered[L7].name == "L7" and rendered[L7].png is None
    assert hashlib.sha256(path.read_bytes()).hexdigest() == digest


def test_import_stacking_order(nafv4_path, qea_copy):
    session = _open(qea_copy(nafv4_path))
    root = _parse(export_svg(session, L7))
    group = next(g for g in _groups(root) if g.get("data-ea-kind") == "element")
    z = int(group.get("data-ea-z")) + 7
    group.set("data-ea-z", str(z))
    import_svg(session, _text(root))
    assert [entry.name for entry in session.log] == ["set_stacking"]
    changes = session.changes()
    assert [(u.table, u.key[1], u.changes["attr_sequence"][1]) for u in changes.updates] == [
        ("t_diagramobjects", group.get("data-ea-duid"), z)
    ]
    assert not changes.inserts and not changes.deletes


def test_import_refuses_zero_stacking_naming_the_group(nafv4_path, qea_copy):
    session = _open(qea_copy(nafv4_path))
    root = _parse(export_svg(session, L7))
    group = next(g for g in _groups(root) if g.get("data-ea-kind") == "element")
    group.set("data-ea-z", "0")
    with pytest.raises(InvalidOperationError, match=rf"{group.get('data-ea-guid').strip('{}')}.*data-ea-z"):
        import_svg(session, _text(root))
    assert session.changes().is_empty() and not session.log


def test_object_without_stacking_round_trips(nafv4_path, qea_copy):
    import sqlite3

    path = qea_copy(nafv4_path)
    with sqlite3.connect(path) as conn:
        conn.execute(
            "UPDATE t_diagramobjects SET Sequence = 0 WHERE rowid = (SELECT min(o.rowid) FROM t_diagramobjects o"
            " JOIN t_diagram d ON d.Diagram_ID = o.Diagram_ID WHERE d.ea_guid = ?)",
            (L7,),
        )
    session = _open(path)
    svg = export_svg(session, L7)
    # Sequence 0 is no stacking order eaedit could write back, so the file leaves it out.
    assert len([g for g in _groups(_parse(svg)) if g.get("data-ea-rect") and g.get("data-ea-z") is None]) == 1
    import_svg(session, svg)
    assert not session.log


@pytest.mark.parametrize("regroup", [False, True])
@pytest.mark.parametrize("numbers", [(2, 1, 3, 4), (4, 3, 1, 2), (4, 3, 2, 1), (2, 4, 1, 3)])
def test_import_reordered_messages_lands_the_files_numbers(nafv4_path, qea_copy, numbers, regroup):
    session = _open(qea_copy(nafv4_path))
    asset1, asset2 = "{787820BD-43DC-424c-81C3-BA7A076C417C}", "{45EF1F2C-6C51-49c0-8EFE-2E4CED2BC1CF}"
    session.show_message(P6, session.connect(asset1, asset2, type="Message", name="Fourth").guid)
    root = _parse(export_svg(session, P6))
    messages = [g for g in _groups(root) if g.get("data-ea-kind") == "message"]
    for group, number in zip(messages, numbers):
        group.set("data-ea-seq", str(number))
    if regroup:  # the groups' order in the file follows the new numbers
        for group in messages:
            _remove(root, group)
        for group in sorted(messages, key=lambda g: int(g.get("data-ea-seq"))):
            root.append(group)
    import_svg(session, _text(root))
    found = {g.get("data-ea-guid"): session.working.get("t_connector", g.get("data-ea-guid")) for g in messages}
    assert [found[g.get("data-ea-guid")].values["attr_seqno"] for g in messages] == list(numbers)
    # the same file again stages nothing
    before = len(session.log)
    import_svg(session, export_svg(session, P6))
    assert len(session.log) == before


def test_import_with_a_message_left_out_keeps_numbers_unique(nafv4_path, qea_copy):
    session = _open(qea_copy(nafv4_path))
    root = _parse(export_svg(session, P6))
    messages = [g for g in _groups(root) if g.get("data-ea-kind") == "message"]
    # leave out a message no note link in the file points at
    linked = {
        g.get(k) for g in _groups(root) if g.get("data-ea-kind") == "notelink" for k in ("data-ea-from", "data-ea-to")
    }
    left_out = next(g for g in messages if g.get("data-ea-guid") not in linked)
    first, second = [g for g in messages if g is not left_out]
    _remove(root, left_out)
    first.set("data-ea-seq", "3")
    second.set("data-ea-seq", "2")
    import_svg(session, _text(root))
    seqno = lambda g: session.working.get("t_connector", g.get("data-ea-guid")).values["attr_seqno"]  # noqa: E731
    assert [seqno(second), seqno(first), seqno(left_out)] == [1, 2, 3]


def test_import_hand_written_gapped_numbers_stages_once(nafv4_path, qea_copy):
    session = _open(qea_copy(nafv4_path))
    root = _parse(export_svg(session, P6))
    messages = [g for g in _groups(root) if g.get("data-ea-kind") == "message"]
    for group, number in zip(messages, (5, 1, 3)):
        group.set("data-ea-seq", str(number))
    text = _text(root)
    import_svg(session, text)
    seqno = lambda g: session.working.get("t_connector", g.get("data-ea-guid")).values["attr_seqno"]  # noqa: E731
    assert [seqno(g) for g in messages] == [3, 1, 2]
    before = len(session.log)
    import_svg(session, text)
    assert len(session.log) == before


def test_import_new_message_takes_the_files_number(nafv4_path, qea_copy):
    session = _open(qea_copy(nafv4_path))
    asset1, asset2 = "{787820BD-43DC-424c-81C3-BA7A076C417C}", "{45EF1F2C-6C51-49c0-8EFE-2E4CED2BC1CF}"
    new = session.connect(asset1, asset2, type="Message", name="New").guid
    root = _parse(export_svg(session, P6))
    messages = [g for g in _groups(root) if g.get("data-ea-kind") == "message"]
    for group in messages:
        group.set("data-ea-seq", str(int(group.get("data-ea-seq")) + 1))
    ET.SubElement(root, "g", {**messages[0].attrib, "data-ea-guid": new, "data-ea-seq": "1"})
    import_svg(session, _text(root))
    assert session.working.get("t_connector", new).values["attr_seqno"] == 1
    assert [session.working.get("t_connector", g.get("data-ea-guid")).values["attr_seqno"] for g in messages] == [
        2,
        3,
        4,
    ]


def test_import_keeps_stacking_zero_when_stored_zero(nafv4_path, qea_copy):
    import sqlite3

    path = qea_copy(nafv4_path)
    with sqlite3.connect(path) as conn:
        conn.execute(
            "UPDATE t_diagramobjects SET Sequence = 0 WHERE rowid = (SELECT min(o.rowid) FROM t_diagramobjects o"
            " JOIN t_diagram d ON d.Diagram_ID = o.Diagram_ID WHERE d.ea_guid = ?)",
            (L7,),
        )
    session = _open(path)
    root = _parse(export_svg(session, L7))
    for group in _groups(root):
        if group.get("data-ea-rect") and group.get("data-ea-z") is None:
            group.set("data-ea-z", "0")  # as files exported before Sequence 0 was left out carry it
    import_svg(session, _text(root))
    assert not session.log


def test_import_message_order_and_offset(nafv4_path, qea_copy):
    session = _open(qea_copy(nafv4_path))
    root = _parse(export_svg(session, P6))
    first, second, _ = [g for g in _groups(root) if g.get("data-ea-kind") == "message"]
    first.set("data-ea-seq", "2")
    second.set("data-ea-seq", "1")
    second.set("data-ea-offset", "-60")
    import_svg(session, _text(root))
    changes = session.changes()
    assert not changes.inserts and not changes.deletes
    assert {u.table for u in changes.updates} == {"t_connector"}
    rows = {g.get("data-ea-guid"): session.working.get("t_connector", g.get("data-ea-guid")) for g in (first, second)}
    assert rows[first.get("data-ea-guid")].values["attr_seqno"] == 2
    assert rows[second.get("data-ea-guid")].values["attr_seqno"] == 1
    assert "SY=-60;" in rows[second.get("data-ea-guid")].values["attr_pdata5"]
