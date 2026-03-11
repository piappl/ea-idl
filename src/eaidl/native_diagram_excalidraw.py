"""
Native EA Diagram Excalidraw Renderer.

Converts a :class:`~eaidl.native_diagram_model.NativeDiagram` into an
Excalidraw JSON document (``*.excalidraw``) that can be opened in
https://excalidraw.com or embedded in Obsidian / VS Code via the Excalidraw
plugin.

Excalidraw coordinate system
-----------------------------
* Origin (0, 0) is the top-left of the canvas.
* X increases to the right, Y increases downward.
* Arrow ``points`` are **relative** to the element's ``(x, y)`` anchor.

This is identical to standard SVG screen space.  EA canvas coordinates are
converted using the same transform used by the SVG renderer::

    ex_x = node.rect_left
    ex_y = -node.rect_top          (EA stores Y as zero-or-negative)
    ex_w = node.rect_right  - node.rect_left
    ex_h = node.rect_top    - node.rect_bottom

Visual conventions
------------------
* ``roughness: 0`` — clean / polished look (no hand-drawn wobble).
* ``fontFamily: 2`` — Helvetica / normal sans-serif.
* Class nodes have a filled header band + body compartment backed by a
  faint body fill, with attributes listed in the body.
* Generalization uses a hollow-triangle arrowhead; Association uses an
  open-chevron arrowhead; NoteLink uses a dashed line without an arrowhead.
* Note text is stripped of EA HTML tags (Excalidraw is plain-text only).
"""

from __future__ import annotations

import json
import math
import re
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional, Sequence, Tuple

from eaidl.native_diagram_model import (
    NativeDiagram,
    NativeDiagramConnector,
    NativeDiagramNode,
    NativeSequenceMessage,
)

# ---------------------------------------------------------------------------
# Layout constants (mirrors native_diagram_svg constants for consistency)
# ---------------------------------------------------------------------------
PADDING_X = 8
PADDING_Y = 5
HEADER_H = 22
ATTR_ROW_H = 16
NOTE_FOLD = 10          # not rendered visually in Excalidraw but kept logically
SVG_PAD = 30
ACTIVATION_BAR_W = 12
LIFELINE_HEAD_H = 55
FRAGMENT_TAB_H = 18

# Excalidraw font families: 1=hand, 2=normal, 3=mono
_FONT_FAMILY = 2
_FONT_SIZE_NORMAL = 14
_FONT_SIZE_SMALL = 10
_FONT_SIZE_ATTR = 11


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _TextStripper(HTMLParser):
    """Strip EA HTML formatting tags to produce plain text for Excalidraw."""

    def __init__(self) -> None:
        super().__init__()
        self._parts: List[str] = []

    def handle_data(self, data: str) -> None:
        self._parts.append(data)

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag.lower() == "br":
            self._parts.append("\n")

    def result(self) -> str:
        return "".join(self._parts).strip()


def _strip_html(html: Optional[str]) -> str:
    """Return plain text, converting ``<br>`` to newlines and removing all tags."""
    if not html:
        return ""
    html = html.replace("\r\n", "\n").replace("\r", "\n")
    p = _TextStripper()
    try:
        p.feed(html)
        text = p.result()
    except Exception:
        text = re.sub(r"<[^>]+>", "", html).strip()
    return text or ""


def _ea_to_ex(node: NativeDiagramNode) -> Tuple[float, float, float, float]:
    """Return ``(x, y, width, height)`` in Excalidraw/screen coordinates."""
    x = float(node.rect_left)
    y = float(-node.rect_top)
    w = float(node.rect_right - node.rect_left)
    h = float(node.rect_top - node.rect_bottom)
    return x, y, w, h


def _node_center(node: NativeDiagramNode) -> Tuple[float, float]:
    x, y, w, h = _ea_to_ex(node)
    return x + w / 2, y + h / 2


def _argb_to_hex(argb: int, fallback: str) -> str:
    if argb < 0:
        return fallback
    b = argb & 0xFF
    g = (argb >> 8) & 0xFF
    r = (argb >> 16) & 0xFF
    return f"#{r:02x}{g:02x}{b:02x}"


def _clip_to_rect(
    cx: float, cy: float, w: float, h: float, dx: float, dy: float
) -> Tuple[float, float]:
    if dx == 0 and dy == 0:
        return cx, cy
    hw, hh = w / 2, h / 2
    tx = (hw / abs(dx)) if dx != 0 else math.inf
    ty = (hh / abs(dy)) if dy != 0 else math.inf
    t = min(tx, ty)
    return cx + dx * t, cy + dy * t


def _edge_points(
    src: NativeDiagramNode,
    tgt: NativeDiagramNode,
    sx: Optional[int] = None,
    sy: Optional[int] = None,
    ex: Optional[int] = None,
    ey: Optional[int] = None,
) -> Tuple[Tuple[float, float], Tuple[float, float]]:
    scx, scy = _node_center(src)
    tcx, tcy = _node_center(tgt)
    _, _, sw, sh = _ea_to_ex(src)
    _, _, tw, th = _ea_to_ex(tgt)

    if sx is not None and (sx != 0 or sy != 0):
        p1: Tuple[float, float] = (scx + sx, scy - (sy or 0))
    else:
        dx, dy = tcx - scx, tcy - scy
        p1 = _clip_to_rect(scx, scy, sw, sh, dx, dy)

    if ex is not None and (ex != 0 or ey != 0):
        p2: Tuple[float, float] = (tcx + ex, tcy - (ey or 0))
    else:
        dx2, dy2 = scx - tcx, scy - tcy
        p2 = _clip_to_rect(tcx, tcy, tw, th, dx2, dy2)

    return p1, p2


# ---------------------------------------------------------------------------
# Element builders — each returns a list of Excalidraw element dicts
# ---------------------------------------------------------------------------

_id_counter = 0


def _next_id(prefix: str = "el") -> str:
    global _id_counter
    _id_counter += 1
    return f"{prefix}-{_id_counter}"


def _base_shape(
    eid: str,
    x: float,
    y: float,
    w: float,
    h: float,
    stroke: str,
    fill: str,
    stroke_style: str = "solid",
    stroke_width: int = 1,
    roughness: int = 0,
    group_ids: Optional[List[str]] = None,
    round_: bool = False,
) -> Dict[str, Any]:
    return {
        "type": "rectangle",
        "id": eid,
        "x": x,
        "y": y,
        "width": w,
        "height": h,
        "angle": 0,
        "strokeColor": stroke,
        "backgroundColor": fill,
        "fillStyle": "solid",
        "strokeWidth": stroke_width,
        "strokeStyle": stroke_style,
        "roughness": roughness,
        "opacity": 100,
        "groupIds": group_ids or [],
        "frameId": None,
        "roundness": {"type": 3} if round_ else None,
        "seed": hash(eid) & 0x7FFFFFFF,
        "version": 1,
        "versionNonce": (hash(eid) >> 1) & 0x7FFFFFFF,
        "isDeleted": False,
        "boundElements": [],
        "updated": 1,
        "link": None,
        "locked": False,
    }


def _base_text(
    eid: str,
    x: float,
    y: float,
    w: float,
    h: float,
    text: str,
    font_size: int = _FONT_SIZE_NORMAL,
    align: str = "center",
    bold: bool = False,
    italic: bool = False,
    color: str = "#1e293b",
    group_ids: Optional[List[str]] = None,
    container_id: Optional[str] = None,
    vertical_align: str = "middle",
) -> Dict[str, Any]:
    style = ""
    if bold and italic:
        style = "bold italic"
    elif bold:
        style = "bold"
    elif italic:
        style = "italic"

    return {
        "type": "text",
        "id": eid,
        "x": x,
        "y": y,
        "width": w,
        "height": h,
        "angle": 0,
        "strokeColor": color,
        "backgroundColor": "transparent",
        "fillStyle": "solid",
        "strokeWidth": 1,
        "strokeStyle": "solid",
        "roughness": 0,
        "opacity": 100,
        "groupIds": group_ids or [],
        "frameId": None,
        "roundness": None,
        "seed": hash(eid) & 0x7FFFFFFF,
        "version": 1,
        "versionNonce": (hash(eid) >> 1) & 0x7FFFFFFF,
        "isDeleted": False,
        "boundElements": [],
        "updated": 1,
        "link": None,
        "locked": False,
        "text": text,
        "fontSize": font_size,
        "fontFamily": _FONT_FAMILY,
        "textAlign": align,
        "verticalAlign": vertical_align,
        "containerId": container_id,
        "originalText": text,
        "autoResize": True,
        "lineHeight": 1.25,
        "fontStyle": style,
    }


def _base_line(
    eid: str,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    stroke: str,
    stroke_style: str = "solid",
    stroke_width: int = 1,
    start_arrowhead: Optional[str] = None,
    end_arrowhead: Optional[str] = None,
    group_ids: Optional[List[str]] = None,
    waypoints: Optional[List[Tuple[float, float]]] = None,
) -> Dict[str, Any]:
    """Return an arrow/line element.  Points are relative to (x1, y1)."""
    # Relative points starting at [0,0]
    pts: List[List[float]] = [[0.0, 0.0]]
    if waypoints:
        for wx, wy in waypoints:
            pts.append([wx - x1, wy - y1])
    pts.append([x2 - x1, y2 - y1])

    w = abs(x2 - x1)
    h = abs(y2 - y1)

    el_type = "arrow" if (start_arrowhead or end_arrowhead) else "line"
    return {
        "type": el_type,
        "id": eid,
        "x": x1,
        "y": y1,
        "width": w,
        "height": h,
        "angle": 0,
        "strokeColor": stroke,
        "backgroundColor": "transparent",
        "fillStyle": "solid",
        "strokeWidth": stroke_width,
        "strokeStyle": stroke_style,
        "roughness": 0,
        "opacity": 100,
        "groupIds": group_ids or [],
        "frameId": None,
        "roundness": None,
        "seed": hash(eid) & 0x7FFFFFFF,
        "version": 1,
        "versionNonce": (hash(eid) >> 1) & 0x7FFFFFFF,
        "isDeleted": False,
        "boundElements": [],
        "updated": 1,
        "link": None,
        "locked": False,
        "points": pts,
        "lastCommittedPoint": None,
        "startBinding": None,
        "endBinding": None,
        "startArrowhead": start_arrowhead,
        "endArrowhead": end_arrowhead,
    }


# ---------------------------------------------------------------------------
# Node renderers
# ---------------------------------------------------------------------------

def _class_node_elements(node: NativeDiagramNode, style) -> List[Dict[str, Any]]:
    """Return Excalidraw elements for a Class or Part node."""
    x, y, w, h = _ea_to_ex(node)

    bg = _argb_to_hex(node.style.background_color, style.node_bg_color)
    if node.object_type == "Part" and node.style.background_color < 0:
        bg = style.part_bg_color
    border = _argb_to_hex(node.style.line_color, style.node_border_color)
    lw = node.style.line_width if node.style.line_width > 0 else style.node_border_width
    group_id = f"node-{node.object_id}"

    body_h = max(h - HEADER_H, ATTR_ROW_H * max(1, len(node.attributes)) + 2 * PADDING_Y)

    elements: List[Dict[str, Any]] = []

    # Header rectangle
    hdr_id = _next_id("hdr")
    elements.append(_base_shape(
        hdr_id, x, y, w, HEADER_H,
        stroke=border, fill=style.node_header_color,
        stroke_width=lw, group_ids=[group_id],
    ))

    # Body rectangle
    body_id = _next_id("body")
    elements.append(_base_shape(
        body_id, x, y + HEADER_H, w, body_h,
        stroke=border, fill=bg,
        stroke_width=lw, group_ids=[group_id],
    ))

    # Stereotype text
    name_y = y + 2
    if node.stereotype:
        st_text = f"«{node.stereotype}»"
        st_h = _FONT_SIZE_SMALL * 1.4
        elements.append(_base_text(
            _next_id("st"), x, y + 1, w, st_h,
            text=st_text,
            font_size=_FONT_SIZE_SMALL,
            align="center",
            italic=True,
            color=style.node_header_text_color,
            group_ids=[group_id],
        ))
        name_y = y + st_h + 1

    # Name text
    name_text = f"«abstract» {node.name}" if node.is_abstract else node.name
    name_h = HEADER_H - (name_y - y) - 1
    elements.append(_base_text(
        _next_id("name"), x, name_y, w, max(name_h, _FONT_SIZE_NORMAL),
        text=name_text,
        font_size=_FONT_SIZE_NORMAL,
        align="center",
        bold=True,
        color=style.node_header_text_color,
        group_ids=[group_id],
        vertical_align="top",
    ))

    # Attribute rows — clipped logically by limiting text width to node width
    body_y = y + HEADER_H
    for i, attr in enumerate(node.attributes):
        ay = body_y + PADDING_Y + i * ATTR_ROW_H
        lb, ub = attr.lower_bound or "", attr.upper_bound or ""
        card = f" [{lb}..{ub}]" if (lb or ub) else ""
        attr_text = f"+ {attr.name} : {attr.type}{card}"
        elements.append(_base_text(
            _next_id("attr"), x + PADDING_X, ay, w - PADDING_X, _ATTR_ROW_H,
            text=attr_text,
            font_size=_FONT_SIZE_ATTR,
            align="left",
            color=style.node_border_color,
            group_ids=[group_id],
            vertical_align="top",
        ))

    return elements


# Alias so the constant resolves at call time
_ATTR_ROW_H = ATTR_ROW_H


def _note_node_elements(node: NativeDiagramNode, style) -> List[Dict[str, Any]]:
    """Return Excalidraw elements for a Note node (plain text in a box)."""
    x, y, w, h = _ea_to_ex(node)
    group_id = f"node-{node.object_id}"

    elements: List[Dict[str, Any]] = []

    box_id = _next_id("note")
    elements.append(_base_shape(
        box_id, x, y, w, h,
        stroke=style.note_border_color, fill=style.note_bg_color,
        stroke_width=1, group_ids=[group_id],
    ))

    raw = node.note_text or node.name or ""
    plain = _strip_html(raw)
    if plain:
        elements.append(_base_text(
            _next_id("note-txt"), x + NOTE_FOLD // 2, y + 4,
            w - NOTE_FOLD, h - 8,
            text=plain,
            font_size=_FONT_SIZE_ATTR,
            align="left",
            color=style.note_text_color,
            group_ids=[group_id],
            vertical_align="top",
        ))

    return elements


def _lifeline_elements(node: NativeDiagramNode, style) -> List[Dict[str, Any]]:
    """Return Excalidraw elements for a sequence-diagram lifeline."""
    x, y, w, h = _ea_to_ex(node)
    cx = x + w / 2
    head_h = min(LIFELINE_HEAD_H, h)

    bg = _argb_to_hex(node.style.background_color, style.node_header_color)
    border = _argb_to_hex(node.style.line_color, style.node_border_color)
    group_id = f"lifeline-{node.object_id}"

    elements: List[Dict[str, Any]] = []

    # Head box
    elements.append(_base_shape(
        _next_id("ll-hd"), x, y, w, head_h,
        stroke=border, fill=bg,
        group_ids=[group_id],
    ))

    # Name
    elements.append(_base_text(
        _next_id("ll-nm"), x, y + 2, w, head_h - 4,
        text=node.name,
        font_size=_FONT_SIZE_NORMAL,
        align="center",
        bold=True,
        color=style.node_header_text_color,
        group_ids=[group_id],
    ))

    # Dashed lifeline
    line_top = y + head_h
    line_bot = y + h
    elements.append(_base_line(
        _next_id("ll-ln"), cx, line_top, cx, line_bot,
        stroke=border,
        stroke_style="dashed",
        group_ids=[group_id],
    ))

    return elements


def _fragment_elements(node: NativeDiagramNode, style) -> List[Dict[str, Any]]:
    """Return Excalidraw elements for an interaction fragment (alt/opt/loop)."""
    x, y, w, h = _ea_to_ex(node)
    border = _argb_to_hex(node.style.line_color, style.node_border_color)
    group_id = f"frag-{node.object_id}"

    elements: List[Dict[str, Any]] = []

    # Dashed outer box
    outer_id = _next_id("frag-box")
    outer = _base_shape(
        outer_id, x, y, w, h,
        stroke=border, fill="transparent",
        stroke_style="dashed",
        group_ids=[group_id],
    )
    elements.append(outer)

    # Keyword tab (solid filled rectangle at top-left)
    tab_w = min(90.0, w * 0.4)
    tab_id = _next_id("frag-tab")
    elements.append(_base_shape(
        tab_id, x, y, tab_w, FRAGMENT_TAB_H,
        stroke=border, fill=style.node_header_color,
        group_ids=[group_id],
    ))

    keyword = node.stereotype or "alt"
    elements.append(_base_text(
        _next_id("frag-kw"), x + 4, y + 1, tab_w - 8, FRAGMENT_TAB_H - 2,
        text=keyword,
        font_size=_FONT_SIZE_SMALL,
        align="left",
        color=style.node_header_text_color,
        group_ids=[group_id],
    ))

    if node.name:
        elements.append(_base_text(
            _next_id("frag-nm"), x + tab_w + 6, y + 1, w - tab_w - 6, FRAGMENT_TAB_H - 2,
            text=node.name,
            font_size=_FONT_SIZE_SMALL,
            align="left",
            color=style.node_border_color,
            group_ids=[group_id],
        ))

    return elements


def _connector_elements(
    conn: NativeDiagramConnector,
    node_map: Dict[int, NativeDiagramNode],
    style,
) -> List[Dict[str, Any]]:
    """Return Excalidraw elements for a connector."""
    src = node_map.get(conn.source_object_id)
    tgt = node_map.get(conn.target_object_id)
    if src is None or tgt is None:
        return []

    geo = conn.geometry
    p1, p2 = _edge_points(src, tgt, geo.source_x, geo.source_y, geo.end_x, geo.end_y)
    wpts: List[Tuple[float, float]] = [
        (float(wp[0]), float(-wp[1])) for wp in geo.waypoints
    ]

    ctype = conn.connector_type or "Association"
    is_note_link = ctype == "NoteLink"
    is_gen = ctype == "Generalization"
    is_agg = ctype in ("Aggregation", "Composition")

    stroke = _argb_to_hex(conn.style.color, "") or (
        style.connector_note_color if is_note_link else style.connector_color
    )
    lw = max(conn.style.line_width, 1)

    stroke_style = "dashed" if is_note_link else "solid"
    start_arrow: Optional[str] = None
    end_arrow: Optional[str] = None

    if is_gen:
        end_arrow = "triangle"
    elif is_agg:
        start_arrow = "dot"   # approximation for diamond
        end_arrow = "arrow"
    elif not is_note_link:
        end_arrow = "arrow"

    elements: List[Dict[str, Any]] = []
    line_el = _base_line(
        _next_id(f"conn-{conn.connector_id}"),
        p1[0], p1[1], p2[0], p2[1],
        stroke=stroke,
        stroke_style=stroke_style,
        stroke_width=lw,
        start_arrowhead=start_arrow,
        end_arrowhead=end_arrow,
        waypoints=wpts,
    )
    elements.append(line_el)

    # Role label near target end
    if conn.target_role:
        lx = p2[0] * 0.8 + p1[0] * 0.2
        ly = p2[1] * 0.8 + p1[1] * 0.2 - 10
        elements.append(_base_text(
            _next_id("role"), lx - 20, ly, 60, _FONT_SIZE_SMALL * 1.4,
            text=conn.target_role,
            font_size=_FONT_SIZE_SMALL,
            align="center",
            color=style.node_border_color,
        ))

    return elements


def _sequence_message_elements(
    msg: NativeSequenceMessage,
    style,
) -> List[Dict[str, Any]]:
    """Return Excalidraw elements for one sequence message."""
    x1, y1 = float(msg.start_x), float(-msg.start_y)
    x2, y2 = float(msg.end_x), float(-msg.end_y)

    is_return = x2 < x1
    is_self = msg.source_object_id == msg.target_object_id

    stroke = style.connector_color
    stroke_style = "dashed" if is_return else "solid"

    elements: List[Dict[str, Any]] = []

    group_id = f"msg-{msg.connector_id}"

    if is_self:
        # Two-segment loop: right bump
        loop_x = x1 + 40
        # Segment 1: x1,y1 → loop_x,y1
        elements.append(_base_line(
            _next_id("msg-s1"), x1, y1, loop_x, y1,
            stroke=stroke, group_ids=[group_id],
        ))
        # Segment 2: loop_x,y1 → loop_x,y1+30
        elements.append(_base_line(
            _next_id("msg-s2"), loop_x, y1, loop_x, y1 + 30,
            stroke=stroke, group_ids=[group_id],
        ))
        # Segment 3 with arrowhead: loop_x,y1+30 → x2,y2+30
        elements.append(_base_line(
            _next_id("msg-s3"), loop_x, y1 + 30, x2, y2 + 30,
            stroke=stroke, end_arrowhead="arrow", group_ids=[group_id],
        ))
    else:
        elements.append(_base_line(
            _next_id(f"msg-{msg.connector_id}"),
            x1, y1, x2, y2,
            stroke=stroke,
            stroke_style=stroke_style,
            end_arrowhead="arrow",
            group_ids=[group_id],
        ))

    # Label text
    mid_x = (x1 + x2) / 2
    label_y = y1 - _FONT_SIZE_NORMAL - 2

    if msg.stereotype:
        elements.append(_base_text(
            _next_id("msg-st"),
            mid_x - 60, label_y - _FONT_SIZE_SMALL - 2, 120, _FONT_SIZE_SMALL * 1.4,
            text=f"«{msg.stereotype}»",
            font_size=_FONT_SIZE_SMALL,
            align="center",
            italic=True,
            color=style.connector_color,
            group_ids=[group_id],
        ))
        label_y -= _FONT_SIZE_SMALL + 2

    label = msg.name or ""
    if msg.param_values:
        label += f"({msg.param_values})"
    if label:
        elements.append(_base_text(
            _next_id("msg-lbl"),
            mid_x - 80, label_y, 160, _FONT_SIZE_NORMAL * 1.4,
            text=label,
            font_size=_FONT_SIZE_NORMAL,
            align="center",
            color=style.node_border_color,
            group_ids=[group_id],
        ))

    if msg.return_value:
        elements.append(_base_text(
            _next_id("msg-ret"),
            mid_x - 80, y1 + 2, 160, _FONT_SIZE_NORMAL * 1.4,
            text=msg.return_value,
            font_size=_FONT_SIZE_NORMAL,
            align="center",
            italic=True,
            color=style.node_border_color,
            group_ids=[group_id],
        ))

    return elements


def _activation_bar_elements(
    messages: List[NativeSequenceMessage],
    node_map: Dict[int, NativeDiagramNode],
    style,
) -> List[Dict[str, Any]]:
    """Return Excalidraw rect elements for activation bars (execution specs)."""
    # Reuse the same span-computation logic as the SVG renderer
    events: List[tuple] = []
    for msg in messages:
        y_svg = float(-msg.start_y)
        events.append((y_svg, msg.source_object_id, "depart"))
        events.append((y_svg, msg.target_object_id, "arrive"))
    events.sort()

    spans: Dict[int, List[Tuple[float, float]]] = {}
    pending: Dict[int, float] = {}
    for y_svg, obj_id, role in events:
        if role == "arrive" and obj_id not in pending:
            pending[obj_id] = y_svg
        elif role == "depart" and obj_id in pending:
            spans.setdefault(obj_id, []).append((pending.pop(obj_id), y_svg))
    for obj_id, top in pending.items():
        spans.setdefault(obj_id, []).append((top, top + 20))

    elements: List[Dict[str, Any]] = []
    hw = ACTIVATION_BAR_W / 2
    for obj_id, obj_spans in spans.items():
        node = node_map.get(obj_id)
        if node is None:
            continue
        _, _, nw, _ = _ea_to_ex(node)
        cx = float(node.rect_left) + nw / 2
        border = _argb_to_hex(node.style.line_color, style.node_border_color)
        for top, bot in obj_spans:
            h = max(bot - top, 4)
            elements.append(_base_shape(
                _next_id("act"),
                cx - hw, top, ACTIVATION_BAR_W, h,
                stroke=border, fill=style.node_bg_color,
            ))

    return elements


def _note_message_ref_elements(
    notes: List[NativeDiagramNode],
    messages: List[NativeSequenceMessage],
    style,
) -> List[Dict[str, Any]]:
    """Dashed lines from notes-to-message refs (PDATA4 idref1)."""
    msg_by_id = {m.connector_id: m for m in messages}
    elements: List[Dict[str, Any]] = []
    for note in notes:
        if note.note_connector_ref is None:
            continue
        msg = msg_by_id.get(note.note_connector_ref)
        if msg is None:
            continue
        nx = float(note.rect_left + note.rect_right) / 2
        ny = (-float(note.rect_top) + -float(note.rect_bottom)) / 2
        mx = (float(msg.start_x) + float(msg.end_x)) / 2
        my = (-float(msg.start_y) + -float(msg.end_y)) / 2
        elements.append(_base_line(
            _next_id("nmref"),
            nx, ny, mx, my,
            stroke=style.connector_note_color,
            stroke_style="dashed",
        ))
    return elements


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def render_excalidraw(diagram: NativeDiagram, style=None) -> str:
    """
    Render *diagram* as an Excalidraw JSON string.

    :param diagram: A :class:`~eaidl.native_diagram_model.NativeDiagram`.
    :param style: A :class:`~eaidl.config.NativeDiagramStyleConfig`.
                  ``None`` uses the default blue-and-white theme.
    :return: A UTF-8 JSON string suitable for saving as ``<name>.excalidraw``.
    """
    # Reset the global counter so IDs are deterministic per call
    global _id_counter
    _id_counter = 0

    if style is None:
        from eaidl.config import NativeDiagramStyleConfig
        style = NativeDiagramStyleConfig()

    node_map: Dict[int, NativeDiagramNode] = {n.object_id: n for n in diagram.nodes}
    elements: List[Dict[str, Any]] = []

    if diagram.diagram_type == "Sequence":
        # Separate lifelines, fragments, and notes
        lifelines = [n for n in diagram.nodes if n.object_type == "Class"]
        fragments = [n for n in diagram.nodes if n.object_type == "InteractionFragment"]
        notes = [n for n in diagram.nodes if n.object_type == "Note"]

        # Fragments first (background)
        for frag in fragments:
            elements.extend(_fragment_elements(frag, style))

        # Lifelines
        for node in lifelines:
            elements.extend(_lifeline_elements(node, style))

        # Messages
        for msg in diagram.sequence_messages:
            elements.extend(_sequence_message_elements(msg, style))

        # Activation bars
        elements.extend(_activation_bar_elements(
            diagram.sequence_messages, node_map, style
        ))

        # NoteLink connectors
        for conn in diagram.connectors:
            if conn.connector_type == "NoteLink" and not conn.hidden:
                elements.extend(_connector_elements(conn, node_map, style))

        # Note-to-message ref dashed lines
        elements.extend(_note_message_ref_elements(notes, diagram.sequence_messages, style))

        # Notes on top
        for note in notes:
            elements.extend(_note_node_elements(note, style))

    else:
        # Class / Composite Structure diagram
        notes = [n for n in diagram.nodes if n.object_type == "Note"]
        class_nodes = [n for n in diagram.nodes if n.object_type != "Note"]

        for node in class_nodes:
            elements.extend(_class_node_elements(node, style))

        for conn in diagram.connectors:
            if not conn.hidden:
                elements.extend(_connector_elements(conn, node_map, style))

        for note in notes:
            elements.extend(_note_node_elements(note, style))

    doc = {
        "type": "excalidraw",
        "version": 2,
        "source": "https://excalidraw.com",
        "elements": elements,
        "appState": {
            "gridSize": None,
            "viewBackgroundColor": style.canvas_bg_color,
        },
        "files": {},
    }

    return json.dumps(doc, ensure_ascii=False, indent=2)
