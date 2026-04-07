"""
Native EA Diagram SVG Renderer.

Converts a :class:`~eaidl.native_diagram_model.NativeDiagram` (the portable
AST produced by :class:`~eaidl.native_diagram_extractor.NativeDiagramExtractor`)
into a standalone SVG string.

Visual conventions
------------------
* **Class / Part nodes** — header band + attribute compartment.
* **Note nodes** — dog-eared sticky note; content is EA HTML rendered via
  ``<foreignObject>`` so bold/italic/underline/lists are preserved faithfully.
* **Generalization** — solid line, hollow triangle arrowhead at parent.
* **Association** — solid line, open chevron arrowhead, role label near target.
* **NoteLink** — dashed line, no arrowhead.

Coordinate system
-----------------
EA stores positions in a canvas space where Y is zero or negative (Y decreases
downward on screen).  Conversion to SVG coordinates::

    svg_x      = node.rect_left
    svg_y      = -node.rect_top
    svg_width  = node.rect_right  - node.rect_left
    svg_height = node.rect_top    - node.rect_bottom

The SX/SY and EX/EY offsets in the geometry string express displacements from
the geometric centre of the source/target node in EA space (positive Y = up).
When all are zero/absent the renderer clips the straight line to the node border.

Styling
-------
Pass a :class:`~eaidl.config.NativeDiagramStyleConfig` to :func:`render_svg`
to override any colour or font.  The defaults match a clean blue-and-white theme.
"""

from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from io import StringIO
from typing import Dict, List, Optional, Tuple

from eaidl.native_diagram_model import (
    NativeDiagram,
    NativeDiagramConnector,
    NativeDiagramNode,
    NativeSequenceMessage,
)

# ---------------------------------------------------------------------------
# Layout constants (geometry only — not user-overridable)
# ---------------------------------------------------------------------------
PADDING_X = 8  # horizontal text padding inside a node
PADDING_Y = 5  # vertical text padding
HEADER_H = 22  # fixed height of the header band
ATTR_ROW_H = 16  # height per attribute row
NOTE_FOLD = 10  # dog-ear fold size for Note objects
SVG_PAD = 30  # white-space margin around the whole diagram
NOTE_INNER_PAD = 6  # padding inside note content area
LIFELINE_HEAD_H = 55  # height of a lifeline head box in sequence diagrams
FRAGMENT_TAB_W = 90  # width of the keyword tab on an interaction fragment
FRAGMENT_TAB_H = 18  # height of the keyword tab
ACTIVATION_BAR_W = 12  # width of execution specification (activation) box

# ---------------------------------------------------------------------------
# HTML → XHTML conversion for Note content
# ---------------------------------------------------------------------------

# Block-level tags that generate their own line-breaks in HTML layout;
# we strip adjacent bare \r\n next to these so we don't double-space.
_BLOCK_TAGS = {"ul", "ol", "li"}

# Tags whose end form is also a block-level tag
_BLOCK_END_TAGS = {"/ul", "/ol", "/li"}

# Tags allowed through unchanged (void → self-close)
_VOID_TAGS = {"br", "img", "hr"}

# Tags EA typically uses for inline formatting
_INLINE_TAGS = {"b", "i", "u"}


class _XhtmlEmitter(HTMLParser):
    """Parse EA HTML and emit well-formed XHTML into a StringIO buffer."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self._buf = StringIO()
        self._in_block = 0  # nesting level inside block elements

    def handle_starttag(self, tag: str, attrs) -> None:
        tag_l = tag.lower()
        if tag_l in _VOID_TAGS:
            self._buf.write(f"<{tag_l}/>")
        else:
            attr_str = ""
            for name, val in attrs:
                if val is None:
                    attr_str += f" {name}"
                else:
                    val_esc = val.replace("&", "&amp;").replace('"', "&quot;")
                    attr_str += f' {name}="{val_esc}"'
            self._buf.write(f"<{tag_l}{attr_str}>")
        if tag_l in _BLOCK_TAGS:
            self._in_block += 1

    def handle_endtag(self, tag: str) -> None:
        tag_l = tag.lower()
        if tag_l in _VOID_TAGS:
            return  # already self-closed in handle_starttag
        self._buf.write(f"</{tag_l}>")
        if tag_l in _BLOCK_TAGS:
            self._in_block = max(0, self._in_block - 1)

    def handle_data(self, data: str) -> None:
        # Normalise line endings
        data = data.replace("\r\n", "\n").replace("\r", "\n")
        if self._in_block == 0:
            # Outside lists: convert newlines to <br/>
            data = data.replace("\n", "<br/>")
            self._buf.write(data)
        else:
            # Inside lists: strip structural whitespace, escape text nodes
            stripped = data.strip("\n\t ")
            if stripped:
                esc = stripped.replace("&", "&amp;").replace("<", "&lt;")
                self._buf.write(esc)

    def handle_entityref(self, name: str) -> None:
        self._buf.write(f"&{name};")

    def handle_charref(self, name: str) -> None:
        self._buf.write(f"&#{name};")

    def result(self) -> str:
        return self._buf.getvalue()


def _ea_html_to_xhtml(raw: Optional[str]) -> str:
    """
    Convert EA note HTML to a well-formed XHTML fragment suitable for
    embedding inside an SVG ``<foreignObject>``.

    Handles ``<b>``, ``<i>``, ``<u>``, ``<ul>``, ``<ol>``, ``<li>``,
    ``<br>``, ``\\r\\n`` line-breaks, and basic character entities.
    """
    if not raw:
        return ""
    emitter = _XhtmlEmitter()
    emitter.feed(raw)
    xhtml = emitter.result()
    # Remove trailing empty inline-formatting wrappers EA sometimes emits
    xhtml = re.sub(r"(<(?:b|i|u)>)\s*(<br/>)?\s*(</(?:b|i|u)>)", "", xhtml)
    # Collapse runs of 3+ consecutive <br/> into two
    xhtml = re.sub(r"(<br/>){3,}", "<br/><br/>", xhtml)
    return xhtml.strip()


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------


def _node_link_href(node: NativeDiagramNode, style) -> Optional[str]:
    """
    Compute the href for a linkable node, or ``None`` if links are disabled.

    * When ``style.node_link_template`` is ``""``  → no link.
    * When it is ``None``  → placeholder ``eaidl:{guid}`` (or ``eaidl:#{object_id}``
      if the node has no GUID).
    * Otherwise the template is formatted with ``name``, ``guid``,
      ``object_id``, ``stereotype``.
    """
    template = style.node_link_template
    if template == "":
        return None
    guid = node.ea_guid or f"#{node.object_id}"
    if template is None:
        return f"eaidl:{guid}"
    return template.format(
        name=node.name,
        guid=guid,
        object_id=node.object_id,
        stereotype=node.stereotype or "",
    )


def svg_link_map(diagram: NativeDiagram) -> Dict[str, Dict]:
    """
    Return a dict mapping each named node\'s ``ea_guid`` to its metadata.

    The returned structure is deliberately compatible with the YAML exported by
    ``model_export.py``.  Keys match ``ModelClass.guid`` so post-processors can
    join the two data sources on GUID::

        link_map = svg_link_map(diagram)
        # link_map['{3522A830-...}'] ==
        #   {'name': 'Message', 'object_id': 35,
        #    'object_type': 'Class', 'stereotype': 'struct',
        #    'href_placeholder': 'eaidl:{3522A830-...}'}

    Nodes without a GUID (unusual) use the key ``"#<object_id>"`` instead.
    """
    result: Dict[str, Dict] = {}
    for node in diagram.nodes:
        if node.object_type == "Note":
            continue
        key = node.ea_guid or f"#{node.object_id}"
        result[key] = {
            "name": node.name,
            "object_id": node.object_id,
            "object_type": node.object_type,
            "stereotype": node.stereotype,
            "href_placeholder": f"eaidl:{key}",
        }
    return result


def rewrite_svg_links(svg: str, guid_to_url: Dict[str, str]) -> str:
    """
    Replace ``eaidl:{guid}`` placeholder hrefs in *svg* with real URLs.

    :param svg: SVG string as produced by :func:`render_svg`.
    :param guid_to_url: Mapping of ``ea_guid`` → URL string, e.g. from a
        post-processor that has consulted the model YAML.
    :return: Updated SVG string.
    """
    for guid, url in guid_to_url.items():
        svg = svg.replace(f"eaidl:{guid}", url)
    return svg


def _ea_to_svg(node: NativeDiagramNode) -> Tuple[float, float, float, float]:
    """Return (x, y, width, height) in SVG coordinates for *node*."""
    x = float(node.rect_left)
    y = float(-node.rect_top)
    w = float(node.rect_right - node.rect_left)
    h = float(node.rect_top - node.rect_bottom)
    return x, y, w, h


def _node_center(node: NativeDiagramNode) -> Tuple[float, float]:
    x, y, w, h = _ea_to_svg(node)
    return x + w / 2, y + h / 2


def _argb_to_css(argb: int, fallback: Optional[str] = None) -> Optional[str]:
    """Convert EA ARGB integer to a CSS hex colour, or *fallback* if -1 (default/unset)."""
    if argb < 0:
        return fallback
    b = argb & 0xFF
    g = (argb >> 8) & 0xFF
    r = (argb >> 16) & 0xFF
    return f"#{r:02x}{g:02x}{b:02x}"


def _clip_to_rect(
    cx: float,
    cy: float,
    w: float,
    h: float,
    dx: float,
    dy: float,
) -> Tuple[float, float]:
    """
    Return the point where the ray from (cx, cy) in direction (dx, dy) first
    crosses the boundary of the axis-aligned rectangle centred at (cx, cy)
    with dimensions w×h.  If dx==dy==0 returns (cx, cy).
    """
    if dx == 0 and dy == 0:
        return cx, cy
    hw, hh = w / 2, h / 2
    # Clip in X and Y separately
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
    """
    Compute the start (on source border) and end (on target border) of a
    connector line.

    If SX/SY/EX/EY offsets are provided and non-zero they express the
    connection point as an offset from the node centre in EA space
    (positive Y = up).  Otherwise, the connector is clipped to the border
    using the straight line between centres.
    """
    scx, scy = _node_center(src)
    tcx, tcy = _node_center(tgt)
    _, _, sw, sh = _ea_to_svg(src)
    _, _, tw, th = _ea_to_svg(tgt)

    if sx is not None and (sx != 0 or sy != 0):
        p1 = (scx + sx, scy - (sy or 0))  # EA +Y = SVG -Y
    else:
        dx, dy = tcx - scx, tcy - scy
        p1 = _clip_to_rect(scx, scy, sw, sh, dx, dy)

    if ex is not None and (ex != 0 or ey != 0):
        p2 = (tcx + ex, tcy - (ey or 0))
    else:
        dx, dy = scx - tcx, scy - tcy
        p2 = _clip_to_rect(tcx, tcy, tw, th, dx, dy)

    return p1, p2


def _waypoints_svg(conn: NativeDiagramConnector) -> List[Tuple[float, float]]:
    """Convert stored waypoints to SVG coordinate space."""
    return [(float(wp[0]), float(-wp[1])) for wp in conn.geometry.waypoints]


# ---------------------------------------------------------------------------
# Sequence diagram helpers
# ---------------------------------------------------------------------------


def _render_lifeline(parent: ET.Element, node: NativeDiagramNode, style) -> None:
    """Render a sequence-diagram lifeline (head box + dashed vertical line)."""
    x, y, w, h = _ea_to_svg(node)
    cx = x + w / 2

    head_h = min(LIFELINE_HEAD_H, h)
    bg = _argb_to_css(node.style.background_color, style.node_header_color)
    border = _argb_to_css(node.style.line_color, style.node_border_color)

    href = _node_link_href(node, style)
    container = parent
    if href and node.name:
        a = ET.SubElement(parent, "a")
        a.set("href", href)
        a.set("xlink:href", href)
        container = a

    g = ET.SubElement(container, "g", **{"class": "lifeline", "data-object-id": str(node.object_id)})

    # Head box
    ET.SubElement(
        g, "rect", x=str(x), y=str(y), width=str(w), height=str(head_h), fill=bg, stroke=border, **{"stroke-width": "1"}
    )

    # Stereotype
    name_y = y + head_h - PADDING_Y
    if node.stereotype:
        ET.SubElement(
            g,
            "text",
            x=str(cx),
            y=str(y + 14),
            **{
                "text-anchor": "middle",
                "font-family": style.font_family,
                "font-size": "9",
                "font-style": "italic",
                "fill": style.node_header_text_color,
            },
        ).text = f"\u00ab{node.stereotype}\u00bb"
        name_y = y + head_h - 3

    ET.SubElement(
        g,
        "text",
        x=str(cx),
        y=str(name_y),
        **{
            "text-anchor": "middle",
            "font-family": style.font_family,
            "font-size": str(style.font_size),
            "font-weight": "bold",
            "fill": style.node_header_text_color,
        },
    ).text = node.name

    # Dashed lifeline extending downward
    line_top = y + head_h
    line_bot = y + h
    ET.SubElement(
        g,
        "line",
        x1=str(cx),
        y1=str(line_top),
        x2=str(cx),
        y2=str(line_bot),
        stroke=border,
        **{"stroke-width": "1", "stroke-dasharray": "6,4"},
    )


def _render_interaction_fragment(parent: ET.Element, node: NativeDiagramNode, style) -> None:
    """Render a UML CombinedFragment (alt/opt/loop) box with keyword tab."""
    x, y, w, h = _ea_to_svg(node)
    border = _argb_to_css(node.style.line_color, style.node_border_color)

    g = ET.SubElement(parent, "g", **{"class": "fragment", "data-object-id": str(node.object_id)})

    # Outer dashed rectangle
    ET.SubElement(
        g, "rect", x=str(x), y=str(y), width=str(w), height=str(h), fill="none", stroke=border, **{"stroke-width": "1"}
    )

    # Keyword tab (pentagon) at top-left
    tw = min(FRAGMENT_TAB_W, w * 0.4)
    th = FRAGMENT_TAB_H
    tab_pts = f"{x},{y} {x+tw},{y} {x+tw+8},{y+th/2} " f"{x+tw},{y+th} {x},{y+th}"
    ET.SubElement(g, "polygon", points=tab_pts, fill=style.node_header_color, stroke=border, **{"stroke-width": "1"})

    keyword = node.stereotype or "alt"
    ET.SubElement(
        g,
        "text",
        x=str(x + 5),
        y=str(y + th - 4),
        **{"font-family": style.font_family, "font-size": "9", "fill": style.node_header_text_color},
    ).text = keyword

    # Label text at top-right of the tab area
    if node.name:
        ET.SubElement(
            g,
            "text",
            x=str(x + tw + 14),
            y=str(y + th - 4),
            **{"font-family": style.font_family, "font-size": "9", "fill": style.node_border_color},
        ).text = node.name


def _render_sequence_message(
    parent: ET.Element,
    msg: NativeSequenceMessage,
    activation_spans: Dict[int, List[Tuple[float, float]]],
    style,
) -> None:
    """Render one sequence message as a horizontal (or self-referencing) arrow."""
    x1 = float(msg.start_x)
    y1 = float(-msg.start_y)  # EA Y is negative
    x2 = float(msg.end_x)
    y2 = float(-msg.end_y)

    is_return = x2 < x1  # simple heuristic: right-to-left = reply
    is_self = msg.source_object_id == msg.target_object_id

    g = ET.SubElement(parent, "g", **{"class": "seq-message", "data-seq": str(msg.seq_no)})

    stroke = style.connector_color
    stroke_w = "1"

    if is_self:
        # Self-referencing loop: small rectangle on the right side
        loop_w, loop_h = 40, 30
        d = f"M {x1},{y1} L {x1+loop_w},{y1} L {x1+loop_w},{y1+loop_h} L {x2},{y2+loop_h}"
        ET.SubElement(
            g, "path", d=d, fill="none", stroke=stroke, **{"stroke-width": stroke_w, "marker-end": "url(#arrow-open)"}
        )
    else:
        path_attrs: Dict[str, str] = {
            "d": f"M {x1},{y1} L {x2},{y2}",
            "fill": "none",
            "stroke": stroke,
            "stroke-width": stroke_w,
            "marker-end": "url(#arrow-open)",
        }
        if is_return:
            path_attrs["stroke-dasharray"] = "6,3"
        ET.SubElement(g, "path", **path_attrs)

    # Activation box at the destination end (arrowhead tip).
    # The actual rectangles are rendered by _render_activation_bars; nothing here.

    # Build label: Name(params) / Name(params): retval
    label = msg.name or ""
    if msg.param_values:
        label += f"({msg.param_values})"
    ret_label = ""
    if msg.return_value:
        ret_label = msg.return_value

    mid_x = (x1 + x2) / 2
    label_y = y1 - 5  # just above the line

    if msg.stereotype:
        ET.SubElement(
            g,
            "text",
            x=str(mid_x),
            y=str(label_y - 11),
            **{
                "text-anchor": "middle",
                "font-family": style.font_family,
                "font-size": "9",
                "font-style": "italic",
                "fill": style.connector_color,
            },
        ).text = f"\u00ab{msg.stereotype}\u00bb"
        label_y -= 2

    if label:
        ET.SubElement(
            g,
            "text",
            x=str(mid_x),
            y=str(label_y),
            **{
                "text-anchor": "middle",
                "font-family": style.font_family,
                "font-size": str(style.font_size),
                "fill": style.node_border_color,
            },
        ).text = label

    if ret_label:
        ET.SubElement(
            g,
            "text",
            x=str(mid_x),
            y=str(label_y + 11),
            **{
                "text-anchor": "middle",
                "font-family": style.font_family,
                "font-size": str(style.font_size),
                "fill": style.node_border_color,
            },
        ).text = ret_label


def _compute_activation_spans(
    messages: List[NativeSequenceMessage],
    node_map: Dict[int, NativeDiagramNode],
) -> Dict[int, List[Tuple[float, float]]]:
    """
    Compute activation bar (execution-specification) spans per lifeline.

    Strategy: for each message, the DESTINATION lifeline becomes "active" at
    that message's Y and stays active until the next message that departs FROM
    that same lifeline.  The span is ``(top_svg_y, bottom_svg_y)``.

    Returns a dict mapping ``object_id -> list of (top, bottom)`` spans in
    SVG coordinate space.
    """
    # Collect (svg_y, object_id, role) tuples sorted by svg_y
    events: List[Tuple[float, int, str]] = []  # (svg_y, object_id, 'arrive'|'depart')
    for msg in messages:
        y_svg = float(-msg.start_y)  # EA y is negative → SVG y is positive
        events.append((y_svg, msg.source_object_id, "depart"))
        events.append((y_svg, msg.target_object_id, "arrive"))
    events.sort(key=lambda e: e[0])

    # Find contiguous arrive→depart pairs per lifeline
    spans: Dict[int, List[Tuple[float, float]]] = {}
    pending: Dict[int, float] = {}  # object_id → svg_y where activation started

    for y_svg, obj_id, role in events:
        if role == "arrive":
            if obj_id not in pending:
                pending[obj_id] = y_svg
        elif role == "depart":
            if obj_id in pending:
                top = pending.pop(obj_id)
                spans.setdefault(obj_id, []).append((top, y_svg))

    # Close any unclosed activations (last message had no return)
    for obj_id, top in pending.items():
        bottom = top + 20
        spans.setdefault(obj_id, []).append((top, bottom))

    return spans


def _render_activation_bars(
    parent: ET.Element,
    spans: Dict[int, List[Tuple[float, float]]],
    node_map: Dict[int, NativeDiagramNode],
    style,
) -> None:
    """Draw activation (execution specification) rectangles for each lifeline."""
    hw = ACTIVATION_BAR_W / 2
    for obj_id, obj_spans in spans.items():
        node = node_map.get(obj_id)
        if node is None:
            continue
        _, _, w, _ = _ea_to_svg(node)
        cx_node = float(node.rect_left) + w / 2  # centre x of lifeline
        border = _argb_to_css(node.style.line_color, style.node_border_color)
        for top, bottom in obj_spans:
            h = max(bottom - top, 4)
            ET.SubElement(
                parent,
                "rect",
                x=str(cx_node - hw),
                y=str(top),
                width=str(ACTIVATION_BAR_W),
                height=str(h),
                fill=style.node_bg_color,
                stroke=border,
                **{"stroke-width": "1"},
            )


def _render_note_connector_refs(
    parent: ET.Element,
    notes: List[NativeDiagramNode],
    messages: List[NativeSequenceMessage],
    style,
) -> None:
    """
    Draw dashed lines from notes that reference a sequence message connector
    (``note_connector_ref``) to the midpoint of that message arrow.
    """
    msg_by_id = {m.connector_id: m for m in messages}

    for note in notes:
        if note.note_connector_ref is None:
            continue
        msg = msg_by_id.get(note.note_connector_ref)
        if msg is None:
            continue

        # Note centre
        nx = float(note.rect_left + note.rect_right) / 2
        ny = float(-note.rect_top + -(note.rect_bottom)) / 2  # avg of svg y values
        # actually: note svg coords
        nx = float(note.rect_left + note.rect_right) / 2
        ny = (-float(note.rect_top) + -float(note.rect_bottom)) / 2

        # Message midpoint
        mx = (float(msg.start_x) + float(msg.end_x)) / 2
        my = (-float(msg.start_y) + -float(msg.end_y)) / 2

        ET.SubElement(
            parent,
            "line",
            x1=str(nx),
            y1=str(ny),
            x2=str(mx),
            y2=str(my),
            stroke=style.connector_note_color,
            **{"stroke-width": "1", "stroke-dasharray": "5,3"},
        )


# Placeholder tag replaced with <foreignObject> after ET serialisation
_NOTE_PLACEHOLDER = "__NOTEFO_{oid}__"


def _build_defs(root: ET.Element, style) -> None:
    """Add shared ``<defs>`` (arrow markers) using colours from *style*."""
    defs = ET.SubElement(root, "defs")
    c = style.connector_color

    # Open chevron (Association and default)
    m = ET.SubElement(
        defs, "marker", id="arrow-open", markerWidth="10", markerHeight="7", refX="9", refY="3.5", orient="auto"
    )
    ET.SubElement(m, "polyline", points="0,0 9,3.5 0,7", fill="none", stroke=c, **{"stroke-width": "1.2"})

    # Hollow triangle (Generalization — points *to* the parent)
    m2 = ET.SubElement(
        defs,
        "marker",
        id="arrow-generalization",
        markerWidth="10",
        markerHeight="7",
        refX="9",
        refY="3.5",
        orient="auto",
    )
    ET.SubElement(m2, "polygon", points="0,0 9,3.5 0,7", fill=style.node_bg_color, stroke=c, **{"stroke-width": "1"})

    # Diamond (Aggregation / Composition — at source end)
    m3 = ET.SubElement(
        defs,
        "marker",
        id="arrow-diamond",
        markerWidth="12",
        markerHeight="8",
        refX="0",
        refY="4",
        orient="auto-start-reverse",
    )
    ET.SubElement(m3, "polygon", points="0,4 5,0 10,4 5,8", fill=style.node_bg_color, stroke=c, **{"stroke-width": "1"})


def _attr_link_href(attr, style, node=None) -> Optional[str]:
    """Return the link href for an attribute row, or ``None``.

    Priority:
    1. ``attr.type_guid`` → links to the type class.
    2. Enum-literal fallback: when the attribute name starts with the parent
       node name (EA convention ``EnumName_LITERAL_VALUE``), link back to the
       parent node itself so the literal is navigable to its enum definition.
    """
    template = style.node_link_template
    if template == "":
        return None
    if attr.type_guid:
        guid = attr.type_guid
        if template is None:
            return f"eaidl:{guid}"
        return template.format(
            name=attr.type,
            guid=guid,
            object_id="",
            stereotype="",
        )
    # Enum-literal fallback: self-link to the parent node
    if node is not None and node.ea_guid and node.name and attr.name.startswith(node.name + "_"):
        return _node_link_href(node, style)
    return None


def _node_min_width(node: NativeDiagramNode, style) -> float:
    """Return the minimum node width needed to display the header and all
    attribute labels without clipping."""
    _char_w_name = style.font_size * 0.62
    _char_w_attr = style.attr_font_size * 0.62
    header_lines = []
    if node.stereotype:
        header_lines.append(f"\u00ab{node.stereotype}\u00bb")
    header_lines.append(f"\u00ababstract\u00bb {node.name}" if node.is_abstract else (node.name or ""))
    min_w = max((len(line) * _char_w_name for line in header_lines), default=0) + 2 * PADDING_X
    for attr in node.attributes:
        lb, ub = attr.lower_bound or "", attr.upper_bound or ""
        card = f" [{lb}..{ub}]" if (lb or ub) else ""
        label = f"+ {attr.name} : {attr.type}{card}"
        min_w = max(min_w, len(label) * _char_w_attr + 2 * PADDING_X)
    return min_w


def _render_class_node(parent: ET.Element, node: NativeDiagramNode, style) -> None:
    """Render a Class or Part node.  The header links to the class; each
    attribute row links to the type of that attribute (when resolvable)."""
    x, y, w, h = _ea_to_svg(node)
    # Per-node colour overrides from objectstyle take precedence over config
    bg = _argb_to_css(node.style.background_color, style.node_bg_color)
    # Parts inside composite diagrams get a slightly lighter fill by default
    if node.object_type == "Part" and node.style.background_color < 0:
        bg = style.part_bg_color
    border = _argb_to_css(node.style.line_color, style.node_border_color)
    lw = node.style.line_width if node.style.line_width > 0 else style.node_border_width

    g = ET.SubElement(parent, "g", **{"class": "node-class", "data-object-id": str(node.object_id)})

    # Body rectangle (rendered before header so header border paints on top).
    # Node borders use the EA-stored dimensions so diagram layout is preserved.
    body_y = y + HEADER_H
    body_h = max(h - HEADER_H, ATTR_ROW_H * max(1, len(node.attributes)) + 2 * PADDING_Y)
    ET.SubElement(
        g,
        "rect",
        x=str(x),
        y=str(body_y),
        width=str(w),
        height=str(body_h),
        fill=bg,
        stroke=border,
        **{"stroke-width": str(lw)},
    )

    # Header — optionally wrapped in a link to the class itself
    node_href = _node_link_href(node, style)
    hdr_container: ET.Element = g
    if node_href and node.name:
        a = ET.SubElement(g, "a")
        a.set("href", node_href)
        a.set("xlink:href", node_href)
        hdr_container = a

    ET.SubElement(
        hdr_container,
        "rect",
        x=str(x),
        y=str(y),
        width=str(w),
        height=str(HEADER_H),
        fill=style.node_header_color,
        stroke=border,
        **{"stroke-width": str(lw)},
    )

    # Stereotype (small italic, rendered first so name sits below it)
    name_text = f"«abstract» {node.name}" if node.is_abstract else node.name
    text_y = y + HEADER_H - PADDING_Y
    if node.stereotype:
        ET.SubElement(
            hdr_container,
            "text",
            x=str(x + w / 2),
            y=str(y + 10),
            **{
                "text-anchor": "middle",
                "font-family": style.font_family,
                "font-size": "9",
                "font-style": "italic",
                "fill": style.node_header_text_color,
            },
        ).text = f"«{node.stereotype}»"
        text_y = y + HEADER_H - 2

    # Class name (bold)
    ET.SubElement(
        hdr_container,
        "text",
        x=str(x + w / 2),
        y=str(text_y),
        **{
            "text-anchor": "middle",
            "font-family": style.font_family,
            "font-size": str(style.font_size),
            "font-weight": "bold",
            "fill": style.node_header_text_color,
        },
    ).text = name_text

    # Attributes — no clip applied so long labels are fully visible even if they
    # extend past the node border.  The viewBox is sized to accommodate them.
    for i, attr in enumerate(node.attributes):
        ay = body_y + PADDING_Y + (i + 0.8) * ATTR_ROW_H
        lb, ub = attr.lower_bound or "", attr.upper_bound or ""
        card = f" [{lb}..{ub}]" if (lb or ub) else ""
        label = f"+ {attr.name} : {attr.type}{card}"
        type_href = _attr_link_href(attr, style, node)
        if type_href:
            a = ET.SubElement(g, "a")
            a.set("href", type_href)
            a.set("xlink:href", type_href)
            txt_parent: ET.Element = a
        else:
            txt_parent = g
        ET.SubElement(
            txt_parent,
            "text",
            x=str(x + PADDING_X),
            y=str(ay),
            **{
                "font-family": style.font_family,
                "font-size": str(style.attr_font_size),
                "fill": style.node_border_color,
            },
        ).text = label


def _render_note_node(
    parent: ET.Element,
    node: NativeDiagramNode,
    style,
    fo_map: Dict[int, str],
) -> None:
    """
    Render a Note object as a dog-eared box.

    EA note content is rich HTML (bold/italic/underline/lists), so it is
    placed inside an SVG ``<foreignObject>`` with XHTML content.  Because
    ElementTree would escape the inner HTML, the foreign-object string is
    built separately and tracked in *fo_map*, which the caller splices into
    the final SVG string after serialisation.
    """
    x, y, w, h = _ea_to_svg(node)
    f = NOTE_FOLD

    g = ET.SubElement(parent, "g", **{"class": "node-note", "data-object-id": str(node.object_id)})

    # Dog-eared polygon
    points = f"{x},{y} {x+w-f},{y} {x+w},{y+f} {x+w},{y+h} {x},{y+h}"
    ET.SubElement(
        g, "polygon", points=points, fill=style.note_bg_color, stroke=style.note_border_color, **{"stroke-width": "1"}
    )

    # Fold triangle
    fold_pts = f"{x+w-f},{y} {x+w},{y+f} {x+w-f},{y+f}"
    ET.SubElement(
        g, "polygon", points=fold_pts, fill="#fff9c4", stroke=style.note_border_color, **{"stroke-width": "1"}
    )

    # Placeholder element — replaced post-serialisation with the foreignObject
    ph = ET.SubElement(g, "desc")
    ph.text = _NOTE_PLACEHOLDER.format(oid=node.object_id)

    # Build the foreignObject HTML string independently
    raw_html = node.note_text or node.name or ""
    xhtml = _ea_html_to_xhtml(raw_html)
    cx = x + NOTE_INNER_PAD
    cy = y + NOTE_INNER_PAD
    cw = max(w - 2 * NOTE_INNER_PAD, 10)
    ch = max(h - 2 * NOTE_INNER_PAD, 10)
    fo_map[node.object_id] = (
        f'<foreignObject x="{cx}" y="{cy}" width="{cw}" height="{ch}">'
        f'<div xmlns="http://www.w3.org/1999/xhtml" style="'
        f"font-family: {style.font_family}; "
        f"font-size: {style.note_font_size}px; "
        f"color: {style.note_text_color}; "
        f"overflow: hidden; "
        f'word-wrap: break-word;">'
        f"{xhtml}"
        f"</div></foreignObject>"
    )


def _render_connector(
    parent: ET.Element,
    conn: NativeDiagramConnector,
    node_map: Dict[int, NativeDiagramNode],
    style,
) -> None:
    """Render a single connector with appropriate routing and arrowhead."""
    src = node_map.get(conn.source_object_id)
    tgt = node_map.get(conn.target_object_id)
    if src is None or tgt is None:
        return

    g = ET.SubElement(parent, "g", **{"class": "connector", "data-connector-id": str(conn.connector_id)})

    geo = conn.geometry
    p1, p2 = _edge_points(src, tgt, geo.source_x, geo.source_y, geo.end_x, geo.end_y)
    wpts = _waypoints_svg(conn)

    ctype = conn.connector_type or "Association"
    is_note_link = ctype == "NoteLink"
    is_generalisation = ctype == "Generalization"
    is_aggregation = ctype in ("Aggregation", "Composition")

    all_pts = [p1] + wpts + [p2]
    d = "M " + " L ".join(f"{px},{py}" for px, py in all_pts)

    stroke = _argb_to_css(conn.style.color) or (style.connector_note_color if is_note_link else style.connector_color)
    stroke_w = str(max(conn.style.line_width, 1))

    path_attrs: Dict[str, str] = {
        "d": d,
        "fill": "none",
        "stroke": stroke,
        "stroke-width": stroke_w,
    }
    if is_note_link:
        path_attrs["stroke-dasharray"] = "4,3"
    if is_generalisation:
        path_attrs["marker-end"] = "url(#arrow-generalization)"
    elif is_aggregation:
        path_attrs["marker-start"] = "url(#arrow-diamond)"
        path_attrs["marker-end"] = "url(#arrow-open)"
    elif not is_note_link:
        path_attrs["marker-end"] = "url(#arrow-open)"

    ET.SubElement(g, "path", **path_attrs)

    # Role label near target end
    if conn.target_role:
        lx = p2[0] * 0.8 + p1[0] * 0.2
        ly = p2[1] * 0.8 + p1[1] * 0.2 - 6
        ET.SubElement(
            g,
            "text",
            x=str(lx),
            y=str(ly),
            **{"font-family": style.font_family, "font-size": "9", "fill": style.node_border_color},
        ).text = conn.target_role


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def render_svg(diagram: NativeDiagram, style=None) -> str:
    """
    Render *diagram* to a UTF-8 SVG string.

    :param diagram: A :class:`~eaidl.native_diagram_model.NativeDiagram` as
                    produced by :class:`~eaidl.native_diagram_extractor.NativeDiagramExtractor`.
    :param style: A :class:`~eaidl.config.NativeDiagramStyleConfig` instance.
                  When ``None`` the default style (blue-and-white theme) is used.
    :return: A complete standalone SVG document as a ``str``.
    """
    if style is None:
        from eaidl.config import NativeDiagramStyleConfig

        style = NativeDiagramStyleConfig()

    node_map: Dict[int, NativeDiagramNode] = {n.object_id: n for n in diagram.nodes}

    # Compute bounding box over all nodes to set viewBox.
    # Use the effective right edge (accounting for min-width expansion) so
    # nodes whose names or attribute labels are wider than the EA-stored
    # rectangle are not clipped by the canvas.
    if diagram.nodes:
        xs_left = [n.rect_left for n in diagram.nodes]
        xs_right = [
            n.rect_left + max(float(n.rect_right - n.rect_left), _node_min_width(n, style)) for n in diagram.nodes
        ]
        ys_top = [-n.rect_top for n in diagram.nodes]
        ys_bot = [-n.rect_bottom for n in diagram.nodes]
        min_x = min(xs_left) - SVG_PAD
        min_y = min(ys_top) - SVG_PAD
        max_x = max(xs_right) + SVG_PAD
        max_y = max(ys_bot) + SVG_PAD
    else:
        min_x, min_y, max_x, max_y = 0, 0, float(diagram.canvas_width), float(diagram.canvas_height)

    vw = max_x - min_x
    vh = max_y - min_y

    root = ET.Element(
        "svg",
        xmlns="http://www.w3.org/2000/svg",
        version="1.1",
        viewBox=f"{min_x} {min_y} {vw} {vh}",
        width=str(int(vw)),
        height=str(int(vh)),
    )
    root.set("xmlns:xlink", "http://www.w3.org/1999/xlink")

    # Background
    ET.SubElement(root, "rect", x=str(min_x), y=str(min_y), width=str(vw), height=str(vh), fill=style.canvas_bg_color)

    _build_defs(root, style)

    ET.SubElement(root, "title").text = diagram.name

    fo_map: Dict[int, str] = {}

    if diagram.diagram_type == "Sequence":
        _render_sequence_content(root, diagram, node_map, style, fo_map)
    else:
        _render_class_content(root, diagram, node_map, style, fo_map)

    # Diagram caption
    ET.SubElement(
        root,
        "text",
        x=str(min_x + SVG_PAD),
        y=str(min_y + SVG_PAD - 8),
        **{"font-family": style.font_family, "font-size": "13", "font-weight": "bold", "fill": style.node_border_color},
    ).text = diagram.name

    ET.indent(root, space="  ")
    svg_str = '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode")

    # Splice foreignObject HTML in place of each placeholder <desc> element
    for oid, fo_html in fo_map.items():
        placeholder = f"<desc>{_NOTE_PLACEHOLDER.format(oid=oid)}</desc>"
        svg_str = svg_str.replace(placeholder, fo_html)

    return svg_str


def _render_class_content(
    root: ET.Element,
    diagram: NativeDiagram,
    node_map: Dict[int, NativeDiagramNode],
    style,
    fo_map: Dict[int, str],
) -> None:
    """Render connectors + nodes for a standard class/composite diagram."""
    conn_group = ET.SubElement(root, "g", id="connectors")
    for conn in diagram.connectors:
        if not conn.hidden:
            _render_connector(conn_group, conn, node_map, style)

    node_group = ET.SubElement(root, "g", id="nodes")
    for node in diagram.nodes:
        if node.object_type == "Note":
            _render_note_node(node_group, node, style, fo_map)
        else:
            _render_class_node(node_group, node, style)


def _render_sequence_content(
    root: ET.Element,
    diagram: NativeDiagram,
    node_map: Dict[int, NativeDiagramNode],
    style,
    fo_map: Dict[int, str],
) -> None:
    """Render a sequence diagram: lifelines, messages, fragments, notes."""
    # Separate node types
    lifelines = [
        n
        for n in diagram.nodes
        if n.object_type in ("Part", "Class") and n.name  # exclude unnamed stubs
    ]
    fragments = [n for n in diagram.nodes if n.object_type == "InteractionFragment"]
    notes = [n for n in diagram.nodes if n.object_type == "Note"]

    # 1. Interaction fragments (lowest layer)
    frag_group = ET.SubElement(root, "g", id="fragments")
    for frag in fragments:
        _render_interaction_fragment(frag_group, frag, style)

    # 2. Lifelines
    lf_group = ET.SubElement(root, "g", id="lifelines")
    for node in lifelines:
        _render_lifeline(lf_group, node, style)

    # 3. Messages
    msg_group = ET.SubElement(root, "g", id="messages")
    activation_spans = _compute_activation_spans(diagram.sequence_messages, node_map)
    for msg in diagram.sequence_messages:
        _render_sequence_message(msg_group, msg, activation_spans, style)

    # 3b. Activation bars (drawn over messages, under notes)
    act_group = ET.SubElement(root, "g", id="activation-bars")
    _render_activation_bars(act_group, activation_spans, node_map, style)

    # 4. NoteLink connectors to lifeline objects
    conn_group = ET.SubElement(root, "g", id="note-connectors")
    for conn in diagram.connectors:
        if conn.connector_type == "NoteLink" and not conn.hidden:
            _render_connector(conn_group, conn, node_map, style)

    # 4b. Note-to-message connector refs (dashed lines from notes to messages)
    ref_group = ET.SubElement(root, "g", id="note-message-refs")
    _render_note_connector_refs(ref_group, notes, diagram.sequence_messages, style)

    # 5. Notes on top
    note_group = ET.SubElement(root, "g", id="notes")
    for note in notes:
        _render_note_node(note_group, note, style, fo_map)
