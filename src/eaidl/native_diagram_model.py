"""
Native EA Diagram Model — rich intermediary representation of EA-authored diagrams.

This module holds a fully-decoded snapshot of *exactly what EA stored* in the
database for each diagram: node positions, visual styles, connector routing,
label positions, etc.  It is intentionally format-agnostic: downstream
renderers (SVG, Excalidraw, DrawIO, …) consume this model without knowing
anything about EA's encoding.

Coordinate system (preserved from EA)
--------------------------------------
EA stores positions as signed integers in a canvas-local coordinate space:

  * X increases to the right (positive).
  * Y decreases downward (is stored as zero or negative).
  * rect_left / rect_top is the top-left corner.
  * rect_right / rect_bottom is the bottom-right corner.
  * canvas_width / canvas_height are the diagram extents in pixels.

To convert to standard screen coordinates (Y = 0 at top, increasing down):

    screen_x      = rect_left
    screen_y      = -rect_top
    node_width    = rect_right  - rect_left
    node_height   = rect_top   - rect_bottom   (rect_top > rect_bottom)
"""

from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class NativeObjectStyle(BaseModel):
    """
    Decoded from ``t_diagramobjects.ObjectStyle`` (semicolon-separated key=value).

    Only well-known keys are surfaced; all others land in ``extra``.
    """

    duid: Optional[str] = None
    """Diagram-unique placement ID.  Connectors reference this via SOID / EOID."""

    hide_icon: bool = False
    """HideIcon — suppress the stereotype icon."""

    background_color: int = -1
    """BCol — ARGB integer, -1 = use default."""

    line_color: int = -1
    """LCol — border/line colour, -1 = use default."""

    line_width: int = -1
    """LWth — border line width in pixels, -1 = use default."""

    font_size: int = 0
    """fontsz — 0 = use default."""

    bold: bool = False
    italic: bool = False
    underline: bool = False

    show_inherited_attrs: bool = False
    """AttInh — show inherited attributes in the compartment."""

    show_custom_attrs: bool = False
    """AttCustom — show custom / tagged properties."""

    extra: Dict[str, str] = Field(default_factory=dict)
    """Any keys not explicitly decoded above."""


class NativeLabelPosition(BaseModel):
    """
    Position of a single connector label, decoded from the label-slot strings
    inside ``t_diagramlinks.Geometry``.

    Label slots: LLB, LLT, LMT, LMB, LRT, LRB, IRHS, ILHS.
    """

    cx: int = 0
    """Centre X of the label box relative to the connector midpoint."""

    cy: int = 0
    """Centre Y of the label box relative to the connector midpoint."""

    ox: int = 0
    """Additional X offset."""

    oy: int = 0
    """Additional Y offset."""

    hidden: bool = False
    bold: bool = False
    italic: bool = False
    underline: bool = False
    color: int = -1
    align: int = 1
    direction: int = 0
    rotation: int = 0


class NativeLinkGeometry(BaseModel):
    """
    Decoded from ``t_diagramlinks.Geometry`` and ``t_diagramlinks.Path``.

    SX/SY and EX/EY are offsets from the *geometric centre* of the source and
    target nodes respectively.  Positive Y = upward in EA space (i.e. toward
    rect_top).
    """

    source_x: Optional[int] = None
    """SX — horizontal offset from source node centre to connection point."""

    source_y: Optional[int] = None
    """SY — vertical offset from source node centre to connection point (+ = up)."""

    end_x: Optional[int] = None
    """EX — horizontal offset from target node centre to connection point."""

    end_y: Optional[int] = None
    """EY — vertical offset from target node centre to connection point (+ = up)."""

    edge_style: int = 1
    """
    EDGE routing mode:
      1 = auto (EA chooses shortest path)
      2 = orthogonal / right-angle segments
      3 = custom / bezier
      4 = direct line (no routing)
    """

    waypoints: List[List[int]] = Field(default_factory=list)
    """
    Intermediate bend-points from ``t_diagramlinks.Path``, in EA canvas
    coordinates.  Each entry is ``[x, y]``.
    """

    labels: Dict[str, NativeLabelPosition] = Field(default_factory=dict)
    """
    Per-slot label positions decoded from the ``$…`` section of the geometry
    string.  Keys: ``LLB``, ``LLT``, ``LMT``, ``LMB``, ``LRT``, ``LRB``,
    ``IRHS``, ``ILHS``.
    """


class NativeLinkStyle(BaseModel):
    """Decoded from ``t_diagramlinks.Style`` (semicolon-separated key=value)."""

    mode: int = 3
    """Mode — rendering mode (3 = custom)."""

    end_duid: Optional[str] = None
    """EOID — matches ``NativeObjectStyle.duid`` of the target node."""

    start_duid: Optional[str] = None
    """SOID — matches ``NativeObjectStyle.duid`` of the source node."""

    color: int = -1
    """Color — ARGB integer, -1 = use default."""

    line_width: int = 0
    """LWidth — line width in pixels."""


class NativeDiagramAttribute(BaseModel):
    """One attribute (field) of a class node as stored in ``t_attribute``."""

    name: str
    type: str
    lower_bound: Optional[str] = None
    upper_bound: Optional[str] = None
    position: int = 0
    """Pos — display order within the compartment."""


class NativeDiagramNode(BaseModel):
    """
    One object placed on an EA diagram.

    Covers Class, Note, Part, and any other ``t_object.Object_Type`` values.
    The ``rect_*`` fields are in raw EA canvas coordinates (see module docstring).
    """

    object_id: int
    name: str
    object_type: str
    """t_object.Object_Type — ``Class``, ``Note``, ``Part``, etc."""

    stereotype: Optional[str] = None
    is_abstract: bool = False

    note_text: Optional[str] = None
    """Populated for ``Note`` objects."""

    note_connector_ref: Optional[int] = None
    """
    For notes attached to a sequence message: the ``Connector_ID`` of the
    referenced connector, parsed from ``t_object.PDATA4 = 'idref1=<id>;'``.
    """

    # --- canvas position (EA coordinate space) ---
    rect_left: int
    rect_top: int
    rect_right: int
    rect_bottom: int
    z_order: int = 0
    """Sequence / Z-order for overlapping objects."""

    style: NativeObjectStyle
    attributes: List[NativeDiagramAttribute] = Field(default_factory=list)


class NativeDiagramConnector(BaseModel):
    """One connector (edge) placed on an EA diagram."""

    connector_id: int
    connector_type: str
    name: Optional[str] = None
    stereotype: Optional[str] = None

    source_object_id: int
    target_object_id: int

    source_role: Optional[str] = None
    target_role: Optional[str] = None
    source_cardinality: Optional[str] = None
    target_cardinality: Optional[str] = None

    hidden: bool = False

    geometry: NativeLinkGeometry
    style: NativeLinkStyle


class NativeSequenceMessage(BaseModel):
    """
    One message in a sequence diagram.

    EA stores these in ``t_connector`` rows that carry a ``DiagramID`` foreign
    key directly on the connector (rather than through ``t_diagramlinks``).  The
    ``PtStartX/Y`` and ``PtEndX/Y`` columns give the absolute canvas-coordinate
    endpoints of the arrow.
    """

    connector_id: int
    name: Optional[str] = None
    stereotype: Optional[str] = None

    source_object_id: int
    target_object_id: int

    seq_no: int = 0
    """SeqNo — display order / time ordering of messages."""

    call_type: Optional[str] = None
    """PDATA1 — e.g. ``Asynchronous``, ``Synchronous``, ``Reply``."""

    return_value: Optional[str] = None
    """Parsed from PDATA2 ``retval=…`` (empty-string / 'void' means no return)."""

    param_values: Optional[str] = None
    """Parsed from ``StyleEx`` ``paramvalues=…``."""

    activation_bar_height: int = 0
    """
    Height in pixels of the activation box drawn at the destination lifeline.
    Parsed from the ``SY`` value in ``PDATA5`` of the sequence connector.
    A value of 0 means no explicit activation box was stored.
    """

    # Absolute canvas coordinates (EA space — Y is negative)
    start_x: int = 0
    start_y: int = 0
    end_x: int = 0
    end_y: int = 0


class NativeDiagram(BaseModel):
    """
    Complete native representation of one EA-authored diagram, ready for
    serialisation to YAML/JSON or consumption by a downstream renderer.
    """

    diagram_id: int
    name: str
    diagram_type: Optional[str] = None
    stereotype: Optional[str] = None
    author: Optional[str] = None
    notes: Optional[str] = None
    canvas_width: int
    canvas_height: int

    nodes: List[NativeDiagramNode] = Field(default_factory=list)
    connectors: List[NativeDiagramConnector] = Field(default_factory=list)
    sequence_messages: List[NativeSequenceMessage] = Field(default_factory=list)
    """Populated only for ``diagram_type == 'Sequence'``."""
