"""
Native EA Diagram SVG Renderer.

Converts a :class:`~eaidl.native_diagram_model.NativeDiagram` (the portable
AST produced by :class:`~eaidl.native_diagram_extractor.NativeDiagramExtractor`)
into a standalone SVG string.

Visual conventions
------------------
* **Class / Part nodes** — header band + attribute compartment.
* **Note nodes** — dog-eared note with portable SVG text.
* **Generalization** — solid line, hollow triangle arrowhead at parent.
* **Association** — solid line; arrowheads follow the EA direction setting.
* **Aggregation** — diamond at the aggregate end; fill follows its EA flag.
* **Usage / dependency / abstraction / realization** — dashed lines.
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
import textwrap
import xml.etree.ElementTree as ET
from html import unescape
from html.parser import HTMLParser
from io import StringIO
from typing import Dict, List, Optional, Tuple

from eaidl.native_diagram_model import (
    NativeDiagram,
    NativeDiagramAttribute,
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
NOTE_FOLD = 12  # EA's dog-ear fold size for Note objects
SVG_PAD = 30  # white-space margin around the whole diagram
NOTE_INNER_PAD = 6  # padding inside note content area
LIFELINE_HEAD_H = 50  # EA's standard lifeline head height
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


class _PlainNoteEmitter(HTMLParser):
    """Preserve EA note paragraphs and list markers for portable SVG text."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.lines: List[str] = []
        self.current: List[str] = []
        self.lists: List[List[object]] = []
        self.in_item = False

    def _flush(self) -> None:
        line = re.sub(r"\s+", " ", "".join(self.current)).strip()
        if line:
            self.lines.append(line)
        self.current.clear()

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in ("ul", "ol"):
            self._flush()
            self.lists.append([tag, 0])
        elif tag == "li":
            self._flush()
            if self.lists and self.lists[-1][0] == "ol":
                self.lists[-1][1] += 1
                self.current.append(f"{self.lists[-1][1]}. ")
            else:
                self.current.append("- ")
            self.in_item = True
        elif tag in ("br", "p", "div"):
            self._flush()

    def handle_endtag(self, tag: str) -> None:
        if tag == "li":
            self._flush()
            self.in_item = False
        elif tag in ("ul", "ol"):
            self._flush()
            if self.lists:
                self.lists.pop()
        elif tag in ("p", "div"):
            self._flush()

    def handle_data(self, data: str) -> None:
        data = data.replace("\r\n", "\n").replace("\r", "\n")
        if self.in_item:
            self.current.append(data.replace("\n", " "))
        else:
            parts = data.split("\n")
            for index, part in enumerate(parts):
                if index:
                    self._flush()
                self.current.append(part)


def _plain_note_lines(raw: str) -> List[str]:
    emitter = _PlainNoteEmitter()
    emitter.feed(raw)
    emitter._flush()
    return emitter.lines


def ea_text_width(text: str, font_size: float) -> float:
    """Approximate EA/Carlito glyph widths without a platform font dependency (also sizes eaedit's layout boxes)."""
    width = 0.0
    for char in text:
        if char in "ilI.,:;!|'`":
            width += 2.2
        elif char in "frtJ":
            width += 3.3
        elif char == " ":
            width += 2.5
        elif char in "mwMW@":
            width += 7.2
        elif char.isupper():
            width += 5.8
        elif char.isdigit():
            width += 5.0
        elif char in "()[]":
            width += 3.0
        elif char in "-_":
            width += 5.0
        else:
            width += 4.5
    return width * font_size / 10


#: The name the renderer's own callers use.
_ea_text_width = ea_text_width


def _wrap_ea_text(paragraph: str, max_width: float, font_size: float) -> List[str]:
    """Wrap on words using approximate glyph widths rather than character count."""
    words = paragraph.split()
    if not words:
        return []
    lines = []
    current = words[0]
    for word in words[1:]:
        candidate = f"{current} {word}"
        if _ea_text_width(candidate, font_size) <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


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


def _colorref_to_css(colorref: int, fallback: Optional[str] = None) -> Optional[str]:
    """Convert an EA Windows COLORREF (0x00BBGGRR) to CSS RGB."""
    if colorref < 0:
        return fallback
    r = colorref & 0xFF
    g = (colorref >> 8) & 0xFF
    b = (colorref >> 16) & 0xFF
    return f"#{r:02x}{g:02x}{b:02x}"


def _node_background(node: NativeDiagramNode, style) -> str:
    """Use an explicit EA fill, then a stereotype fill, then the default."""
    ea_stereotype_fills = (
        {
            "InformationElement": "#66b2e4",
            "DataElement": "#ef7d00",
            "idlStruct": "#ef7d00",
            "idlUnion": "#ef7d00",
            "idlTypedef": "#ef7d00",
            "ResourceArchitecture": "#ef7d00",
            "ResourceRole": "#ff9b37",
            "ResourceArtifact": "#ef7d00",
            "ResourceInterface": "#ef7d00",
            "ResourceConstraint": "#ef7d00",
            "System": "#ef7d00",
            "Standard": "#ffd618",
        }
        if style.ea_detail_nodes
        else {}
    )
    fallback = style.stereotype_bg_colors.get(
        node.stereotype, ea_stereotype_fills.get(node.stereotype, style.node_bg_color)
    )
    if style.respect_ea_colors:
        return _colorref_to_css(node.style.background_color, fallback)
    return fallback


def _compact_label_lines(name: str, width: float, height: float, style, has_context: bool) -> Tuple[int, List[str]]:
    """Fit a class name into its EA box, preferring CamelCase break points."""
    parts = re.findall(r"[A-Z]+(?=[A-Z][a-z]|$)|[A-Z]?[a-z]+|\d+|[^A-Za-z\d]+", name)
    usable_h = max(10, height - (22 if has_context else 10))
    for font_size in range(max(8, min(style.font_size, 16)), 7, -1):
        max_chars = max(2, int((width - 12) / (font_size * 0.58)))
        lines: List[str] = []
        current = ""
        for part in parts:
            while part:
                room = max_chars - len(current)
                if room <= 0:
                    lines.append(current)
                    current = ""
                    room = max_chars
                if len(part) <= room:
                    current += part
                    part = ""
                else:
                    if current:
                        lines.append(current)
                        current = ""
                    else:
                        lines.append(part[:max_chars])
                        part = part[max_chars:]
        if current:
            lines.append(current)
        if len(lines) * font_size * 1.2 <= usable_h:
            return font_size, lines or [name]
    return 8, lines or [name]


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
    waypoints: Optional[List[Tuple[float, float]]] = None,
) -> Tuple[Tuple[float, float], Tuple[float, float]]:
    """
    Compute the start (on source border) and end (on target border) of a
    connector line.

    EA stores endpoint offsets from each node centre. Some offsets specify
    only the coordinate *along* a side (the other coordinate is zero or near
    zero). In that case, project the point onto the side facing the next bend
    or other node. With no offset, clip the centre-to-centre ray as before.
    """
    scx, scy = _node_center(src)
    tcx, tcy = _node_center(tgt)
    _, _, sw, sh = _ea_to_svg(src)
    _, _, tw, th = _ea_to_svg(tgt)

    first_target = waypoints[0] if waypoints else (tcx, tcy)
    last_source = waypoints[-1] if waypoints else (scx, scy)

    def anchored(node, cx, cy, width, height, ox, oy, toward):
        if (ox is None and oy is None) or (abs(ox or 0) <= 1 and abs(oy or 0) <= 1):
            dx, dy = toward[0] - cx, toward[1] - cy
            return _clip_to_rect(cx, cy, width, height, dx, dy)

        candidate = (cx + (ox or 0), cy - (oy or 0))
        left, top, _, _ = _ea_to_svg(node)
        right, bottom = left + width, top + height
        distances = (
            abs(candidate[0] - left),
            abs(candidate[0] - right),
            abs(candidate[1] - top),
            abs(candidate[1] - bottom),
        )
        if min(distances) <= 3 and left - 3 <= candidate[0] <= right + 3 and top - 3 <= candidate[1] <= bottom + 3:
            return candidate

        dx, dy = toward[0] - cx, toward[1] - cy
        if abs(dx / max(width, 1)) >= abs(dy / max(height, 1)):
            return (right if dx >= 0 else left, min(max(candidate[1], top), bottom))
        return (min(max(candidate[0], left), right), bottom if dy >= 0 else top)

    p1 = anchored(src, scx, scy, sw, sh, sx, sy, first_target)
    p2 = anchored(tgt, tcx, tcy, tw, th, ex, ey, last_source)

    return p1, p2


def _waypoints_svg(conn: NativeDiagramConnector) -> List[Tuple[float, float]]:
    """Convert stored waypoints to SVG coordinate space."""
    return [(float(wp[0]), float(-wp[1])) for wp in conn.geometry.waypoints]


def _bend_edge_point(node: NativeDiagramNode, bend: Tuple[float, float]) -> Optional[Tuple[float, float]]:
    """Continue an orthogonal bend to the nearest side of its class box."""
    x, y, width, height = _ea_to_svg(node)
    bx, by = bend
    if x <= bx <= x + width:
        if by < y:
            return bx, y
        if by > y + height:
            return bx, y + height
    if y <= by <= y + height:
        if bx < x:
            return x, by
        if bx > x + width:
            return x + width, by
    return None


def _diamond_anchor(node: NativeDiagramNode, toward: Tuple[float, float]) -> Tuple[float, float]:
    """Attach an activity flow to a decision/merge diamond's actual vertex."""
    x, y, width, height = _ea_to_svg(node)
    cx, cy = x + width / 2, y + height / 2
    dx, dy = toward[0] - cx, toward[1] - cy
    if abs(dx / width) >= abs(dy / height):
        return (x + width if dx >= 0 else x, cy)
    return (cx, y + height if dy >= 0 else y)


def _single_stale_bend(
    src: NativeDiagramNode,
    tgt: NativeDiagramNode,
    waypoints: List[Tuple[float, float]],
) -> bool:
    """A lone point far outside both nodes is likely an obsolete EA Path."""
    if len(waypoints) != 1:
        return False
    sx, sy, sw, sh = _ea_to_svg(src)
    tx, ty, tw, th = _ea_to_svg(tgt)
    left, right = min(sx, tx), max(sx + sw, tx + tw)
    top, bottom = min(sy, ty), max(sy + sh, ty + th)
    bx, by = waypoints[0]
    return max(left - bx, bx - right, top - by, by - bottom) > 75


def _ea_straight_route(
    src: NativeDiagramNode,
    tgt: NativeDiagramNode,
    conn: NativeDiagramConnector,
    waypoints: List[Tuple[float, float]],
) -> Optional[List[Tuple[float, float]]]:
    """Use EA's horizontal/vertical EDGE routes when the boxes overlap.

    EA may retain obsolete Path points after a connector becomes straight.
    In that case its export follows the EDGE mode and the current boxes, not
    the stored Path. Explicit endpoint offsets still select a position along
    the common edge (notably for tall classes).
    """
    geo = conn.geometry
    has_diamond = src.object_type in ("Decision", "MergeNode") or tgt.object_type in ("Decision", "MergeNode")
    if (
        src.object_id == tgt.object_id
        or has_diamond
        and not (geo.edge_style == 4 and _single_stale_bend(src, tgt, waypoints))
        or geo.edge_style not in (2, 3, 4)
        or conn.source_feature_guid
        or conn.target_feature_guid
    ):
        return None
    sx, sy, sw, sh = _ea_to_svg(src)
    tx, ty, tw, th = _ea_to_svg(tgt)
    scx, scy = sx + sw / 2, sy + sh / 2
    tcx, tcy = tx + tw / 2, ty + th / 2
    overlap_y = (max(sy, ty), min(sy + sh, ty + th))
    overlap_x = (max(sx, tx), min(sx + sw, tx + tw))

    both_centres_share_row = overlap_y[0] <= scy <= overlap_y[1] and overlap_y[0] <= tcy <= overlap_y[1]
    explicit_same_row = (
        geo.source_y is not None
        and geo.end_y is not None
        and (geo.source_y != 0 or geo.end_y != 0)
        and abs((scy - geo.source_y) - (tcy - geo.end_y)) <= 3
    )
    wide_target = th >= 2 * sh and ty <= scy <= ty + th
    wide_source = sh >= 2 * th and sy <= tcy <= sy + sh
    horizontal_ea_route = (
        geo.edge_style == 4
        and both_centres_share_row
        or geo.edge_style == 2
        and (explicit_same_row or wide_target or wide_source or abs(scy - tcy) <= 3)
    )
    if horizontal_ea_route and overlap_y[0] <= overlap_y[1] and (sx + sw <= tx or tx + tw <= sx):
        # Keep a meaningful authored bend. A bend outside the shared row is
        # stale for this straight route, as in EA's Object generalization.
        if waypoints and any(overlap_y[0] <= y <= overlap_y[1] for _, y in waypoints):
            return None
        y = scy - geo.source_y if geo.source_y is not None else scy
        if not overlap_y[0] <= y <= overlap_y[1]:
            y = tcy - geo.end_y if geo.end_y is not None else tcy
        y = min(max(y, overlap_y[0]), overlap_y[1])
        return [(sx + sw, y), (tx, y)] if scx < tcx else [(sx, y), (tx + tw, y)]

    vertical_gap = max(ty - (sy + sh), sy - (ty + th), 0)
    explicit_vertical = (
        geo.source_x is not None and geo.end_x is not None and abs((scx + geo.source_x) - (tcx + geo.end_x)) <= 3
    )
    source_vertical = (
        geo.source_x is not None and geo.end_x is None and overlap_x[0] <= scx + geo.source_x <= overlap_x[1]
    )
    if (
        geo.edge_style in (3, 4)
        and overlap_x[0] <= overlap_x[1]
        and (sy + sh <= ty or ty + th <= sy)
        and (
            explicit_vertical
            or source_vertical
            or (vertical_gap > 3 * max(sh, th) and geo.source_x in (None, 0) and geo.end_x in (None, 0))
        )
    ):
        if waypoints and any(overlap_x[0] <= x <= overlap_x[1] for x, _ in waypoints):
            return None
        x = scx + geo.source_x if explicit_vertical or source_vertical else (overlap_x[0] + overlap_x[1]) / 2
        if not overlap_x[0] <= x <= overlap_x[1]:
            x = tcx + geo.end_x if explicit_vertical else x
        x = min(max(x, overlap_x[0]), overlap_x[1])
        return [(x, sy + sh), (x, ty)] if scy < tcy else [(x, sy), (x, ty + th)]
    return None


def _ea_detail_name_lines(node: NativeDiagramNode) -> List[str]:
    """Wrap an EA class name within its stored box using Carlito text widths."""
    display_name = (
        f"{node.display_context}::{node.name}" if node.display_context and not node.foreign_package_path else node.name
    )
    if node.object_type == "Part" and node.classifier_name:
        display_name += f" / {node.classifier_name}"
    width = node.rect_right - node.rect_left
    # EA wraps against the actual Carlito bold text width; our glyph estimate
    # is slightly narrow, so leave the measured margin seen in EA exports.
    max_width = max(10, (width - 10) / 1.055)
    lines = []
    for paragraph in display_name.splitlines() or [display_name]:
        leading = paragraph[: len(paragraph) - len(paragraph.lstrip(" "))]
        wrapped = _wrap_ea_text(paragraph.strip(), max_width - _ea_text_width(leading, 10), 10)
        if wrapped:
            wrapped[0] = leading + wrapped[0]
            lines.extend(wrapped)
    return lines or [display_name]


def _ea_detail_header_height(node: NativeDiagramNode) -> int:
    return (53 if node.parent_name else 37) + 13 * (len(_ea_detail_name_lines(node)) - 1)


def _ea_visible_attributes(node: NativeDiagramNode) -> List[NativeDiagramAttribute]:
    """EA groups ordinary attributes before stereotyped attributes."""
    visibility_key = {"Public": "AttPub", "Private": "AttPri", "Protected": "AttPro", "Package": "AttPkg"}
    attributes = [
        attr
        for attr in node.attributes
        if node.style.extra.get(visibility_key.get(attr.visibility or "Public", "AttPub")) != "0"
    ]
    return sorted(
        attributes,
        key=lambda attr: (
            bool(attr.stereotype),
            attr.stereotype or "",
            attr.inheritance_depth,
            attr.name.casefold(),
            attr.name,
        ),
    )


def _ea_attribute_rows(node: NativeDiagramNode) -> List[Tuple[NativeDiagramAttribute, float]]:
    """Return each attribute and its baseline relative to the node top."""
    baseline = _ea_detail_header_height(node) + 14
    previous_stereotype = None
    previous_owner = None
    rows = []
    for attribute in _ea_visible_attributes(node):
        if attribute.stereotype and attribute.stereotype != previous_stereotype:
            # The stereotype heading is 17 px after the preceding row;
            # its first attribute follows 13 px later.
            baseline += 17
        if attribute.inherited_from and attribute.inherited_from != previous_owner:
            baseline += 16
        rows.append((attribute, baseline))
        baseline += 13
        previous_stereotype = attribute.stereotype
        previous_owner = attribute.inherited_from
    return rows


def _feature_anchor(
    node: NativeDiagramNode,
    guid: Optional[str],
    side: Optional[str],
    toward: Tuple[float, float],
) -> Optional[Tuple[float, float]]:
    """Place an LFSP/LFEP endpoint beside its attached EA attribute row."""
    if not guid or side not in ("L", "R"):
        return None
    for attribute, baseline in _ea_attribute_rows(node):
        if attribute.ea_guid == guid:
            x, y, width, height = _ea_to_svg(node)
            row_y = y + min(height - 8, baseline - 4)
            # L/R identifies EA's feature label side. The connector itself
            # leaves the class border facing the other element.
            facing_right = toward[0] > x + width / 2
            return (x + width if facing_right else x, row_y)
    return None


def _polyline_midpoint(points: List[Tuple[float, float]]) -> Tuple[float, float]:
    """Return the point halfway along a routed connector's visible length."""
    lengths = [math.dist(a, b) for a, b in zip(points, points[1:])]
    remaining = sum(lengths) / 2
    for (a, b), length in zip(zip(points, points[1:]), lengths):
        if remaining <= length and length:
            fraction = remaining / length
            return (a[0] + (b[0] - a[0]) * fraction, a[1] + (b[1] - a[1]) * fraction)
        remaining -= length
    return points[0]


# ---------------------------------------------------------------------------
# Sequence diagram helpers
# ---------------------------------------------------------------------------


def _render_lifeline(
    parent: ET.Element,
    node: NativeDiagramNode,
    style,
    parent_node: Optional[NativeDiagramNode] = None,
) -> None:
    """Render a sequence-diagram lifeline (head box + dashed vertical line)."""
    x, y, w, h = _ea_to_svg(node)
    cx = x + w / 2

    head_h = min(LIFELINE_HEAD_H, h)
    line_bot = y + h
    if parent_node is not None:
        _, parent_y, _, _ = _ea_to_svg(parent_node)
        y = parent_y + LIFELINE_HEAD_H
        head_h = min(25, line_bot - y)
    bg = _colorref_to_css(node.style.background_color, style.node_header_color)
    border = _colorref_to_css(
        node.style.line_color,
        "#9a8484" if style.ea_detail_nodes and style.respect_ea_colors else style.node_border_color,
    )

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

    # EA sequence heads display the role and classifier as one grey label.
    name_y = y + head_h - PADDING_Y
    if style.ea_detail_nodes:
        label = node.name + (f": {node.classifier_name}" if node.classifier_name else "")
        for index, line in enumerate(_wrap_ea_text(label, w - 12, 10)):
            # EA positions a run from its estimated width.  Centring with SVG
            # text-anchor shifts it when the viewer has different font metrics.
            ET.SubElement(
                g,
                "text",
                x=str(round(cx - _ea_text_width(line, 10) / 2)),
                y=str(y + 13 + index * 13),
                **{
                    "font-family": style.font_family,
                    "font-size": "10",
                    "fill": "#595959" if style.respect_ea_colors else style.node_header_text_color,
                },
            ).text = line
    else:
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
    ET.SubElement(
        g,
        "line",
        x1=str(cx),
        y1=str(line_top),
        x2=str(cx),
        y2=str(line_bot),
        stroke=border,
        **{"stroke-width": "1", "stroke-dasharray": "6,3" if style.ea_detail_nodes else "6,4"},
    )


def _render_interaction_fragment(parent: ET.Element, node: NativeDiagramNode, style) -> None:
    """Render a UML CombinedFragment (alt/opt/loop) box with keyword tab."""
    x, y, w, h = _ea_to_svg(node)
    border = _colorref_to_css(node.style.line_color, "#9a8484") if style.respect_ea_colors else style.node_border_color

    g = ET.SubElement(parent, "g", **{"class": "fragment", "data-object-id": str(node.object_id)})

    # EA puts a subtle lower-right frame shadow behind the one-pixel border.
    if style.respect_ea_colors:
        ET.SubElement(
            g,
            "path",
            d=f"M {x + 3},{y + h + 1} L {x + w + 1},{y + h + 1} L {x + w + 1},{y + 3}",
            fill="none",
            stroke="#a3a3a3",
            **{"stroke-width": "2"},
        )
    ET.SubElement(
        g, "rect", x=str(x), y=str(y), width=str(w), height=str(h), fill="none", stroke=border, **{"stroke-width": "1"}
    )

    keyword = {0: "alt", 1: "opt", 4: "loop"}.get(node.ntype, node.stereotype or "alt")
    label = f"{keyword} {node.name}".strip()
    tw = min(w * 0.4, _ea_text_width(label, 10) + 22)
    tab_pts = f"{x},{y} {x},{y + 20} {x + tw - 13},{y + 20} {x + tw},{y + 6} {x + tw},{y}"
    ET.SubElement(
        g,
        "polygon",
        points=tab_pts,
        fill="#f1faed" if style.respect_ea_colors else style.node_header_color,
        stroke=border,
        **{"stroke-width": "1"},
    )
    ET.SubElement(
        g,
        "text",
        x=str(x + 5),
        y=str(y + 13),
        **{
            "font-family": style.font_family,
            "font-size": "10",
            "font-weight": "bold",
            "fill": "#595959" if style.respect_ea_colors else style.node_header_text_color,
        },
    ).text = label
    partition_top = 0
    for index, (guard, size) in enumerate(node.interaction_operands):
        if index:
            ET.SubElement(
                g,
                "line",
                x1=str(x),
                x2=str(x + w),
                y1=str(y + partition_top),
                y2=str(y + partition_top),
                stroke=border,
                **{"stroke-dasharray": "3,3"},
            )
        if guard and guard != "<anonymous>":
            ET.SubElement(
                g,
                "text",
                x=str(x + 5),
                y=str(y + (33 if index == 0 else partition_top + 15)),
                **{
                    "font-family": style.font_family,
                    "font-size": "10",
                    "fill": "#595959" if style.respect_ea_colors else style.node_header_text_color,
                },
            ).text = f"[{guard}]"
        partition_top += size


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

    is_return = (msg.call_type or "").lower() == "reply"
    is_self = msg.source_object_id == msg.target_object_id

    g = ET.SubElement(parent, "g", **{"class": "seq-message", "data-seq": str(msg.seq_no)})

    stroke = "#69738c" if style.ea_detail_nodes and style.respect_ea_colors else style.connector_color
    stroke_w = "1"
    arrow = "url(#arrow-sequence)" if style.ea_detail_nodes and style.respect_ea_colors else "url(#arrow-open)"

    if is_self:
        # Self-referencing loop: small rectangle on the right side
        loop_w = 40
        loop_bottom = y2 if y2 > y1 else y1 + 15
        d = f"M {x1},{y1} L {x1+loop_w},{y1} L {x1+loop_w},{loop_bottom} L {x2},{loop_bottom}"
        ET.SubElement(g, "path", d=d, fill="none", stroke=stroke, **{"stroke-width": stroke_w, "marker-end": arrow})
    else:
        path_attrs: Dict[str, str] = {
            "d": f"M {x1},{y1} L {x2},{y2}",
            "fill": "none",
            "stroke": stroke,
            "stroke-width": stroke_w,
            "marker-end": arrow,
        }
        if is_return:
            path_attrs["stroke-dasharray"] = "6,3"
        ET.SubElement(g, "path", **path_attrs)

    # Activation box at the destination end (arrowhead tip).
    # The actual rectangles are rendered by _render_activation_bars; nothing here.

    # Build label: Name(params) / Name(params): retval
    label = msg.name or ""
    if label and (msg.param_values or style.ea_detail_nodes):
        label += f"({msg.param_values or ''})"
    ret_label = ""
    if msg.return_value:
        ret_label = msg.return_value

    mid_x = (x1 + x2) / 2
    label_y = y1 - (4 if style.ea_detail_nodes else 5)

    if msg.stereotype and not style.ea_detail_nodes:
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
            x=str(x1 + 4 if is_self and style.ea_detail_nodes else mid_x),
            y=str(label_y),
            **{
                "text-anchor": "start" if is_self and style.ea_detail_nodes else "middle",
                "font-family": style.font_family,
                "font-size": str(style.font_size),
                "fill": "#595959" if style.ea_detail_nodes and style.respect_ea_colors else style.node_border_color,
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
        border = _colorref_to_css(
            node.style.line_color,
            "#9a8484" if style.ea_detail_nodes and style.respect_ea_colors else style.node_border_color,
        )
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


def _build_defs(root: ET.Element, style, diagram: NativeDiagram) -> None:
    """Add shared ``<defs>`` (arrow markers) using colours from *style*."""
    defs = ET.SubElement(root, "defs")
    c = "#69738c" if style.ea_detail_nodes and style.respect_ea_colors else style.connector_color
    open_fill = "#faf1ec" if style.ea_detail_nodes and style.respect_ea_colors else style.canvas_bg_color

    # Open chevrons for directed associations and dependencies.
    for marker_id, orientation in (("arrow-open", "auto"), ("arrow-open-start", "auto-start-reverse")):
        marker_size = (16, 11) if style.ea_detail_nodes else (10, 7)
        tip_x = 15 if style.ea_detail_nodes else 9
        mid_y = marker_size[1] / 2
        m = ET.SubElement(
            defs,
            "marker",
            id=marker_id,
            markerWidth=str(marker_size[0]),
            markerHeight=str(marker_size[1]),
            refX=str(tip_x),
            refY=str(mid_y),
            orient=orientation,
        )
        ET.SubElement(
            m,
            "polyline",
            points=f"0,0 {tip_x},{mid_y} 0,{marker_size[1]}",
            fill="none",
            stroke=c,
            **{"stroke-width": "1" if style.ea_detail_nodes else "1.2"},
        )

    sequence_marker = ET.SubElement(
        defs, "marker", id="arrow-sequence", markerWidth="12", markerHeight="8", refX="12", refY="4", orient="auto"
    )
    # EA exports every sequence message head as a closed, filled 12x8 triangle.
    ET.SubElement(
        sequence_marker, "polygon", points="0,0 12,4 0,8", fill="#69738c", stroke="#69738c", **{"stroke-width": "1"}
    )

    # EA's activity-flow head is 16 units long and 12 units wide. Keep its
    # tip at the path endpoint so flows into diamonds meet the actual vertex.
    flow_marker = ET.SubElement(
        defs, "marker", id="arrow-control", markerWidth="16", markerHeight="12", refX="16", refY="6", orient="auto"
    )
    flow_color = style.control_flow_color or c
    ET.SubElement(
        flow_marker, "polygon", points="0,0 16,6 0,12", fill=flow_color, stroke=flow_color, **{"stroke-width": "1"}
    )
    information_marker = ET.SubElement(
        defs,
        "marker",
        id="arrow-information",
        markerWidth="16",
        markerHeight="11",
        refX="15",
        refY="5.5",
        orient="auto",
    )
    ET.SubElement(
        information_marker,
        "polyline",
        points="0,0 15,5.5 0,11",
        fill="none",
        stroke=style.information_flow_color or c,
        **{"stroke-width": "1"},
    )
    state_marker_colors = [("arrow-state", "#69738c")]
    if style.ea_detail_nodes and any(
        conn.connector_type == "StateFlow"
        and (
            conn.style.color >= 0
            and _colorref_to_css(conn.style.color) == "#ff0000"
            or conn.style.color < 0
            and (conn.transition_event or "").startswith("TaskAdminActionEnum.")
            and conn.transition_event != "TaskAdminActionEnum.CANCEL"
        )
        for conn in diagram.connectors
    ):
        state_marker_colors.append(("arrow-state-action", "#ff0000"))
    if style.ea_detail_nodes and any(
        conn.connector_type == "StateFlow"
        and conn.transition_event == "TaskAdminActionEnum.CANCEL"
        and conn.style.color < 0
        for conn in diagram.connectors
    ):
        state_marker_colors.append(("arrow-state-cancel", "#ff4500"))
    for marker_id, color in state_marker_colors:
        marker = ET.SubElement(
            defs, "marker", id=marker_id, markerWidth="10", markerHeight="7", refX="9", refY="3.5", orient="auto"
        )
        ET.SubElement(marker, "polyline", points="0,0 9,3.5 0,7", fill="none", stroke=color, **{"stroke-width": "1"})

    # Hollow triangle (Generalization — points *to* the parent)
    triangle_length = 15 if style.ea_detail_nodes else 9
    triangle_height = 14 if style.ea_detail_nodes else 7
    m2 = ET.SubElement(
        defs,
        "marker",
        id="arrow-generalization",
        markerWidth=str(triangle_length + 1),
        markerHeight=str(triangle_height),
        refX=str(triangle_length),
        refY=str(triangle_height / 2),
        orient="auto",
    )
    ET.SubElement(
        m2,
        "polygon",
        points=f"0,0 {triangle_length},{triangle_height / 2} 0,{triangle_height}",
        fill=open_fill if style.ea_detail_nodes else style.node_bg_color,
        stroke=c,
        **{"stroke-width": "1"},
    )

    # The EA aggregate flags identify which end owns the diamond and whether
    # it is hollow (shared) or filled (composite).
    for marker_id, at_start, filled in (
        ("diamond-open-start", True, False),
        ("diamond-open-end", False, False),
        ("diamond-filled-start", True, True),
        ("diamond-filled-end", False, True),
    ):
        size = 16 if style.ea_detail_nodes else 10
        half_height = 6 if style.ea_detail_nodes else 4
        m = ET.SubElement(
            defs,
            "marker",
            id=marker_id,
            markerWidth=str(size + 2),
            markerHeight=str(half_height * 2),
            refX="0" if at_start else str(size),
            refY=str(half_height),
            orient="auto",
        )
        ET.SubElement(
            m,
            "polygon",
            points=f"0,{half_height} {size / 2},0 {size},{half_height} {size / 2},{half_height * 2}",
            fill=c if filled else open_fill,
            stroke=c,
            **{"stroke-width": "1"},
        )


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
    if style.compact_nodes or style.ea_detail_nodes or node.object_type == "Note":
        return float(node.rect_right - node.rect_left)
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


def _node_min_height(node: NativeDiagramNode, style) -> float:
    stored_height = float(node.rect_top - node.rect_bottom)
    if style.compact_nodes or style.ea_detail_nodes or node.object_type == "Note":
        return stored_height
    return max(stored_height, HEADER_H + ATTR_ROW_H * max(1, len(node.attributes)) + 2 * PADDING_Y)


def _render_ea_detail_node(parent: ET.Element, node: NativeDiagramNode, style) -> None:
    """Render content within EA's stored bounds, including visible notes."""
    x, y, width, height = _ea_to_svg(node)
    fill = _node_background(node, style)
    border = _colorref_to_css(node.style.line_color, "#9a8484") if style.respect_ea_colors else style.node_border_color
    header_text = "#595959" if style.respect_ea_colors else style.node_border_color
    attribute_text = "#66413f" if style.respect_ea_colors else style.node_border_color
    description_text = "#808080" if style.respect_ea_colors else style.node_border_color
    g = ET.SubElement(parent, "g", **{"class": "node-class", "data-object-id": str(node.object_id)})
    ET.SubElement(g, "title").text = node.note_text or node.name
    ET.SubElement(g, "rect", x=str(x), y=str(y), width=str(width), height=str(height), fill=fill, stroke=border)

    if node.object_type == "Part" and node.stereotype == "ResourceRole":
        ET.SubElement(
            g,
            "text",
            x=str(x + width / 2),
            y=str(y + 15),
            **{"text-anchor": "middle", "font-family": style.font_family, "font-size": "9", "fill": "#595959"},
        ).text = "«ResourceRole»"
        label = node.name + (f" / {node.classifier_name}" if node.classifier_name else "")
        lines = textwrap.wrap(label, width=max(8, int((width - 8) / 5.5)))
        for index, line in enumerate(lines):
            ET.SubElement(
                g,
                "text",
                x=str(x + width / 2),
                y=str(y + 30 + index * 12),
                **{
                    "text-anchor": "middle",
                    "font-family": style.font_family,
                    "font-size": "10",
                    "font-weight": "bold",
                    "fill": "#595959",
                },
            ).text = line
        return

    name_lines = _ea_detail_name_lines(node)
    header_height = min(height, _ea_detail_header_height(node))
    attributes = _ea_visible_attributes(node)
    show_note = node.style.extra.get("Notes") not in (None, "0") and bool(node.note_text)
    if attributes or show_note:
        ET.SubElement(
            g, "line", x1=str(x), x2=str(x + width), y1=str(y + header_height), y2=str(y + header_height), stroke=border
        )
    header_shift = 16 if node.parent_name else 0
    if node.parent_name:
        ET.SubElement(
            g,
            "text",
            x=str(x + width / 2),
            y=str(y + 13),
            **{
                "text-anchor": "middle",
                "font-family": style.font_family,
                "font-size": "10",
                "font-style": "italic",
                "fill": header_text,
            },
        ).text = node.parent_name
    if node.stereotype:
        ET.SubElement(
            g,
            "text",
            x=str(x + width / 2),
            y=str(y + 16 + header_shift),
            **{"text-anchor": "middle", "font-family": style.font_family, "font-size": "10", "fill": header_text},
        ).text = f"«{','.join(node.stereotypes) if node.stereotypes else node.stereotype}»"
    name_size = style.font_size
    for index, line in enumerate(name_lines):
        ET.SubElement(
            g,
            "text",
            x=str(x + width / 2),
            y=str(y + min(29 + header_shift + 13 * index, header_height - 5)),
            **{
                "text-anchor": "middle",
                "font-family": style.font_family,
                "font-size": str(name_size),
                "font-weight": "bold",
                "fill": header_text,
            },
        ).text = line

    if node.foreign_package_path:
        parts = node.foreign_package_path.split("::")
        footer_lines = []
        line = "(from "
        for index, part in enumerate(parts):
            segment = part + ("::" if index < len(parts) - 1 else ")")
            if line != "(from " and _ea_text_width(line + segment, 10) > width - 8:
                footer_lines.append(line)
                line = segment
            else:
                line += segment
        footer_lines.append(line)
        for index, line in enumerate(footer_lines):
            ET.SubElement(
                g,
                "text",
                x=str(x + 8),
                y=str(y + height + 15 + 13 * index),
                **{"font-family": style.font_family, "font-size": "10", "font-style": "italic", "fill": header_text},
            ).text = line

    shown_rows = []
    previous_stereotype = None
    previous_owner = None
    for attr, baseline in _ea_attribute_rows(node):
        if baseline > height - 5:
            break
        new_owner = bool(attr.inherited_from and attr.inherited_from != previous_owner)
        if attr.stereotype and attr.stereotype != previous_stereotype:
            ET.SubElement(
                g,
                "text",
                x=str(x + 12),
                y=str(y + baseline - 13 - (16 if new_owner else 0)),
                **{"font-family": style.font_family, "font-size": "10", "fill": header_text},
            ).text = f"«{attr.stereotype}»"
        if new_owner:
            ET.SubElement(
                g,
                "text",
                x=str(x + 5),
                y=str(y + baseline - 13),
                **{"font-family": style.font_family, "font-size": "10", "font-style": "italic", "fill": header_text},
            ).text = f"::{attr.inherited_from}"
        bounds = (
            f" [{attr.lower_bound or ''}..{attr.upper_bound or ''}]"
            if (attr.lower_bound or attr.upper_bound) and (attr.lower_bound, attr.upper_bound) != ("1", "1")
            else ""
        )
        label = f"{attr.name}: {attr.type}{bounds}"
        visibility_symbol = {"Private": "-", "Protected": "#", "Package": "~"}.get(attr.visibility, "+")
        ET.SubElement(
            g,
            "text",
            x=str(x + 5),
            y=str(y + baseline),
            **{"font-family": style.font_family, "font-size": str(style.attr_font_size), "fill": attribute_text},
        ).text = visibility_symbol + " "
        ET.SubElement(
            g,
            "text",
            x=str(x + 22),
            y=str(y + baseline),
            **{"font-family": style.font_family, "font-size": str(style.attr_font_size), "fill": attribute_text},
        ).text = label
        shown_rows.append(baseline)
        previous_stereotype = attr.stereotype
        previous_owner = attr.inherited_from

    if show_note:
        note_top = y + (shown_rows[-1] + 8 if shown_rows else header_height)
        if note_top < y + height - 8:
            ET.SubElement(g, "line", x1=str(x), x2=str(x + width), y1=str(note_top), y2=str(note_top), stroke=border)
            raw = node.note_text or ""
            note_height = y + height - note_top
            font_size = style.note_font_size
            lines = [line for para in _plain_note_lines(raw) for line in _wrap_ea_text(para, width - 15, font_size)]
            max_lines = max(1, int((note_height - 16) / 13))
            if len(lines) > max_lines:
                lines = lines[:max_lines]
                lines[-1] = lines[-1].rstrip(". ") + "…"
            for index, line in enumerate(lines):
                ET.SubElement(
                    g,
                    "text",
                    x=str(x + 10),
                    y=str(note_top + 27 + index * 13),
                    **{"font-family": style.font_family, "font-size": str(font_size), "fill": description_text},
                ).text = line


def _render_class_node(parent: ET.Element, node: NativeDiagramNode, style) -> None:
    """Render a Class or Part node.  The header links to the class; each
    attribute row links to the type of that attribute (when resolvable)."""
    x, y, w, h = _ea_to_svg(node)
    if style.ea_detail_nodes:
        _render_ea_detail_node(parent, node, style)
        return
    if style.compact_nodes:
        g = ET.SubElement(parent, "g", **{"class": "node-class", "data-object-id": str(node.object_id)})
        ET.SubElement(g, "title").text = f"{node.name} ({node.stereotype or node.object_type})"
        ET.SubElement(
            g,
            "rect",
            x=str(x),
            y=str(y),
            width=str(w),
            height=str(h),
            rx="7",
            fill=_node_background(node, style),
            stroke=style.node_border_color,
            **{"stroke-width": str(style.node_border_width)},
        )
        name_font_size, lines = _compact_label_lines(node.name, w, h, style, bool(node.display_context))
        line_h = name_font_size * 1.2
        label_mid = y + (h - (18 if node.display_context else 0)) / 2
        first_y = label_mid - (len(lines) - 1) * line_h / 2 + name_font_size * 0.35
        for index, line in enumerate(lines):
            ET.SubElement(
                g,
                "text",
                x=str(x + w / 2),
                y=str(first_y + index * line_h),
                **{
                    "text-anchor": "middle",
                    "font-family": style.font_family,
                    "font-size": str(name_font_size),
                    "font-weight": "bold",
                    "fill": style.node_border_color,
                },
            ).text = line
        if node.display_context:
            ET.SubElement(
                g,
                "text",
                x=str(x + w / 2),
                y=str(y + h / 2 + 15),
                **{
                    "text-anchor": "middle",
                    "font-family": style.font_family,
                    "font-size": str(style.attr_font_size),
                    "fill": style.note_text_color,
                },
            ).text = node.display_context
        return
    w = max(w, _node_min_width(node, style))
    h = max(h, _node_min_height(node, style))
    # Per-node colour overrides from objectstyle take precedence over config
    bg = _node_background(node, style)
    # Parts inside composite diagrams get a slightly lighter fill by default
    if node.object_type == "Part" and node.style.background_color < 0:
        bg = style.part_bg_color
    border = (
        _colorref_to_css(node.style.line_color, style.node_border_color)
        if style.respect_ea_colors
        else style.node_border_color
    )
    lw = node.style.line_width if node.style.line_width > 0 else style.node_border_width

    g = ET.SubElement(parent, "g", **{"class": "node-class", "data-object-id": str(node.object_id)})

    # Body rectangle (rendered before header so header border paints on top).
    # Expand too-small EA boxes so their labels fit within the node border.
    body_y = y + HEADER_H
    body_h = h - HEADER_H
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

    # Attribute labels now fit the measured node width and height.
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
    """Render Note text as portable SVG text inside a dog-eared box."""
    x, y, w, h = _ea_to_svg(node)
    f = NOTE_FOLD
    note_bg = (
        _colorref_to_css(node.style.background_color, style.note_bg_color)
        if style.respect_ea_colors
        else style.note_bg_color
    )
    note_border = "#658a99" if style.respect_ea_colors else style.note_border_color
    fold_fill = "#dcdcdc" if style.respect_ea_colors else "#fff9c4"

    g = ET.SubElement(parent, "g", **{"class": "node-note", "data-object-id": str(node.object_id)})

    # Dog-eared polygon
    points = f"{x},{y} {x+w-f},{y} {x+w},{y+f} {x+w},{y+h} {x},{y+h}"
    ET.SubElement(g, "polygon", points=points, fill=note_bg, stroke=note_border, **{"stroke-width": "1"})

    # Fold triangle
    fold_pts = f"{x+w-f},{y} {x+w},{y+f} {x+w-f},{y+f}"
    ET.SubElement(g, "polygon", points=fold_pts, fill=fold_fill, stroke=note_border, **{"stroke-width": "1"})

    raw = node.note_text or node.name or ""
    note_font = node.style.extra.get("font") or style.font_family
    if style.ea_detail_nodes and note_font.lower() == "calibri":
        # EA's SVG export substitutes Carlito for its Calibri note font.
        note_font = style.font_family
    is_code = note_font.lower() == "courier new"
    font_size = (
        10
        if is_code and style.ea_detail_nodes
        else round(node.style.font_size / 7.5)
        if node.style.font_size > 0
        else style.note_font_size
    )
    line_height = 12 if is_code and style.ea_detail_nodes else 14 if font_size >= 12 else 13
    first_baseline = 25 if font_size >= 12 else 24
    if is_code and style.ea_detail_nodes:
        # EA keeps the source's line breaks and indentation in code notes.
        lines = [line.rstrip() for line in unescape(re.sub(r"<[^>]*>", "", raw)).splitlines()]
    else:
        lines = [line for para in _plain_note_lines(raw) for line in _wrap_ea_text(para, w - 10, font_size)]
    max_lines = max(1, int((h - first_baseline) / line_height) + 1)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1].rstrip(". ") + "…"
    ET.SubElement(g, "title").text = "\n".join(_plain_note_lines(raw))
    for index, line in enumerate(lines):
        ET.SubElement(
            g,
            "text",
            x=str(x + 5),
            y=str(y + first_baseline + index * line_height),
            **{
                "font-family": note_font,
                "font-size": str(font_size),
                "fill": style.note_text_color,
                "xml:space": "preserve" if is_code else "default",
            },
        ).text = line


def _render_statechart_node(parent: ET.Element, node: NativeDiagramNode, diagram_name: str, style) -> None:
    """Render EA Statechart frames, rounded states, and initial/final nodes."""
    x, y, width, height = _ea_to_svg(node)
    border = _colorref_to_css(node.style.line_color, "#9a8484") if style.respect_ea_colors else style.node_border_color
    fill = _colorref_to_css(node.style.background_color, "#f5edd8") if style.respect_ea_colors else style.node_bg_color
    label_color = "#595959" if style.respect_ea_colors else style.node_border_color
    group = ET.SubElement(parent, "g", **{"class": "node-state", "data-object-id": str(node.object_id)})
    if node.object_type == "StateMachine":
        ET.SubElement(
            group,
            "rect",
            x=str(x),
            y=str(y),
            width=str(width),
            height=str(height),
            fill="none",
            stroke="#b4b4b4",
            **{"stroke-width": "2"},
        )
        ET.SubElement(
            group, "rect", x=str(x), y=str(y), width=str(width), height=str(height), fill="none", stroke=border
        )
        tab_width = min(width / 2, max(80, len(f"stm {diagram_name}") * 4.2 + 22))
        tab = f"{x},{y + 20} {x + tab_width - 13},{y + 20} {x + tab_width},{y + 6} {x + tab_width},{y} {x},{y}"
        ET.SubElement(group, "polygon", points=tab, fill="#ffffff", stroke=border)
        ET.SubElement(
            group,
            "text",
            x=str(x + 7),
            y=str(y + 13),
            **{"font-family": style.font_family, "font-size": "10", "fill": label_color},
        ).text = f"stm {diagram_name}"
    elif node.object_type == "StateNode":
        cx, cy = x + width / 2, y + height / 2
        is_initial = node.ntype == 3 or (node.name or "").lower() == "initial"
        ET.SubElement(
            group,
            "ellipse",
            cx=str(cx),
            cy=str(cy),
            rx=str(width / 2),
            ry=str(height / 2),
            fill=border if is_initial else "#ffffff",
            stroke=border,
        )
        if not is_initial:
            ET.SubElement(group, "ellipse", cx=str(cx), cy=str(cy), rx="6", ry="6", fill="#bec661")
        if node.name:
            ET.SubElement(
                group,
                "text",
                x=str(cx),
                y=str(y + height + 20),
                **{"text-anchor": "middle", "font-family": style.font_family, "font-size": "10", "fill": label_color},
            ).text = node.name
    elif node.object_type == "Text":
        if node.legend_entries:
            ET.SubElement(
                group,
                "rect",
                x=str(x),
                y=str(y),
                width=str(width),
                height=str(height),
                rx="3",
                fill=node.legend_background_color or "#e2e0dd",
                stroke="#ffffff",
            )
            color = node.legend_text_color or "#003060"
            ET.SubElement(
                group,
                "text",
                x=str(x + 20),
                y=str(y + 19),
                **{
                    "font-family": style.font_family,
                    "font-size": "16",
                    "font-weight": "bold",
                    "fill": color,
                    "textLength": str(max(20, width - 40)),
                    "lengthAdjust": "spacingAndGlyphs",
                },
            ).text = node.name or node.legend_title
            for index, (label, swatch_color) in enumerate(node.legend_entries):
                row_y = y + 37 + index * 17
                ET.SubElement(
                    group, "line", x1=str(x + 10), x2=str(x + 26), y1=str(row_y), y2=str(row_y), stroke=swatch_color
                )
                ET.SubElement(
                    group,
                    "text",
                    x=str(x + 31),
                    y=str(row_y + 4),
                    **{"font-family": style.font_family, "font-size": "10", "fill": color},
                ).text = label
        elif node.name:
            ET.SubElement(
                group,
                "text",
                x=str(x + 10),
                y=str(y + 13),
                **{"font-family": style.font_family, "font-size": "10", "fill": label_color},
            ).text = node.name
    else:
        ET.SubElement(
            group, "rect", x=str(x), y=str(y), width=str(width), height=str(height), rx="20", fill=fill, stroke=border
        )
        for index, line in enumerate((node.name or "").splitlines()):
            ET.SubElement(
                group,
                "text",
                x=str(x + width / 2),
                y=str(y + 13 + index * 13),
                **{
                    "text-anchor": "middle",
                    "font-family": style.font_family,
                    "font-size": "10",
                    "font-weight": "bold",
                    "fill": label_color,
                },
            ).text = line
        if node.note_text and node.style.extra.get("Notes") not in (None, "0"):
            ET.SubElement(group, "line", x1=str(x), x2=str(x + width), y1=str(y + 21), y2=str(y + 21), stroke=border)
            raw = unescape(re.sub(r"<[^>]*>", "", node.note_text)).strip()
            max_chars = max(8, int((width - 16) / 4))
            lines = textwrap.wrap(raw, width=max_chars)
            max_lines = max(1, int((height - 48) / 13) + 1)
            if len(lines) > max_lines:
                lines = lines[:max_lines]
                lines[-1] = lines[-1].rstrip(". ") + "…"
            for index, line in enumerate(lines[:max_lines]):
                ET.SubElement(
                    group,
                    "text",
                    x=str(x + 10),
                    y=str(y + 48 + index * 13),
                    **{"font-family": style.font_family, "font-size": "10", "fill": "#808080"},
                ).text = line


def _render_activity_node(parent: ET.Element, node: NativeDiagramNode, style) -> None:
    """Render the UML activity symbols used by EA's P4 diagrams."""
    x, y, width, height = _ea_to_svg(node)
    activity_border = "#808080" if node.object_type in ("Activity", "StateNode") else "#9a8484"
    border = (
        _colorref_to_css(node.style.line_color, activity_border) if style.respect_ea_colors else style.node_border_color
    )
    text_color = "#595959" if style.respect_ea_colors else style.node_border_color
    fill = _node_background(node, style)
    group = ET.SubElement(parent, "g", **{"class": "node-activity", "data-object-id": str(node.object_id)})
    kind = node.object_type
    if kind == "Text":
        if node.legend_title:
            ET.SubElement(
                group,
                "text",
                x=str(x + 10),
                y=str(y + 25),
                **{"font-family": style.font_family, "font-size": "16", "font-weight": "bold", "fill": text_color},
            ).text = node.legend_title
        for index, (label, color) in enumerate(node.legend_entries):
            row_y = y + 40 + index * 19
            ET.SubElement(group, "rect", x=str(x + 1), y=str(row_y), width="17", height="17", fill=color, stroke=border)
            ET.SubElement(
                group,
                "text",
                x=str(x + 22),
                y=str(row_y + 12),
                **{"font-family": style.font_family, "font-size": "10", "fill": text_color},
            ).text = label
        return
    if kind in ("Activity", "Action"):
        ET.SubElement(
            group,
            "rect",
            x=str(x),
            y=str(y),
            width=str(width),
            height=str(height),
            rx="13" if kind == "Activity" else "11",
            fill=fill,
            stroke=border,
        )
        if kind == "Action" and width >= 24 and height >= 26:
            right, bottom = x + width, y + height
            icon = (
                f"M {right - 11},{bottom - 20} L {right - 11},{bottom - 5} "
                f"M {right - 7},{bottom - 5} L {right - 7},{bottom - 13} "
                f"L {right - 15},{bottom - 13} L {right - 15},{bottom - 5}"
            )
            ET.SubElement(group, "path", d=icon, fill="none", stroke=border)
    elif kind in ("Decision", "MergeNode"):
        cx, cy = x + width / 2, y + height / 2
        ET.SubElement(
            group, "polygon", points=f"{cx},{y} {x + width},{cy} {cx},{y + height} {x},{cy}", fill=fill, stroke=border
        )
    elif kind == "StateNode":
        cx, cy = x + width / 2, y + height / 2
        initial = node.ntype != 101
        ET.SubElement(
            group,
            "ellipse",
            cx=str(cx),
            cy=str(cy),
            rx=str(width / 2),
            ry=str(height / 2),
            fill=border if initial else fill,
            stroke=border,
        )
        if not initial:
            ET.SubElement(group, "ellipse", cx=str(cx), cy=str(cy), rx="4", ry="4", fill=border)
    elif kind in ("Synchronization", "ForkNode", "JoinNode"):
        ET.SubElement(
            group, "rect", x=str(x), y=str(y), width=str(width), height=str(height), fill=border, stroke=border
        )
    elif kind == "ActionPin":
        ET.SubElement(group, "rect", x=str(x), y=str(y), width=str(width), height=str(height), fill=fill, stroke=border)
    else:
        _render_class_node(parent, node, style)
        parent.remove(group)
        return

    if not node.name:
        return
    if kind in ("Decision", "MergeNode"):
        label_style = node.style.extra.get("LBL", "")
        saved = dict(re.findall(r"(?:^|:)(CX|CY|OX|OY)=(-?\d+)", label_style))
        if style.ea_detail_nodes and kind == "Decision" and all(key in saved for key in ("CX", "CY", "OX", "OY")):
            # LBL's OX/OY is the label box's top-left offset from the
            # diamond's top-left; CX/CY is that box's stored size.
            label_x = x + int(saved["OX"])
            label_y = y + int(saved["OY"])
            label_width = int(saved["CX"])
            for index, line in enumerate(_wrap_ea_text(node.name, label_width + 3, 10)):
                ET.SubElement(
                    group,
                    "text",
                    x=str(label_x + (label_width - _ea_text_width(line, 10)) / 2),
                    y=str(label_y + 10 + index * 13),
                    **{"font-family": style.font_family, "font-size": "10", "fill": text_color},
                ).text = line
            return
        lines = textwrap.wrap(node.name, width=23)
        for index, line in enumerate(lines):
            ET.SubElement(
                group,
                "text",
                x=str(x - 5),
                y=str(y + height / 2 + (index - (len(lines) - 1) / 2) * 12 + 3),
                **{"text-anchor": "end", "font-family": style.font_family, "font-size": "10", "fill": text_color},
            ).text = line
        return
    if kind not in ("Activity", "Action"):
        return
    raw_lines = re.split(r"\r?\n", node.name)
    lines = [part for line in raw_lines for part in _wrap_ea_text(line, width - 20, 10)]
    line_height = 13
    start = y + 16
    for index, line in enumerate(lines):
        ET.SubElement(
            group,
            "text",
            x=str(x + width / 2),
            y=str(start + index * line_height),
            **{
                "text-anchor": "middle",
                "font-family": style.font_family,
                "font-size": "10",
                "font-weight": "bold",
                "fill": text_color,
            },
        ).text = line


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
    wpts = _waypoints_svg(conn)
    stale_bend = False
    if (
        conn.connector_type in ("ControlFlow", "ObjectFlow")
        and geo.edge_style == 4
        and len(wpts) == 2
        and abs(wpts[0][0] - wpts[1][0]) <= 1
    ):
        source_centre = _node_center(src)
        target_centre = _node_center(tgt)
        route_y = source_centre[1]
        if (
            abs(route_y - target_centre[1]) <= 5
            and min(wpts[0][1], wpts[1][1]) < route_y < max(wpts[0][1], wpts[1][1])
            and max(abs(point[1] - route_y) for point in wpts) < 35
        ):
            # EA ignores a short saved vertical detour when both endpoints
            # still lie on one horizontal activity-flow route.
            wpts = []
    if (
        len(wpts) == 1
        and geo.edge_style == 1
        and conn.connector_type == "Generalization"
        and max(src.rect_left, tgt.rect_left) <= min(src.rect_right, tgt.rect_right)
    ):
        wpts = []
    if len(wpts) == 1 and conn.connector_type in ("Abstraction", "Generalization", "Realisation"):
        sx, sy, sw, sh = _ea_to_svg(src)
        tx, ty, tw, th = _ea_to_svg(tgt)
        left, right = min(sx, tx), max(sx + sw, tx + tw)
        top, bottom = min(sy, ty), max(sy + sh, ty + th)
        bx, by = wpts[0]
        if max(left - bx, bx - right, top - by, by - bottom) > 75:
            # EA can retain an old bend after the classes are moved. It then
            # exports an automatic route and ignores that lone Path point.
            wpts = []
            stale_bend = True
    p1, p2 = _edge_points(src, tgt, geo.source_x, geo.source_y, geo.end_x, geo.end_y, wpts)
    if wpts and geo.edge_style in (1, 3, 4):
        p1 = _bend_edge_point(src, wpts[0]) or p1
        p2 = _bend_edge_point(tgt, wpts[-1]) or p2
    p1 = _feature_anchor(src, conn.source_feature_guid, conn.source_feature_side, _node_center(tgt)) or p1
    p2 = _feature_anchor(tgt, conn.target_feature_guid, conn.target_feature_side, _node_center(src)) or p2
    source_x, source_y, source_width, source_height = _ea_to_svg(src)
    target_x, target_y, target_width, target_height = _ea_to_svg(tgt)
    horizontally_separate = source_x + source_width <= target_x or target_x + target_width <= source_x
    implicit_property = (
        conn.connector_type == "Association"
        and not wpts
        and not conn.source_feature_guid
        and not conn.target_feature_guid
        and bool(conn.target_role)
        and horizontally_separate
        and max(source_y, target_y) <= min(source_y + source_height, target_y + target_height)
        and all(
            offset is None
            for offset in (
                geo.source_x,
                geo.source_y,
                geo.end_x,
                geo.end_y,
            )
        )
    )
    if implicit_property:
        # Some EA property associations do not carry LFSP.  Their role names
        # still identify the source attribute, and EA attaches at that row.
        matches = [attr for attr in src.attributes if attr.name == conn.target_role]
        if matches:
            p1 = _feature_anchor(src, matches[0].ea_guid, "R", _node_center(tgt)) or p1
            target_rows = _ea_attribute_rows(tgt)
            if target_rows:
                tx, ty, tw, _ = _ea_to_svg(tgt)
                p2 = (tx if _node_center(src)[0] < tx + tw / 2 else tx + tw, ty + target_rows[0][1] - 4)
    if (
        conn.source_feature_guid
        and not conn.target_feature_guid
        and geo.end_x not in (None, 0)
        and p1[1] < _ea_to_svg(tgt)[1]
    ):
        # For a property link approaching a class from above, EA uses the
        # target's top edge and its saved horizontal endpoint displacement.
        tx, ty, tw, _ = _ea_to_svg(tgt)
        p2 = (min(max(tx + 3, _node_center(tgt)[0] - geo.end_x - 3), tx + tw - 3), ty)
    if src.object_type in ("Decision", "MergeNode"):
        p1 = _diamond_anchor(src, wpts[0] if wpts else _node_center(tgt))
    if tgt.object_type in ("Decision", "MergeNode"):
        p2 = _diamond_anchor(tgt, wpts[-1] if wpts else _node_center(src))

    ctype = conn.connector_type or "Association"
    is_note_link = ctype == "NoteLink"
    is_generalisation = ctype == "Generalization"
    is_aggregation = ctype in ("Aggregation", "Composition")
    sx, sy, sw, sh = _ea_to_svg(src)
    tx, ty, tw, th = _ea_to_svg(tgt)
    if src.object_type == "MergeNode" and tgt.object_type == "Synchronization":
        diamond_x = sx + sw / 2
        if tx <= diamond_x <= tx + tw and ty >= sy + sh:
            p1 = (diamond_x, sy + sh)
            p2 = (diamond_x, ty)

    if ctype == "StateFlow" and not wpts and src.object_type == "State":
        scx, scy = _node_center(src)
        tcx, tcy = _node_center(tgt)
        dx, dy = tcx - scx, tcy - scy
        if tgt.object_type == "StateNode" and abs(dx) > 140:
            # EA routes transitions into a final node from the visible state
            # boundary. The saved SX/SY can instead point to a stale location
            # in the middle of that state.
            p1 = _clip_to_rect(scx, scy, sw, sh, dx, dy)
        elif (
            tgt.object_type == "State"
            and src.note_text
            and tgt.note_text
            and abs(dx) > 80
            and abs(dy) > 70
            and geo.edge_style in (1, 2, 4)
        ):
            # For diagonal leaf-state transitions EA chooses the corners
            # facing the other state, rather than the stored centre offsets.
            p1 = _clip_to_rect(scx, scy, sw, sh, dx, dy)
            p2 = _clip_to_rect(tcx, tcy, tw, th, -dx, -dy)
            if geo.edge_style == 1 and dx < 0 and dy < 0:
                # EA's automatic upward-left route leaves the top of the
                # lower state and enters the right of the upper state.
                p1 = (sx + sw / 3, sy)
                p2 = (tx + tw, ty + th * 0.75)
            elif geo.edge_style == 4 and dx < 0 and dy > 0:
                # Direct down-left transitions attach near opposite rounded
                # corners of the two state boxes.
                p1 = (sx, sy + sh - 8)
                p2 = (tx + tw * 0.63, ty)
            elif geo.edge_style == 2 and dx > 0 and dy < 0:
                # EA's upward-right orthogonal mode clips this diagonal at
                # the upper-right and lower-left rounded corners.
                p1 = (sx + sw, sy + 13)
                p2 = (tx + tw * 0.17, ty + th)

    # A feature link must retain its attribute endpoint even when EA's edge
    # mode would otherwise allow a centre-to-centre straight route.
    implicit_property = implicit_property and any(attr.name == conn.target_role for attr in src.attributes)
    straight = (
        None
        if conn.source_feature_guid or conn.target_feature_guid or implicit_property
        else _ea_straight_route(src, tgt, conn, wpts)
    )
    same_bounds = _ea_to_svg(src) == _ea_to_svg(tgt) and src.object_id != tgt.object_id
    if (
        ctype == "Association"
        and geo.edge_style == 1
        and not wpts
        and conn.source_role
        and conn.target_role
        and (geo.source_y or 0) > 0
        and (geo.end_y or 0) > 0
        and tx - (sx + sw) > sw
        and sy - (ty + th) > 30
    ):
        # EA's automatic route for two named association ends uses the open
        # corridor above a remote, upper-right target.
        route_x = sx + sw - min(20, sw / 8)
        route_y = ty + min(45, th / 2)
        all_pts = [(route_x, sy), (route_x, route_y), (tx, route_y)]
    elif (
        stale_bend
        and max(sh, th) < 1.6 * min(sh, th)
        and max(sy, ty) <= min(sy + sh, ty + th)
        and (sx + sw <= tx or tx + tw <= sx)
    ):
        y = min(max((sy + sh / 2 + ty + th / 2) / 2, max(sy, ty)), min(sy + sh, ty + th))
        all_pts = [(sx + sw, y), (tx, y)] if sx < tx else [(sx, y), (tx + tw, y)]
    elif stale_bend and geo.edge_style == 4 and (sy + sh <= ty or ty + th <= sy):
        source_x = sx + sw if tx > sx else sx
        target_y = ty if sy < ty else ty + th
        target_x = tx + tw / 2
        source_y = sy + sh / 2
        all_pts = [(source_x, source_y), (target_x, source_y), (target_x, target_y)]
    elif same_bounds and not wpts:
        # Distinct elements can be superimposed in an EA diagram. Their
        # connector must remain visible instead of collapsing to a point.
        x, y, width, height = _ea_to_svg(src)
        all_pts = [(x + width / 2, y + height / 2), (x + width / 2 + 3, y + height + 25)]
    elif straight is not None:
        all_pts = straight
    elif (
        ctype == "Association"
        and geo.edge_style == 3
        and not wpts
        and tx > sx + sw
        and ty > sy + sh
        and (geo.source_x or 0) < -0.35 * sw
        and (geo.end_x or 0) < -0.35 * tw
    ):
        # EA's rectangular route leaves the bottom of the upper-left class,
        # then enters the lower-right class on its left edge. The saved SX/EX
        # values identify the sides, but are not the final route coordinates.
        route_y = min(max(ty + th / 2 - (geo.end_y or 0) - 2, ty), ty + th)
        source_mid_x = sx + sw / 2
        all_pts = [(source_mid_x, sy + sh), (source_mid_x, route_y), (tx, route_y)]
    elif (
        geo.edge_style == 3
        and conn.connector_type == "Association"
        and not wpts
        and max(sh, th) >= 2 * min(sh, th)
        and (sy + sh <= ty or ty + th <= sy)
        and not conn.source_feature_guid
        and not conn.target_feature_guid
    ):
        overlap = max(0, min(sx + sw, tx + tw) - max(sx, tx))
        blend = 0.35 if overlap < 0.5 * min(sw, tw) else 1.0
        source_x = sx + sw / 2 + (p1[0] - sx - sw / 2) * blend
        target_x = tx + tw / 2 + (p2[0] - tx - tw / 2) * blend
        all_pts = [(source_x, sy + sh), (target_x, ty)] if sy < ty else [(source_x, sy), (target_x, ty + th)]
    elif (
        geo.edge_style == 4
        and ctype != "StateFlow"
        and not wpts
        and not conn.source_feature_guid
        and not conn.target_feature_guid
        and abs(p1[0] - p2[0]) > 150
        and abs(p1[1] - p2[1]) > 80
    ):
        # EA's orthogonal edge mode adds elbows even when Path is empty.
        middle_x = (p1[0] + p2[0]) / 2
        all_pts = [p1, (middle_x, p1[1]), (middle_x, p2[1]), p2]
    else:
        all_pts = [p1] + wpts + [p2]
    p1, p2 = all_pts[0], all_pts[-1]
    curved_state_control_y: Optional[float] = None
    if ctype == "StateFlow" and conn.style.mode == 10 and src.object_type == "State" and tgt.object_type == "State":
        sx, sy, sw, _ = _ea_to_svg(src)
        tx, ty, tw, _ = _ea_to_svg(tgt)
        # The saved waypoint says which side of the states the arc traverses.
        # EDGE alone is insufficient: both upper and lower CQL2 arcs use 2/4.
        top_arc = (wpts[0][1] < sy + sh / 2) if wpts else geo.edge_style == 2
        row = 12 if top_arc else 46
        p1 = (sx + sw if _node_center(src)[0] < _node_center(tgt)[0] else sx, sy + row)
        p2 = (tx if _node_center(src)[0] < _node_center(tgt)[0] else tx + tw, ty + row)
        dx = p2[0] - p1[0]
        control_y = (p1[1] + p2[1]) / 2 + (-18 if top_arc else 10)
        curved_state_control_y = control_y
        d = f"M {p1[0]},{p1[1]} C {p1[0] + dx * 0.28},{control_y} " f"{p1[0] + dx * 0.72},{control_y} {p2[0]},{p2[1]}"
        all_pts = [p1, p2]
    else:
        d = "M " + " L ".join(f"{px},{py}" for px, py in all_pts)

    stroke = (_colorref_to_css(conn.style.color) if style.respect_ea_colors else None) or (
        style.connector_note_color
        if is_note_link
        else style.control_flow_color
        if ctype == "ControlFlow" and style.control_flow_color
        else style.connector_color
    )
    if ctype == "InformationFlow" and style.information_flow_color and conn.style.color < 0:
        stroke = style.information_flow_color
    if ctype == "ObjectFlow" and style.control_flow_color and conn.style.color < 0:
        stroke = style.control_flow_color
    if ctype == "StateFlow" and style.ea_detail_nodes and style.respect_ea_colors and conn.style.color < 0:
        if conn.transition_event == "TaskAdminActionEnum.CANCEL":
            stroke = "#ff4500"
        elif (conn.transition_event or "").startswith("TaskAdminActionEnum."):
            stroke = "#ff0000"
        else:
            stroke = "#69738c"
    if (
        style.ea_detail_nodes
        and style.respect_ea_colors
        and conn.style.color < 0
        and ctype
        in (
            "Association",
            "Aggregation",
            "Composition",
            "Generalization",
            "Dependency",
            "Abstraction",
            "Realisation",
            "Usage",
        )
    ):
        stroke = "#69738c"
    stroke_w = str(max(conn.style.line_width, 1))

    path_attrs: Dict[str, str] = {
        "d": d,
        "fill": "none",
        "stroke": stroke,
        "stroke-width": stroke_w,
    }
    if is_note_link:
        path_attrs["stroke-dasharray"] = "4,3"
    elif ctype in ("Usage", "Dependency", "Abstraction", "Realisation"):
        path_attrs["stroke-dasharray"] = "5,3"
    elif ctype == "InformationFlow" and style.ea_detail_nodes:
        path_attrs["stroke-dasharray"] = "6,3"

    def navigable(setting: Optional[str], default: bool) -> bool:
        if setting == "Navigable":
            return True
        if setting == "Non-Navigable":
            return False
        return default

    source_arrow = navigable(conn.source_navigability, conn.direction in ("Destination -> Source", "Bi-Directional"))
    target_arrow = navigable(conn.target_navigability, conn.direction in ("Source -> Destination", "Bi-Directional"))
    if is_generalisation or ctype == "Realisation":
        path_attrs["marker-end"] = "url(#arrow-generalization)"
    elif is_aggregation or conn.source_is_aggregate or conn.target_is_aggregate:
        if conn.source_is_aggregate:
            kind = "filled" if conn.source_is_aggregate == 2 else "open"
            path_attrs["marker-start"] = f"url(#diamond-{kind}-start)"
        if conn.target_is_aggregate or is_aggregation and not conn.source_is_aggregate:
            kind = "filled" if conn.target_is_aggregate == 2 or ctype == "Composition" else "open"
            path_attrs["marker-end"] = f"url(#diamond-{kind}-end)"
        # EA exports diamond links with a plain line at the opposite end
        # (26/26 diamond groups across the reference exports), even when the
        # role style says Navigable; no navigability arrow is added there.
    elif ctype == "ControlFlow" and style.ea_detail_nodes:
        path_attrs["marker-end"] = "url(#arrow-control)"
    elif ctype == "InformationFlow" and style.ea_detail_nodes:
        path_attrs["marker-end"] = "url(#arrow-information)"
    elif ctype == "ObjectFlow" and style.ea_detail_nodes:
        path_attrs["marker-end"] = "url(#arrow-information)"
    elif ctype == "StateFlow" and style.ea_detail_nodes:
        path_attrs["marker-end"] = (
            "url(#arrow-state-action)"
            if stroke == "#ff0000"
            else "url(#arrow-state-cancel)"
            if stroke == "#ff4500"
            else "url(#arrow-state)"
        )
    elif ctype in ("Usage", "Dependency", "Abstraction", "StateFlow", "ControlFlow", "InformationFlow"):
        path_attrs["marker-end"] = "url(#arrow-open)"
    elif not is_note_link:
        if ctype in ("Association", "Aggregation", "Composition"):
            if source_arrow:
                path_attrs["marker-start"] = "url(#arrow-open-start)"
            if target_arrow:
                path_attrs["marker-end"] = "url(#arrow-open)"
        elif conn.direction == "Source -> Destination":
            path_attrs["marker-end"] = "url(#arrow-open)"
        elif conn.direction == "Destination -> Source":
            path_attrs["marker-start"] = "url(#arrow-open-start)"
        elif conn.direction == "Bi-Directional":
            path_attrs["marker-start"] = "url(#arrow-open-start)"
            path_attrs["marker-end"] = "url(#arrow-open)"

    ET.SubElement(g, "path", **path_attrs)
    detail_label_color = "#595959" if style.ea_detail_nodes and style.respect_ea_colors else style.node_border_color

    if style.ea_detail_nodes and ctype == "InformationFlow":
        midpoint = _polyline_midpoint(all_pts)
        for label, offset in ((conn.top_mid_label, -7), (conn.bottom_mid_label, 13)):
            if label:
                ET.SubElement(
                    g,
                    "text",
                    x=str(midpoint[0]),
                    y=str(midpoint[1] + offset),
                    **{
                        "text-anchor": "middle",
                        "font-family": style.font_family,
                        "font-size": "10",
                        "fill": detail_label_color,
                    },
                ).text = label
    elif (
        style.ea_detail_nodes
        and ctype in ("ControlFlow", "ObjectFlow")
        and conn.name in ("Yes", "No")
        and src.object_type == "Decision"
    ):
        # Branch guards belong to the decision they leave.  EA places them
        # beside the first segment, including ObjectFlow branches.
        first, next_point = all_pts[:2]
        dx, dy = next_point[0] - first[0], next_point[1] - first[1]
        _, source_y, source_w, source_h = _ea_to_svg(src)
        if abs(dx) > abs(dy):
            label_x = src.rect_right + 8 if dx > 0 else src.rect_left - _ea_text_width(conn.name, 10) - 6
            label_y = source_y + source_h - 3
        else:
            saved = conn.geometry.labels.get("LRT")
            label_x = src.rect_left + (saved.ox if saved else source_w / 2) - 6
            label_y = source_y + source_h + 14
        ET.SubElement(
            g,
            "text",
            x=str(label_x),
            y=str(label_y),
            **{"font-family": style.font_family, "font-size": "10", "fill": detail_label_color},
        ).text = conn.name
    elif style.ea_detail_nodes and ctype == "ControlFlow" and conn.name:
        if len(all_pts) > 1:
            first, next_point = all_pts[:2]
            decision_label = src.style.extra.get("LBL", "") if src.object_type == "Decision" else ""
            offset = re.search(r"(?:^|:)OY=(-?\d+)", decision_label)
            below_decision = offset and int(offset.group(1)) > sh / 2
            if below_decision and wpts:
                label_x = wpts[0][0] - (8 if wpts[0][0] > first[0] else 0)
                label_y = wpts[0][1] - 6
            else:
                label_x = first[0] + (8 if next_point[0] >= first[0] else -8)
                label_y = first[1] + (-6 if abs(next_point[0] - first[0]) > abs(next_point[1] - first[1]) else 14)
            ET.SubElement(
                g,
                "text",
                x=str(label_x),
                y=str(label_y),
                **{
                    "text-anchor": "middle" if below_decision and wpts else "start",
                    "font-family": style.font_family,
                    "font-size": "10",
                    "fill": detail_label_color,
                },
            ).text = conn.name

    if ctype == "StateFlow" and conn.transition_event:
        label_x, label_y = _polyline_midpoint(all_pts)
        label_position = conn.geometry.labels.get("LMT") if style.ea_detail_nodes else None
        if label_position and not label_position.hidden:
            label_x += label_position.ox - label_position.cx / 2
            if curved_state_control_y is not None:
                # EA labels these arcs along the outer side of the curve.
                label_y = curved_state_control_y + label_position.oy / 2 + 2
            else:
                label_y += label_position.oy - 4
            anchor = "start"
        else:
            label_y -= 8
            anchor = "middle"
        ET.SubElement(
            g,
            "text",
            x=str(label_x),
            y=str(label_y),
            **{
                "text-anchor": anchor,
                "font-family": style.font_family,
                "font-size": "10" if style.ea_detail_nodes else "11",
                "fill": "#595959" if style.ea_detail_nodes else style.node_border_color,
            },
        ).text = conn.transition_event

    if style.ea_detail_nodes and ctype in ("Abstraction", "Generalization", "Dependency", "Usage") and conn.stereotype:
        label_position = conn.geometry.labels.get("LMB")
        if label_position is None or not label_position.hidden:
            midpoint = _polyline_midpoint(all_pts)
            label_x, label_y = midpoint[0] + 1, midpoint[1] + 12
            label_width = label_position.cx if label_position else _ea_text_width(f"«{conn.stereotype}»", 10)
            first_dx = all_pts[1][0] - all_pts[0][0]
            first_dy = all_pts[1][1] - all_pts[0][1]
            if ctype == "Generalization" and len(all_pts) > 2 and abs(first_dy) > 2 * abs(first_dx):
                # EA labels the first vertical trunk of a routed generalization.
                label_x = all_pts[0][0] + 3
                label_y = (all_pts[0][1] + all_pts[1][1]) / 2 - 2
            elif ctype == "Dependency" and len(all_pts) > 2 and abs(first_dx) > 2 * abs(first_dy):
                # A routed dependency keeps its label beside the source row.
                label_x = (all_pts[0][0] + all_pts[-1][0]) / 2 - 1
                label_y = all_pts[0][1] + 13
            elif len(all_pts) == 2 and abs(first_dx) > 2 * abs(first_dy):
                label_x = midpoint[0] - label_width / 2 + 1
            ET.SubElement(
                g,
                "text",
                x=str(label_x + (label_position.ox if label_position else 0)),
                y=str(label_y + (label_position.oy if label_position else 0)),
                **{"font-family": style.font_family, "font-size": "10", "fill": detail_label_color},
            ).text = f"«{conn.stereotype}»"

    if style.ea_detail_nodes and ctype == "Association":
        midpoint = _polyline_midpoint(all_pts)
        for label, slot_name, offset in (
            (conn.name, "LMT", -4),
            (f"«{conn.stereotype}»" if conn.stereotype else None, "LMB", 13),
        ):
            slot = conn.geometry.labels.get(slot_name)
            if label and label.strip() and slot and not slot.hidden:
                ET.SubElement(
                    g,
                    "text",
                    x=str(midpoint[0] + slot.ox),
                    y=str(midpoint[1] + offset + slot.oy),
                    **{
                        "text-anchor": "middle",
                        "font-family": style.font_family,
                        "font-size": "10",
                        "fill": detail_label_color,
                    },
                ).text = label

    association_class = node_map.get(conn.association_class_object_id)
    if association_class is not None:
        link_start = _polyline_midpoint(all_pts)
        cx, cy = _node_center(association_class)
        _, _, width, height = _ea_to_svg(association_class)
        link_end = _clip_to_rect(cx, cy, width, height, link_start[0] - cx, link_start[1] - cy)
        ET.SubElement(
            g,
            "path",
            d=f"M {link_start[0]},{link_start[1]} L {link_end[0]},{link_end[1]}",
            fill="none",
            stroke=style.connector_note_color,
            **{"class": "association-class-link", "stroke-width": "1", "stroke-dasharray": "5,3"},
        )

    if style.ea_detail_nodes and not is_note_link:
        for endpoint, neighbor, role, cardinality, role_slot, card_slot in (
            (p1, all_pts[1], conn.source_role, conn.source_cardinality, "LLT", "LLB"),
            (p2, all_pts[-2], conn.target_role, conn.target_cardinality, "LRT", "LRB"),
        ):
            dx, dy = neighbor[0] - endpoint[0], neighbor[1] - endpoint[1]
            length = math.hypot(dx, dy) or 1
            label_x = endpoint[0] + dx / length * 10
            label_y = endpoint[1] + dy / length * 10
            role_position = conn.geometry.labels.get(role_slot)
            card_position = conn.geometry.labels.get(card_slot)
            horizontal = abs(dx) >= 2 * abs(dy)
            vertical = abs(dy) >= 2 * abs(dx)
            if horizontal or vertical:
                role_text = "+" + role.lstrip("+") if role else ""
                role_width = _ea_text_width(role_text, 10)
                card_width = _ea_text_width(cardinality, 10) if cardinality else 0
                if horizontal:
                    if dx > 0:
                        role_x = endpoint[0] + 3 + (role_position.ox if role_position else 0)
                        card_x = endpoint[0] + 3 + (card_position.ox if card_position else 0)
                    else:
                        role_x = endpoint[0] - role_width - 3 + (role_position.ox if role_position else 0)
                        card_x = endpoint[0] - card_width - 3 + (card_position.ox if card_position else 0)
                    role_y = endpoint[1] - 8 + (role_position.oy if role_position else 0)
                    card_y = endpoint[1] + 15 + (card_position.oy if card_position else 0)
                    if role and cardinality and abs(role_y - card_y) < 9:
                        role_x = card_x + card_width + 7 if dx > 0 else card_x - role_width - 7
                else:
                    baseline = endpoint[1] + (15 if dy > 0 else (-7 if role_slot == "LLT" else -8))
                    side_gap = 3 if role_slot == "LLT" else 8
                    role_x = endpoint[0] - role_width - side_gap + (role_position.ox if role_position else 0)
                    card_x = endpoint[0] + side_gap + (card_position.ox if card_position else 0)
                    role_y = baseline + (role_position.oy if role_position else 0)
                    card_y = baseline + (card_position.oy if card_position else 0)
                if role:
                    lines = _wrap_ea_text(role_text, role_position.cx or 1000, 10) if role_position else [role_text]
                    for index, line in enumerate(lines):
                        centered = (
                            max(0, ((role_position.cx or role_width) - _ea_text_width(line, 10)) / 2) if index else 0
                        )
                        ET.SubElement(
                            g,
                            "text",
                            x=str(role_x + centered),
                            y=str(role_y + 13 * index),
                            **{"font-family": style.font_family, "font-size": "10", "fill": detail_label_color},
                        ).text = line
                if cardinality:
                    ET.SubElement(
                        g,
                        "text",
                        x=str(card_x),
                        y=str(card_y),
                        **{"font-family": style.font_family, "font-size": "10", "fill": detail_label_color},
                    ).text = cardinality
                continue
            if role:
                ET.SubElement(
                    g,
                    "text",
                    x=str(label_x),
                    y=str(label_y - 5),
                    **{
                        "text-anchor": "middle",
                        "font-family": style.font_family,
                        "font-size": "10",
                        "fill": detail_label_color,
                    },
                ).text = "+" + role.lstrip("+")
            if cardinality:
                ET.SubElement(
                    g,
                    "text",
                    x=str(label_x),
                    y=str(label_y + 10),
                    **{
                        "text-anchor": "middle",
                        "font-family": style.font_family,
                        "font-size": "10",
                        "fill": detail_label_color,
                    },
                ).text = cardinality

    # Compact views label the relation once, near its midpoint.
    if style.compact_nodes and style.compact_connector_labels and not is_note_link:
        relation = conn.target_role or (
            "is a"
            if is_generalisation
            else "implements"
            if ctype == "Abstraction" and conn.stereotype == "Implements"
            else ctype.lower()
        )
        lx = (p1[0] + p2[0]) / 2
        ly = (p1[1] + p2[1]) / 2 - 6
    elif not style.compact_nodes and not style.ea_detail_nodes and conn.target_role:
        relation = conn.target_role
        lx = p2[0] * 0.8 + p1[0] * 0.2
        ly = p2[1] * 0.8 + p1[1] * 0.2 - 6
    else:
        relation = None
    if relation:
        if style.compact_nodes:
            label_width = max(36, len(relation) * 6.8 + 14)
            ET.SubElement(
                g,
                "rect",
                x=str(lx - label_width / 2),
                y=str(ly - 12),
                width=str(label_width),
                height="18",
                rx="4",
                fill=style.canvas_bg_color,
            )
        ET.SubElement(
            g,
            "text",
            x=str(lx),
            y=str(ly),
            **{
                "text-anchor": "middle" if style.compact_nodes else "start",
                "font-family": style.font_family,
                "font-size": "12" if style.compact_nodes else "9",
                "fill": style.node_border_color,
            },
        ).text = relation


def _ea_line_jumps(parent: ET.Element, connectors: List[NativeDiagramConnector]) -> None:
    """Add EA-style bridges where a later transition crosses earlier flows."""
    types = {conn.connector_id: conn.connector_type for conn in connectors}
    earlier: List[Tuple[int, Tuple[float, float], Tuple[float, float]]] = []
    for group in parent.findall("g"):
        connector_id = int(group.get("data-connector-id", "0"))
        path = group.find("path")
        if path is None:
            continue
        d = path.get("d", "")
        if set(re.findall(r"[A-Za-z]", d)) - {"M", "L"}:
            continue
        values = [float(value) for value in re.findall(r"-?\d+(?:\.\d+)?", d)]
        points = list(zip(values[::2], values[1::2]))
        segments = list(zip(points, points[1:]))
        if len(segments) == 1:
            start, end = segments[0]
            dx, dy = end[0] - start[0], end[1] - start[1]
            length = math.hypot(dx, dy)
            state_jump = types.get(connector_id) == "StateFlow" and abs(dx) > 20 and abs(dy) > 20
            activity_jump = types.get(connector_id) == "ControlFlow" and abs(dx) > 250 and abs(dy) < 2
            if (state_jump or activity_jump) and length > 30:
                hits = []
                for old_id, other_start, other_end in earlier:
                    if state_jump and types.get(old_id) != "StateFlow":
                        continue
                    if activity_jump and types.get(old_id) not in ("ControlFlow", "ObjectFlow"):
                        continue
                    ax, ay = start
                    bx, by = end
                    cx, cy = other_start
                    ex, ey = other_end
                    denominator = (ax - bx) * (cy - ey) - (ay - by) * (cx - ex)
                    if abs(denominator) < 1e-8:
                        continue
                    t = ((ax - cx) * (cy - ey) - (ay - cy) * (cx - ex)) / denominator
                    u = ((ax - cx) * (ay - by) - (ay - cy) * (ax - bx)) / denominator
                    if 12 / length < t < 1 - 12 / length and 0.04 < u < 0.96:
                        hits.append(t)
                if hits:
                    ux, uy = dx / length, dy / length
                    route = [f"M {start[0]},{start[1]}"]
                    for t in sorted(set(hits)):
                        cx, cy = start[0] + t * dx, start[1] + t * dy
                        before = (cx - 6 * ux, cy - 6 * uy)
                        after = (cx + 6 * ux, cy + 6 * uy)
                        route.append(f"L {before[0]},{before[1]}")
                        route.append(f"A 6 -6 180 0 0 {after[0]},{after[1]}")
                    route.append(f"L {end[0]},{end[1]}")
                    path.set("d", " ".join(route))
        elif types.get(connector_id) == "Association" and len(segments) > 1:
            # EA also bridges crossings on a horizontal leg of a routed
            # association, as in Point -> Frame in the Positions diagram.
            route = [f"M {points[0][0]},{points[0][1]}"]
            bridged = False
            for start, end in segments:
                dx, dy = end[0] - start[0], end[1] - start[1]
                length = math.hypot(dx, dy)
                hits = []
                if abs(dx) > 250 and abs(dy) < 2:
                    for _, other_start, other_end in earlier:
                        ox = other_end[0] - other_start[0]
                        oy = other_end[1] - other_start[1]
                        if abs(ox) > 2 or abs(oy) < 20:
                            continue
                        t = (other_start[0] - start[0]) / dx
                        u = (start[1] - other_start[1]) / oy
                        if 12 / length < t < 1 - 12 / length and 0.04 < u < 0.96:
                            hits.append(t)
                for t in sorted(set(hits)):
                    cx = start[0] + t * dx
                    before = (cx - 6 * math.copysign(1, dx), start[1])
                    after = (cx + 6 * math.copysign(1, dx), start[1])
                    route.append(f"L {before[0]},{before[1]}")
                    route.append(f"A 6 -6 180 0 0 {after[0]},{after[1]}")
                    bridged = True
                route.append(f"L {end[0]},{end[1]}")
            if bridged:
                path.set("d", " ".join(route))
        earlier.extend((connector_id, start, end) for start, end in segments)


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

    if style.ea_detail_nodes and diagram.diagram_type != "Sequence":
        # EA enlarges an undersized class box to show its full attribute
        # compartment when exporting.  Apply the effective bounds before
        # routing connectors, so links clip to the same visible rectangle.
        expanded_nodes = []
        for node in diagram.nodes:
            if diagram.hide_attributes and node.object_type == "Class":
                node = node.model_copy(update={"attributes": []})
            rows = _ea_attribute_rows(node) if node.object_type == "Class" else []
            required_height = rows[-1][1] + 8 if rows else 0
            current_height = node.rect_top - node.rect_bottom
            if required_height > current_height:
                node = node.model_copy(update={"rect_bottom": node.rect_top - required_height})
            expanded_nodes.append(node)
        diagram = diagram.model_copy(update={"nodes": expanded_nodes})

    node_map: Dict[int, NativeDiagramNode] = {n.object_id: n for n in diagram.nodes}

    # Compute bounding box over all nodes to set viewBox.
    # Use the effective right edge (accounting for min-width expansion) so
    # nodes whose names or attribute labels are wider than the EA-stored
    # rectangle are not clipped by the canvas.
    ea_page_frame = style.ea_detail_nodes and diagram.diagram_type != "Statechart" and bool(diagram.nodes)
    if ea_page_frame:
        # EA's non-statechart page encloses the stored objects with fixed
        # margins: left 29, top 34, right 44, bottom 27, then a 6 px gutter.
        frame_x = min(n.rect_left for n in diagram.nodes) - 29
        frame_y = min(-n.rect_top for n in diagram.nodes) - 34
        frame_right = max(n.rect_right for n in diagram.nodes) + 44
        frame_bottom = max(-n.rect_bottom for n in diagram.nodes) + 27
        min_x, min_y = frame_x - 6, frame_y - 6
        max_x, max_y = frame_right + 6, frame_bottom + 6
    elif diagram.nodes:
        xs_left = [n.rect_left for n in diagram.nodes]
        xs_right = [
            n.rect_left + max(float(n.rect_right - n.rect_left), _node_min_width(n, style)) for n in diagram.nodes
        ]
        ys_top = [-n.rect_top for n in diagram.nodes]
        ys_bot = [-n.rect_top + _node_min_height(n, style) for n in diagram.nodes]
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

    _build_defs(root, style, diagram)

    ET.SubElement(root, "title").text = diagram.name

    if ea_page_frame:
        group = ET.SubElement(root, "g", id="ea-page-frame")
        ET.SubElement(
            group,
            "rect",
            x=str(frame_x),
            y=str(frame_y),
            width=str(frame_right - frame_x),
            height=str(frame_bottom - frame_y),
            fill="none",
            stroke="#000000",
        )
        title = diagram.name
        prefix = re.match(r"^([PL]\d+)\s*:", title)
        if diagram.view_id:
            title = f"{diagram.view_id} {title}"
        elif prefix:
            title = f"{prefix.group(1)} {title}"
        tab_right = frame_x + _ea_text_width(title, 10) + 20
        tab = (
            f"{frame_x},{frame_y + 20} {tab_right - 13},{frame_y + 20} "
            f"{tab_right},{frame_y + 6} {tab_right},{frame_y} {frame_x},{frame_y}"
        )
        ET.SubElement(group, "polygon", points=tab, fill="#ffffff", stroke="#000000")
        ET.SubElement(
            group,
            "text",
            x=str(frame_x + 5),
            y=str(frame_y + 13),
            **{"font-family": style.font_family, "font-size": "10", "font-weight": "bold", "fill": "#000000"},
        ).text = title

    fo_map: Dict[int, str] = {}

    if diagram.diagram_type == "Sequence":
        _render_sequence_content(root, diagram, node_map, style, fo_map)
    else:
        _render_class_content(root, diagram, node_map, style, fo_map)

    # Statecharts display their title in the EA state-machine frame.
    if diagram.diagram_type != "Statechart" and not ea_page_frame:
        ET.SubElement(
            root,
            "text",
            x=str(min_x + 6),
            y=str(min_y + 9),
            **{
                "font-family": style.font_family,
                "font-size": "10",
                "font-weight": "bold",
                "fill": style.node_border_color,
            },
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

    def render_node(parent: ET.Element, node: NativeDiagramNode) -> None:
        if node.object_type == "Note":
            _render_note_node(parent, node, style, fo_map)
        elif diagram.diagram_type == "Statechart" and node.object_type in (
            "StateMachine",
            "State",
            "StateNode",
            "Text",
        ):
            _render_statechart_node(parent, node, diagram.name, style)
        elif (
            diagram.diagram_type == "Custom"
            and node.object_type
            in (
                "Activity",
                "Action",
                "ActionPin",
                "Decision",
                "MergeNode",
                "StateNode",
                "Synchronization",
                "ForkNode",
                "JoinNode",
                "Text",
            )
            and style.ea_detail_nodes
        ):
            _render_activity_node(parent, node, style)
        else:
            _render_class_node(parent, node, style)

    def contains(outer: NativeDiagramNode, inner: NativeDiagramNode) -> bool:
        if outer.object_id == inner.object_id:
            return False
        ox, oy, ow, oh = _ea_to_svg(outer)
        ix, iy, iw, ih = _ea_to_svg(inner)
        return ox <= ix and oy <= iy and ox + ow >= ix + iw and oy + oh >= iy + ih and (ow > iw or oh > ih)

    containers = [node for node in diagram.nodes if any(contains(node, other) for other in diagram.nodes)]
    container_ids = {node.object_id for node in containers}
    container_group = ET.SubElement(root, "g", id="containers")
    for node in sorted(
        containers, key=lambda item: -(item.rect_right - item.rect_left) * (item.rect_top - item.rect_bottom)
    ):
        render_node(container_group, node)

    conn_group = ET.SubElement(root, "g", id="connectors")
    for conn in diagram.connectors:
        if not conn.hidden:
            _render_connector(conn_group, conn, node_map, style)
    if style.ea_detail_nodes:
        _ea_line_jumps(conn_group, diagram.connectors)

    node_group = ET.SubElement(root, "g", id="nodes")
    for node in diagram.nodes:
        if node.object_id not in container_ids:
            render_node(node_group, node)
    if style.ea_detail_nodes:
        feature_group = ET.SubElement(root, "g", id="feature-attachments")
        for conn in diagram.connectors:
            if conn.hidden:
                continue
            src = node_map.get(conn.source_object_id)
            tgt = node_map.get(conn.target_object_id)
            if src is None or tgt is None:
                continue
            for node, guid, side, toward in (
                (src, conn.source_feature_guid, conn.source_feature_side, _node_center(tgt)),
                (tgt, conn.target_feature_guid, conn.target_feature_side, _node_center(src)),
            ):
                endpoint = _feature_anchor(node, guid, side, toward)
                if endpoint is None:
                    continue
                nx, _, nw, _ = _ea_to_svg(node)
                inset = 3 if abs(endpoint[0] - nx) <= 1 else -3
                if abs(endpoint[0] - nx) > 1 and abs(endpoint[0] - nx - nw) > 1:
                    continue
                bx = endpoint[0] + inset
                tip = endpoint[0] + inset * 4
                stroke = (_colorref_to_css(conn.style.color) if style.respect_ea_colors else None) or (
                    "#69738c" if style.respect_ea_colors else style.connector_color
                )
                ET.SubElement(
                    feature_group,
                    "path",
                    d=(
                        f"M {tip},{endpoint[1] - 5} L {bx},{endpoint[1] - 5} "
                        f"L {bx},{endpoint[1] + 5} L {tip},{endpoint[1] + 5}"
                    ),
                    fill="none",
                    stroke=stroke,
                    **{"stroke-width": "1"},
                )


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
    boundaries = [n for n in diagram.nodes if n.object_type == "Boundary"]

    # 1. Interaction fragments (lowest layer)
    frag_group = ET.SubElement(root, "g", id="fragments")
    for frag in fragments:
        _render_interaction_fragment(frag_group, frag, style)

    # 2. Lifelines
    lf_group = ET.SubElement(root, "g", id="lifelines")
    for node in lifelines:
        _render_lifeline(lf_group, node, style, node_map.get(node.parent_object_id))

    # 3. Messages
    msg_group = ET.SubElement(root, "g", id="messages")
    # The sampled EA exports contain no execution bars, including messages
    # with nonzero PDATA5/SY.  That field describes message geometry and does
    # not by itself establish a visible execution specification.
    activation_spans = {} if style.ea_detail_nodes else _compute_activation_spans(diagram.sequence_messages, node_map)
    for msg in diagram.sequence_messages:
        _render_sequence_message(msg_group, msg, activation_spans, style)

    # Sequence separators are EA Boundary objects, not interaction fragments.
    boundary_group = ET.SubElement(root, "g", id="sequence-boundaries")
    for node in boundaries:
        x, y, width, height = _ea_to_svg(node)
        group = ET.SubElement(
            boundary_group, "g", **{"class": "sequence-boundary", "data-object-id": str(node.object_id)}
        )
        ET.SubElement(
            group,
            "rect",
            x=str(x),
            y=str(y),
            width=str(width),
            height=str(height),
            fill="none",
            stroke="#000000",
            **{"stroke-width": "2"},
        )
        ET.SubElement(
            group,
            "text",
            x=str(x + width / 2),
            y=str(y + 16),
            **{
                "text-anchor": "middle",
                "font-family": style.font_family,
                "font-size": "13",
                "font-weight": "bold",
                "fill": "#595959" if style.respect_ea_colors else style.node_border_color,
            },
        ).text = node.name

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
