"""Diagram operations: create, update and delete a diagram with its objects and links."""

from __future__ import annotations

import re
from collections.abc import Sequence

from eacore.embedded import duid, link_ends
from eacore.records import Record, Ref
from eaedit.defaults import (
    DIAGRAM_PROPERTIES,
    OBJECT_STYLES,
    apply_fields,
    link_geometry,
    link_style,
    new_record,
    new_row,
    timestamp,
)
from eaedit.diagrams.geometry import Rect, check_rect, from_ea, to_ea
from eaedit.diagrams.views import resolve_view
from eaedit.errors import InvalidOperationError
from eaedit.ops import operation
from eaedit.ops.common import primary_guid
from eaedit.ops.elements import cascade_delete
from eaedit.resolve import guid_of


def _diagram(session, identifier: str) -> Record:
    return session.working.resolve(session.find(identifier, kinds=("diagram",)))


def _unique_name(session, package: Ref, name: str, key=None) -> None:
    """Refuse ``name`` when another diagram of ``package`` has it: diagrams are found by ``package::name``."""
    for other in session.working.records("t_diagram"):
        if (
            other.key != key
            and other.values.get("attr_package_id") == package
            and other.values.get("attr_name") == name
        ):
            raise InvalidOperationError(f"diagram name {name!r} is taken in its package by {guid_of(other)}")


@operation("create_diagram")
def create_diagram(session, owner: str, name: str, type: str = "Class", guid: str | None = None) -> str:
    if not name:
        raise InvalidOperationError("a diagram needs a name")
    view = resolve_view(session.catalogues, type)
    ref = session.find(owner, kinds=("package", "element"))
    parent = None
    if ref.table == "t_object":
        # A diagram of an element sits in the element's package (ParentID names the element), as EA stores it.
        parent = ref
        ref = session.working.resolve(ref).values.get("attr_package_id")
        if not isinstance(ref, Ref):
            raise InvalidOperationError(f"element {owner!r} belongs to no existing package; its diagrams need one")
    _unique_name(session, ref, name)
    guid = primary_guid(session, guid)
    now = timestamp(session.now())
    values = {
        "attr_ea_guid": guid,
        "attr_name": name,
        "attr_diagram_type": view.diagram_type,
        "attr_package_id": ref,
        "attr_author": session.author,
        "attr_createddate": now,
        "attr_modifieddate": now,
    }
    if parent is not None:
        values["attr_parentid"] = parent
    record = new_record(session, "t_diagram", values, view.diagram_type)
    if view.mdg_name:
        # Hand-made view rows carry MDGDgm just before STBLDgm (the P2 row in nafv4.qea).
        styleex = record.values["attr_styleex"]
        record.values["attr_styleex"] = styleex.replace("STBLDgm=", f"MDGDgm={view.mdg_name};STBLDgm=", 1)
        if not view.verified:
            session.warn("unverified-default", f"view {type!r} has no EA-made sample; written from the MDG alone", guid)
    session.put(record)
    # Every hand-made diagram in nafv4.qea has this row (type 'diagram properties', supplier NULL).
    properties = {
        "attr_name": "CustomProperties",
        "attr_type": "diagram properties",
        "attr_description": DIAGRAM_PROPERTIES,
        "attr_client": guid,
    }
    session.put(new_record(session, "t_xref", properties, "CustomProperties"))
    return guid


@operation("update_diagram")
def update_diagram(session, diagram: str, **fields) -> str:
    record = _diagram(session, diagram)
    if fields.get("orientation", "P") not in ("P", "L"):
        raise InvalidOperationError(
            f"orientation must be 'P' (portrait) or 'L' (landscape), not {fields['orientation']!r}"
        )
    if "name" in fields:
        _unique_name(session, record.values.get("attr_package_id"), fields["name"], record.key)
    values = apply_fields("t_diagram", record.values, fields)
    values["attr_modifieddate"] = timestamp(session.now())
    session.put(Record("t_diagram", record.key, values, record.rid))
    return guid_of(record)


@operation("delete_diagram")
def delete_diagram(session, diagram: str) -> str:
    record = _diagram(session, diagram)
    this = Ref("t_diagram", record.key)
    placed: dict[str, set] = {}
    for row in session.working.records("t_diagramobjects"):
        element = shown_element(session, row)
        if element is not None and element.values.get("attr_object_type") == "Note":
            placed.setdefault(element.key, set()).add(row.values.get("attr_diagram_id"))
    # A Note placed only on this diagram has no other home; EA deletes it with the diagram's content.
    notes = [key for key, diagrams in placed.items() if diagrams == {this}]
    cascade_delete(session, notes, [record.key])
    return guid_of(record)


#: Default size of a new object, from the hand-made rows in nafv4.qea (Parts on p2, Notes on L7, Classes on L7).
_SIZES = {"Part": (70, 54), "Note": (115, 55)}
_SIZE = (90, 70)
_GAP = 30


def diagram_objects(session, diagram: Ref) -> list[Record]:
    return [r for r in session.working.records("t_diagramobjects") if r.values.get("attr_diagram_id") == diagram]


def shown_element(session, obj: Record) -> Record | None:
    """The element a diagram object shows; None for a dangling object (Object_ID unset or naming no element, which
    the loader keeps as the raw value). Diagram operations carry a dangling object through untouched."""
    ref = obj.values.get("attr_object_id")
    if not isinstance(ref, Ref) or ref.table != "t_object":
        return None
    return session.working.resolve(ref)


def _element(session, identifier: str) -> Record:
    return session.working.resolve(session.find(identifier, kinds=("element",)))


def _object(session, diagram: Ref, identifier: str) -> Record:
    """The diagram object named by a DUID, or the only object showing the element."""
    objects = diagram_objects(session, diagram)
    if re.fullmatch(r"[0-9A-Fa-f]{8}", identifier):
        for obj in objects:
            if duid(obj.values.get("attr_objectstyle")) == identifier.upper():
                return obj
    element = _element(session, identifier)
    shown = [o for o in objects if o.values.get("attr_object_id") == Ref("t_object", element.key)]
    name = element.values.get("attr_name")
    if not shown:
        raise InvalidOperationError(f"{name!r} is not on the diagram")
    if len(shown) > 1:
        duids = ", ".join(str(duid(o.values.get("attr_objectstyle"))) for o in shown)
        raise InvalidOperationError(f"{name!r} is on the diagram {len(shown)} times: name one by DUID ({duids})")
    return shown[0]


def _new_duid(session, taken: set[str | None]) -> str:
    while True:
        value = session.new_duid()
        if value not in taken:
            return value


def _style_kind(element: Record, diagram_type: str | None) -> str:
    kind = element.values.get("attr_object_type")
    if kind in ("Note", "InteractionFragment"):
        return kind
    if diagram_type == "Sequence":
        return "Lifeline"
    return kind if kind in OBJECT_STYLES else "*"


def _free_rect(session, diagram: Ref, kind: str | None) -> Rect:
    """The first free spot to the right of the diagram's objects, at the top of the topmost."""
    width, height = _SIZES.get(kind, _SIZE)
    rects = [from_ea(o.values) for o in diagram_objects(session, diagram)]
    left = max((r[2] for r in rects), default=0) + _GAP
    top = min((r[1] for r in rects), default=_GAP)
    return left, top, left + width, top + height


def _free_slot(session, diagram: Ref, outer: Rect) -> Rect | None:
    """A Part-sized spot inside ``outer`` clear of every object, left to right then wrapping; None if full."""
    width, height = _SIZES["Part"]
    taken = [from_ea(o.values) for o in diagram_objects(session, diagram)]
    top = outer[1] + 30  # below the owner's name compartment
    while top + height <= outer[3] - _GAP // 3:
        left = outer[0] + 20
        while left + width <= outer[2] - 20:
            spot = (left, top, left + width, top + height)
            clash = any(
                spot[0] < t[2] and t[0] < spot[2] and spot[1] < t[3] and t[1] < spot[3] for t in taken if t != outer
            )
            if not clash:
                return spot
            left += width + 10
        top += height + 10
    return None


def _inside(rect: Rect, outer: Rect) -> bool:
    return rect[0] >= outer[0] and rect[1] >= outer[1] and rect[2] <= outer[2] and rect[3] <= outer[3]


def _clamp(rect: Rect, outer: Rect) -> Rect:
    """``rect`` moved (not resized) into ``outer``; a rectangle wider than ``outer`` is pinned to its top left."""
    width, height = rect[2] - rect[0], rect[3] - rect[1]
    left = max(outer[0], min(rect[0], outer[2] - width))
    top = max(outer[1], min(rect[1], outer[3] - height))
    return left, top, left + width, top + height


def _owner_object(session, diagram: Ref, element: Record) -> Record | None:
    """The diagram object of a Part's owner, if the owner is on the diagram."""
    if element.values.get("attr_object_type") != "Part":
        return None
    parent = element.values.get("attr_parentid")
    if not isinstance(parent, Ref):
        return None
    for obj in diagram_objects(session, diagram):
        if obj.values.get("attr_object_id") == parent:
            return obj
    return None


def _keep_in_owner(session, diagram: Ref, element: Record, rect: Rect) -> Rect:
    """A Part stays inside its owner's rectangle when the owner is shown (Review Focus 1)."""
    owner = _owner_object(session, diagram, element)
    if owner is None:
        return rect
    outer = from_ea(owner.values)
    if _inside(rect, outer):
        return rect
    session.warn(
        "moved-inside-owner",
        f"Part {element.values.get('attr_name')!r} moved inside its owner's rectangle",
        guid_of(element),
    )
    return _clamp(rect, outer)


def _stack_owner(session, owner: Record, part_sequence: int) -> None:
    """Put the owner behind its Part (higher Sequence = further back, as on the hand-made p2 rows)."""
    if (owner.values.get("attr_sequence") or 0) > part_sequence:
        return
    session.put(Record("t_diagramobjects", owner.key, {**owner.values, "attr_sequence": part_sequence + 1}, owner.rid))


def _edge(source: Rect, target: Rect) -> int:
    """Side of ``source`` facing ``target``: 1 top, 2 right, 3 bottom, 4 left (L7 rows: EDGE follows the direction)."""
    dx = (target[0] + target[2]) - (source[0] + source[2])
    dy = (target[1] + target[3]) - (source[1] + source[3])
    if abs(dx) >= abs(dy):
        return 2 if dx >= 0 else 4
    return 3 if dy > 0 else 1


def _link_key(diagram: Ref, connector: Record) -> tuple[Ref, Ref]:
    return diagram, Ref("t_connector", connector.key)


def _link_row(session, diagram: Ref, connector: Record) -> Record | None:
    """The link row for ``connector`` on ``diagram``, written from the objects now showing both ends."""
    values = connector.values
    ends = []
    for column in ("attr_start_object_id", "attr_end_object_id"):
        shown = [o for o in diagram_objects(session, diagram) if o.values.get("attr_object_id") == values.get(column)]
        if not shown or not duid(shown[0].values.get("attr_objectstyle")):
            return None
        ends.append(shown[0])
    source, target = ends
    style = link_style(duid(source.values["attr_objectstyle"]), duid(target.values["attr_objectstyle"]))
    edge = _edge(from_ea(source.values), from_ea(target.values))
    return new_row(
        session,
        "t_diagramlinks",
        {
            "attr_diagramid": diagram,
            "attr_connectorid": Ref("t_connector", connector.key),
            "attr_geometry": link_geometry(edge),
            "attr_style": style,
        },
    )


def _show_links(session, diagram: Ref, element: Ref) -> None:
    """Write a link row for each connector of ``element`` whose ends are both shown and which has none."""
    for connector in list(session.working.records("t_connector")):
        values = connector.values
        if element not in (values.get("attr_start_object_id"), values.get("attr_end_object_id")):
            continue
        # A sequence message is shown through the sequence diagram's own columns, not a link row.
        if values.get("attr_connector_type") == "Sequence":
            continue
        if session.working.get("t_diagramlinks", _link_key(diagram, connector)) is not None:
            continue
        row = _link_row(session, diagram, connector)
        if row is not None:
            session.put(row)


@operation("place")
def place(session, diagram: str, element: str, rect: Sequence[int] | None = None) -> str:
    record = _diagram(session, diagram)
    this = Ref("t_diagram", record.key)
    target = _element(session, element)
    ref = Ref("t_object", target.key)
    objects = diagram_objects(session, this)
    kind = _style_kind(target, record.values.get("attr_diagram_type"))
    owner = _owner_object(session, this, target)
    slot = _free_slot(session, this, from_ea(owner.values)) if rect is None and owner is not None else None
    if slot is not None:
        wanted = slot
    elif rect is None:
        wanted = _free_rect(session, this, target.values.get("attr_object_type"))
    else:
        wanted = check_rect(rect)
    if any(o.values.get("attr_object_id") == ref for o in objects):
        session.warn(
            "already-on-diagram", f"{target.values.get('attr_name')!r} is already on the diagram", guid_of(target)
        )
    wanted = _keep_in_owner(session, this, target, wanted)
    # Lower Sequence is in front: a new object gets 1, one that contains others goes behind them all.
    sequence = 1
    if any(_inside(from_ea(o.values), wanted) for o in objects):
        sequence = max(o.values.get("attr_sequence") or 0 for o in objects) + 1
    new_duid = _new_duid(session, {duid(o.values.get("attr_objectstyle")) for o in objects})
    row = new_row(
        session,
        "t_diagramobjects",
        {
            "attr_diagram_id": this,
            "attr_object_id": ref,
            **to_ea(wanted),
            "attr_sequence": sequence,
            "attr_objectstyle": f"DUID={new_duid};{OBJECT_STYLES[kind]}",
        },
    )
    session.put(row)
    if owner is not None:
        _stack_owner(session, session.working.get("t_diagramobjects", owner.key), sequence)
    _show_links(session, this, ref)
    return new_duid


@operation("set_bounds")
def set_bounds(session, diagram: str, element: str, rect: Sequence[int]) -> str:
    this = Ref("t_diagram", _diagram(session, diagram).key)
    obj = _object(session, this, element)
    wanted = check_rect(rect)
    target = shown_element(session, obj)
    if target is not None:
        wanted = _keep_in_owner(session, this, target, wanted)
    # Link rows are left alone: EA routes them from the stored geometry, which a move does not rewrite.
    session.put(Record("t_diagramobjects", obj.key, {**obj.values, **to_ea(wanted)}, obj.rid))
    return duid(obj.values.get("attr_objectstyle")) or ""


@operation("set_stacking")
def set_stacking(session, diagram: str, element: str, sequence: int) -> str:
    """Set an object's ``Sequence``: lower is in front, as on the hand-made rows (an owner behind its Parts on p2)."""
    if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 1:
        raise InvalidOperationError(f"sequence must be an integer >= 1, not {sequence!r}")
    this = Ref("t_diagram", _diagram(session, diagram).key)
    obj = _object(session, this, element)
    session.put(Record("t_diagramobjects", obj.key, {**obj.values, "attr_sequence": sequence}, obj.rid))
    return duid(obj.values.get("attr_objectstyle")) or ""


@operation("remove_from_diagram")
def remove_from_diagram(session, diagram: str, element: str) -> str:
    this = Ref("t_diagram", _diagram(session, diagram).key)
    obj = _object(session, this, element)
    gone = duid(obj.values.get("attr_objectstyle"))
    note = shown_element(session, obj)
    if note is not None and note.values.get("attr_object_type") == "Note":
        ref = Ref("t_object", note.key)
        rows = session.working.records("t_diagramobjects")
        if not any(o.key != obj.key and o.values.get("attr_object_id") == ref for o in rows):
            # A Note shown nowhere else has no other home: it goes with its last object, as delete_diagram treats it.
            cascade_delete(session, [note.key])
            return gone or ""
    session.drop("t_diagramobjects", obj.key)
    shown = obj.values.get("attr_object_id")
    still = any(o.values.get("attr_object_id") == shown for o in diagram_objects(session, this))
    for link in list(session.working.records("t_diagramlinks")):
        if link.values.get("attr_diagramid") != this:
            continue
        if gone:
            lost = gone in link_ends(link.values.get("attr_style"))
        else:
            ref = link.values.get("attr_connectorid")
            connector = session.working.resolve(ref) if isinstance(ref, Ref) else None
            if connector is None:
                continue  # a dangling link row (its connector is gone) is carried through untouched
            ends = (connector.values.get("attr_start_object_id"), connector.values.get("attr_end_object_id"))
            lost = shown in ends and not still
        if lost:
            session.drop("t_diagramlinks", link.key)
    return gone or ""


def _connector_row(session, diagram: Ref, connector: str) -> tuple[Record, Record | None]:
    record = session.working.resolve(session.find(connector, kinds=("connector",)))
    return record, session.working.get("t_diagramlinks", _link_key(diagram, record))


@operation("hide_connector")
def hide_connector(session, diagram: str, connector: str) -> str:
    this = Ref("t_diagram", _diagram(session, diagram).key)
    record, link = _connector_row(session, this, connector)
    if link is None:
        raise InvalidOperationError("the connector is not shown on the diagram")
    session.put(Record("t_diagramlinks", link.key, {**link.values, "attr_hidden": 1}, link.rid))
    return guid_of(record)


@operation("show_connector")
def show_connector(session, diagram: str, connector: str) -> str:
    this = Ref("t_diagram", _diagram(session, diagram).key)
    record, link = _connector_row(session, this, connector)
    if link is not None:
        session.put(Record("t_diagramlinks", link.key, {**link.values, "attr_hidden": 0}, link.rid))
        return guid_of(record)
    if record.values.get("attr_connector_type") == "Sequence":
        raise InvalidOperationError("a sequence message is not shown through a link row")
    row = _link_row(session, this, record)
    if row is None:
        raise InvalidOperationError("both ends of the connector must be on the diagram")
    session.put(row)
    return guid_of(record)


def _message(session, diagram: Ref, connector: str) -> Record:
    record = session.working.resolve(session.find(connector, kinds=("connector",)))
    if record.values.get("attr_connector_type") != "Sequence":
        raise InvalidOperationError(f"{connector!r} is not a Sequence message")
    return record


def _messages(session, diagram: Ref) -> list[Record]:
    return [
        r
        for r in session.working.records("t_connector")
        if r.values.get("attr_connector_type") == "Sequence" and r.values.get("attr_diagramid") == diagram
    ]


def _with_offset(pdata5: str | None, offset: int) -> str:
    """``PDATA5`` with ``SY=`` set; every other key is kept (hand-made: ``SX=0;SY=-39;EX=0;EY=0;$LLB=;...``)."""
    if pdata5 and re.search(r"(?<![A-Za-z$])SY=-?\d+", pdata5):
        return re.sub(r"(?<![A-Za-z$])SY=-?\d+", f"SY={offset}", pdata5, count=1)
    if pdata5:
        return f"SY={offset};{pdata5}"
    return f"SX=0;SY={offset};EX=0;EY=0;$LLB=;LLT=;LMT=;LMB=;LRT=;LRB=;IRHS=;ILHS=;"


@operation("show_message")
def show_message(session, diagram: str, connector: str, order: int | None = None, offset: int | None = None) -> str:
    record = _diagram(session, diagram)
    this = Ref("t_diagram", record.key)
    if record.values.get("attr_diagram_type") != "Sequence":
        raise InvalidOperationError("messages are shown on Sequence diagrams only")
    message = _message(session, this, connector)
    shown = {o.values.get("attr_object_id") for o in diagram_objects(session, this)}
    for column in ("attr_start_object_id", "attr_end_object_id"):
        if message.values.get(column) not in shown:
            raise InvalidOperationError("both ends of the message must be lifelines on the diagram")
    home = message.values.get("attr_diagramid")
    if isinstance(home, Ref) and home != this:
        current = session.working.resolve(home)
        name = guid_of(current) if current is not None else home.key
        raise InvalidOperationError(f"the message is shown on diagram {name}: a message is shown on one diagram only")
    others = [m for m in _messages(session, this) if m.key != message.key]
    current_number = message.values.get("attr_seqno") if home == this else None
    if order is not None and order != current_number:
        # EA keeps a diagram's message numbers 1..n: the message leaves its place, then the number it takes and
        # those after it move down one.
        numbers = {m.key: m.values.get("attr_seqno") or 0 for m in others}
        if current_number:
            numbers = {k: n - 1 if n > current_number else n for k, n in numbers.items()}
        if order in numbers.values():
            numbers = {k: n + 1 if n >= order else n for k, n in numbers.items()}
        for other in others:
            if numbers[other.key] != (other.values.get("attr_seqno") or 0):
                values = {**other.values, "attr_seqno": numbers[other.key]}
                session.put(Record("t_connector", other.key, values, other.rid))
    values = dict(message.values)
    values["attr_diagramid"] = this
    if order is not None:
        values["attr_seqno"] = order
    elif not current_number:
        # Shown again without an order, it keeps its number; newly shown, it comes last.
        values["attr_seqno"] = max((m.values.get("attr_seqno") or 0 for m in others), default=0) + 1
    pdata5 = values.get("attr_pdata5")
    if offset is None and not (pdata5 and "SY=" in pdata5):
        # No hand-made rule for a message EA has not laid out: step down from the previous message.
        offset = -39 - 38 * len(others)
        session.warn("unverified-default", "message offset chosen by spacing, not read from EA", guid_of(message))
    if offset is not None:
        values["attr_pdata5"] = _with_offset(pdata5, offset)
    session.put(Record("t_connector", message.key, values, message.rid))
    return guid_of(message)


@operation("set_message_order")
def set_message_order(session, diagram: str, connectors: list[str]) -> str:
    record = _diagram(session, diagram)
    this = Ref("t_diagram", record.key)
    messages = [_message(session, this, c) for c in connectors]
    if len({m.key for m in messages}) != len(messages):
        raise InvalidOperationError("a message is listed twice")
    for message in messages:
        if message.values.get("attr_diagramid") != this:
            raise InvalidOperationError("every message must be shown on the diagram: use show_message")
    # The others on the diagram follow in their stored order, so the numbers stay 1..n with none taken twice.
    listed = {m.key for m in messages}
    rest = sorted(
        (m for m in _messages(session, this) if m.key not in listed),
        key=lambda m: (m.values.get("attr_seqno") or 0, str(m.key)),
    )
    for number, message in enumerate([*messages, *rest], 1):
        if message.values.get("attr_seqno") != number:
            session.put(Record("t_connector", message.key, {**message.values, "attr_seqno": number}, message.rid))
    return guid_of(record)
