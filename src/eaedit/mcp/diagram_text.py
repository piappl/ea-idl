"""A diagram as compact paged text for the agent: objects with rectangles and stacking, links, messages."""

from __future__ import annotations

from eacore.embedded import duid
from eacore.records import Record, Ref
from eaedit.diagrams.geometry import from_ea
from eaedit.diagrams.svg import diagram_type, message_offset, object_kind
from eaedit.mcp.explore import _braced, _qname, _replies, _resolve, _stereos, page_lines
from eaedit.ops.diagrams import diagram_objects, shown_element

NOTE_TEXT = 60


def _stereo(session, record: Record) -> str:
    names = ", ".join(_stereos(session, record))
    return f" «{names}»" if names else ""


def _object_line(session, row: Record) -> str:
    element = shown_element(session, row)
    tail = f"duid={duid(row.values.get('attr_objectstyle')) or '-'}"
    rect = ",".join(str(v) for v in from_ea(row.values))
    tail += f" rect={rect} z={row.values.get('attr_sequence') or 0}"
    kind = "readonly" if element is None else object_kind(element)
    if kind == "readonly":
        return f"readonly {tail}"
    if kind == "note":
        text = (element.values.get("attr_note") or "").replace("\r", " ").replace("\n", " ")
        return f'note {_braced(element)} {tail} "{text[:NOTE_TEXT]}"'
    return f"obj {_qname(session, element)}{_stereo(session, element)} {_braced(element)} {tail}"


def _ends(session, connector: Record) -> str:
    names = []
    for column in ("attr_start_object_id", "attr_end_object_id"):
        ref = connector.values.get(column)
        end = session.working.resolve(ref) if isinstance(ref, Ref) else None
        # A note has no name: it is told by its GUID.
        named = end is not None and (end.values.get("attr_name") or "")
        names.append(_qname(session, end) if named else _braced(end) if end is not None else "?")
    return " -> ".join(names)


def _link_lines(session, diagram: Ref) -> list[str]:
    working = session.working
    rows = []
    for link in working.records("t_diagramlinks"):
        if link.values.get("attr_diagramid") != diagram:
            continue
        connector = working.resolve(link.values.get("attr_connectorid"))
        if connector is None:
            continue
        kind = connector.values.get("attr_connector_type") or "?"
        hidden = " hidden" if link.values.get("attr_hidden") else ""
        text = f"link {kind}{_stereo(session, connector)} {_ends(session, connector)} {_braced(connector)}{hidden}"
        rows.append((text, _braced(connector)))
    return [text for text, _ in sorted(rows)]


def _message_lines(session, diagram: Ref) -> list[str]:
    messages = [
        m
        for m in session.working.records("t_connector")
        if m.values.get("attr_connector_type") == "Sequence" and m.values.get("attr_diagramid") == diagram
    ]
    messages.sort(key=lambda m: (m.values.get("attr_seqno") or 0, str(m.key)))
    return [
        f"msg {m.values.get('attr_seqno') or 0} {_ends(session, m)}{_stereo(session, m)} {_braced(m)}"
        f" offset={message_offset(m.values.get('attr_pdata5'))}"
        for m in messages
    ]


@_replies
def diagram_text(session, diagram: str, page: int = 1, page_size: int = 40) -> str:
    """One diagram: header, objects (back to front), shown connectors, then sequence messages."""
    record = _resolve(session, diagram, ("diagram",))
    this = Ref("t_diagram", record.key)
    values = record.values
    header = f"diagram {_qname(session, record)} {_braced(record)}  type={diagram_type(record)}"
    lines = [header + f"  page={values.get('attr_cx') or 0}x{values.get('attr_cy') or 0}"]
    rows = sorted(diagram_objects(session, this), key=lambda r: (r.values.get("attr_sequence") or 0, str(r.key)))
    lines += [_object_line(session, row) for row in rows]
    lines += _link_lines(session, this)
    lines += _message_lines(session, this)
    return page_lines(lines, page, page_size)
