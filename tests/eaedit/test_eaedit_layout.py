from datetime import datetime

import pytest

from eacore.records import Ref
from eaedit import InvalidOperationError, Session
from eaedit.diagrams.geometry import from_ea
from eaedit.layout import Box, Edge, contain, fits, hub, layers, split_suggestion, suggest
from eaedit.ops.layout import plan_layout, size_for

FIXED = datetime(2026, 1, 2, 3, 4, 5)
L7 = "{0BA44FD3-F22C-4f9a-AC35-3BDB736B3C80}"
MESSAGE = "{308FD88F-3514-4a20-942B-5CF2F35B042F}"  # Model::core::message::Message, on L7
DATA_MESSAGE = "{9F3D867F-2B36-4ab7-9F95-7EB442443042}"  # generalizes Message


def _open(path):
    return Session.open(path, policy="off", clock=lambda: FIXED, author="tester")


def _boxes(*specs) -> dict[str, Box]:
    return {key: Box(key, width, height, parent) for key, width, height, parent in specs}


def _overlap(a, b) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def _no_overlaps(rects) -> bool:
    items = list(rects.values())
    return not any(_overlap(a, b) for i, a in enumerate(items) for b in items[i + 1 :])


def _objects(session, diagram):
    ref = Ref("t_diagram", diagram)
    return [r for r in session.working.records("t_diagramobjects") if r.values["attr_diagram_id"] == ref]


def test_layers_deterministic_no_overlap():
    boxes = _boxes(("a", 90, 70, None), ("b", 120, 50, None), ("c", 60, 40, None), ("d", 200, 90, None))
    rows = [["a"], ["b", "c", "d"]]
    first = layers(rows, boxes)
    assert first == layers(rows, boxes)
    assert set(first) == set(boxes)
    assert _no_overlaps(first)
    # Each box keeps its size; the second row lies below the first, in order, and both are centred on each other.
    for key, (left, top, right, bottom) in first.items():
        assert (right - left, bottom - top) == (boxes[key].width, boxes[key].height)
    assert first["b"][1] >= first["a"][3] + 60
    assert first["b"][2] + 40 <= first["c"][0] and first["c"][2] + 40 <= first["d"][0]
    row = (first["b"][0] + first["d"][2]) / 2
    assert abs((first["a"][0] + first["a"][2]) / 2 - row) <= 1
    across = layers(rows, boxes, direction="right")
    assert _no_overlaps(across)
    assert across["b"][0] >= across["a"][2] + 60 and across["c"][1] >= across["b"][3] + 40


def test_hub_sides():
    boxes = _boxes(*[(k, 90, 70, None) for k in ("hub", "up1", "up2", "down", "west", "east1", "east2")])
    groups = {"above": ["up1", "up2"], "below": ["down"], "left": ["west"], "right": ["east1", "east2"]}
    rects = hub("hub", groups, boxes)
    assert rects == hub("hub", groups, boxes)
    assert _no_overlaps(rects)
    center = rects["hub"]
    assert all(rects[k][3] <= center[1] for k in groups["above"])
    assert rects["down"][1] >= center[3]
    assert rects["west"][2] <= center[0]
    assert all(rects[k][0] >= center[2] for k in groups["right"])
    with pytest.raises(ValueError):
        hub("hub", {"around": ["west"]}, boxes)


def test_contain_grows_owner():
    boxes = _boxes(("owner", 90, 70, None), *[(f"p{i}", 70, 54, "owner") for i in range(5)])
    rects = contain("owner", [f"p{i}" for i in range(5)], boxes)
    owner = rects["owner"]
    assert owner[2] - owner[0] > 90 and owner[3] - owner[1] > 70
    parts = {k: v for k, v in rects.items() if k != "owner"}
    assert _no_overlaps(parts)
    for left, top, right, bottom in parts.values():
        assert owner[0] + 20 <= left and right <= owner[2] - 20 and bottom <= owner[3] - 20 and top > owner[1]
    # An owner already big enough keeps its size.
    big = _boxes(("owner", 900, 700, None), ("p", 70, 54, "owner"))
    assert contain("owner", ["p"], big)["owner"] == (0, 0, 900, 700)


def test_suggest_follows_edges():
    boxes = _boxes(*[(k, 90, 70, None) for k in "abcde"])
    edges = [Edge("a", "b"), Edge("b", "c"), Edge("a", "d"), Edge("d", "c"), Edge("c", "a"), Edge("e", "e")]
    rects = suggest(boxes, edges)
    assert rects == suggest(boxes, list(reversed(edges)))
    assert _no_overlaps(rects)
    # c -> a closes a cycle and is dropped; every other edge points down the page.
    for source, target in (("a", "b"), ("b", "c"), ("a", "d"), ("d", "c")):
        assert rects[source][3] <= rects[target][1]


def test_split_suggestion_fits_pages():
    boxes = _boxes(*[(f"n{i:02}", 150, 90, None) for i in range(30)])
    edges = [Edge(f"n{i:02}", f"n{i + 1:02}") for i in range(29)]
    rects = layers([list(boxes)], boxes)
    assert not fits(rects)
    groups = split_suggestion(rects, edges, (791, 1134))
    assert sorted(k for group in groups for k in group) == sorted(boxes)
    assert len(groups) > 1
    for group in groups:
        chosen = {k: boxes[k] for k in group}
        assert fits(suggest(chosen, [e for e in edges if e.source in chosen and e.target in chosen]))
    # A chain cut into consecutive runs: only the edges between groups are cut.
    cut = sum(1 for e in edges if not any(e.source in g and e.target in g for g in groups))
    assert cut == len(groups) - 1


def test_size_for_grows_with_text(nafv4_path):
    session = _open(nafv4_path)
    width, height = size_for(session, DATA_MESSAGE)
    assert width >= 90 and height >= 70
    assert size_for(session, DATA_MESSAGE) == (width, height)


def test_layout_op_on_nafv4_l7(nafv4_path, qea_copy):
    session = _open(qea_copy(nafv4_path))
    geometry = {r.key: r.values["attr_geometry"] for r in session.working.records("t_diagramlinks")}
    assert session.layout(L7, {"pattern": "suggest"}).guid == L7
    rects = {r.key: from_ea(r.values) for r in _objects(session, L7)}
    assert len(rects) == 4 and _no_overlaps(rects)
    assert {r.key: r.values["attr_geometry"] for r in session.working.records("t_diagramlinks")} == geometry
    # Dependency direction: the source of each connector sits above its target.
    by_element = {r.values["attr_object_id"].key: from_ea(r.values) for r in _objects(session, L7)}
    assert by_element[DATA_MESSAGE][3] <= by_element[MESSAGE][1]
    # A second run changes nothing, and the plan reports what was applied.
    session.layout(L7, {"pattern": "suggest"})
    assert {r.key: from_ea(r.values) for r in _objects(session, L7)} == rects
    report = plan_layout(session, L7, {"pattern": "suggest"})
    assert report.fits and report.split is None
    assert {k: v for k, v in report.rects.items()} == by_element
    assert session.log[-1].args == {"diagram": L7, "spec": {"pattern": "suggest"}}


def test_layout_op_places_missing_and_contains_parts(nafv4_path, qea_copy):
    session = _open(qea_copy(nafv4_path))
    diagram = session.create_diagram("Model::p2", "D").guid
    owner = session.create_element("Model::p2", "Owner", type="Class").guid
    parts = [session.create_element(name=f"Part{i}", type="Part", parent=owner).guid for i in range(3)]
    session.layout(diagram, {"pattern": "layers", "rows": [["Model::core::message::Message"], [owner]]})
    rows = {r.values["attr_object_id"].key: from_ea(r.values) for r in _objects(session, diagram)}
    assert set(rows) == {MESSAGE, owner}
    session.layout(diagram, {"pattern": "layers", "rows": [[MESSAGE], [owner, *parts]]})
    rows = {r.values["attr_object_id"].key: from_ea(r.values) for r in _objects(session, diagram)}
    assert set(rows) == {MESSAGE, owner, *parts}
    outer = rows[owner]
    for part in parts:
        left, top, right, bottom = rows[part]
        assert outer[0] <= left and outer[1] <= top and right <= outer[2] and bottom <= outer[3]
    assert _no_overlaps({k: v for k, v in rows.items() if k != owner})
    assert not [w for w in session.warnings if w.code == "moved-inside-owner"]


def test_layout_warns_page_overflow(nafv4_path, qea_copy):
    session = _open(qea_copy(nafv4_path))
    diagram = session.create_diagram("Model::p2", "D").guid
    names = [session.create_element("Model::p2", f"Wide element number {i}", type="Class").guid for i in range(12)]
    result = session.layout(diagram, {"pattern": "layers", "rows": [names]})
    overflow = [w for w in result.warnings if w.code == "page-overflow"]
    assert len(overflow) == 1 and "split" in overflow[0].message
    report = plan_layout(session, diagram, {"pattern": "layers", "rows": [names]})
    assert not report.fits and report.split and len(report.split) > 1


def test_layout_rejects_bad_spec(nafv4_path, qea_copy):
    session = _open(qea_copy(nafv4_path))
    with pytest.raises(InvalidOperationError):
        session.layout(L7, {"pattern": "spiral"})
    with pytest.raises(InvalidOperationError):
        session.layout(L7, {"pattern": "hub", "center": MESSAGE, "around": [DATA_MESSAGE]})
