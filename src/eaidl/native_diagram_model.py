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

from typing import Dict, List, Optional, Tuple

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
    """BCol — Windows COLORREF integer (0x00BBGGRR), -1 = default."""

    line_color: int = -1
    """LCol — Windows COLORREF border/line colour, -1 = default."""

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
    """Color — Windows COLORREF integer, -1 = default."""

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
    visibility: Optional[str] = None
    """EA Scope, used for visibility symbols and diagram attribute filters."""
    stereotype: Optional[str] = None
    """Attribute stereotype, rendered as a heading for its compartment group."""
    inherited_from: Optional[str] = None
    """Name of the ancestor that owns this field when AttInh=1."""
    inheritance_depth: int = 0
    """Distance from the displayed class to that ancestor; own fields use zero."""
    ea_guid: Optional[str] = None
    """EA GUID, used by feature-linked connector endpoints."""

    type_guid: Optional[str] = None
    """
    ``t_object.ea_guid`` of the *type* class, resolved from
    ``t_attribute.Classifier`` (the Object_ID of the referenced type).
    ``None`` when the type is primitive / unresolved.
    """


class NativeDiagramNode(BaseModel):
    """
    One object placed on an EA diagram.

    Covers Class, Note, Part, and any other ``t_object.Object_Type`` values.
    The ``rect_*`` fields are in raw EA canvas coordinates (see module docstring).
    """

    object_id: int
    parent_object_id: int = 0
    """EA ParentID, used to position nested sequence lifeline heads."""
    name: str
    object_type: str
    """t_object.Object_Type — ``Class``, ``Note``, ``Part``, etc."""
    ntype: int = 0
    """EA NType distinguishes initial (100) and final (101) activity nodes."""

    stereotype: Optional[str] = None
    stereotypes: List[str] = Field(default_factory=list)
    """All stereotypes from the ``t_xref`` list, primary first; EA mode shows them comma-joined."""
    is_abstract: bool = False
    parent_name: Optional[str] = None
    """Immediate generalization parent displayed in EA's class header."""
    classifier_name: Optional[str] = None
    """Classifier shown after a Part role name in EA resource views."""
    display_context: Optional[str] = None
    """Optional export-only context label, such as the owning model layer."""
    foreign_package_path: Optional[str] = None
    """Full package path displayed below a foreign class when EA ShowFQN=1."""

    ea_guid: Optional[str] = None
    """
    ``t_object.ea_guid`` — the stable cross-reference key that matches
    ``ModelClass.guid`` in the IDL model pipeline and in ``model_export.py``.
    Use this to correlate diagram node link maps with the exported YAML model.
    """

    note_text: Optional[str] = None
    """Note body for notes, or element documentation for classes."""
    legend_title: Optional[str] = None
    legend_entries: List[Tuple[str, str]] = Field(default_factory=list)
    """EA Text legend content and its explicit CSS colours."""
    legend_is_line: bool = False
    legend_background_color: Optional[str] = None
    legend_text_color: Optional[str] = None
    interaction_operands: List[Tuple[str, int]] = Field(default_factory=list)
    """Combined-fragment operand guards and heights, ordered from top to bottom."""

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
    ea_guid: Optional[str] = None
    name: Optional[str] = None
    stereotype: Optional[str] = None
    top_mid_label: Optional[str] = None
    bottom_mid_label: Optional[str] = None
    """EA connector labels, including conveyed information on P2 flows."""
    transition_event: Optional[str] = None
    """StateFlow event label stored in t_connector.PDATA1."""

    source_object_id: int
    target_object_id: int
    direction: Optional[str] = None
    """EA Direction, including Unspecified and Source -> Destination."""
    source_navigability: Optional[str] = None
    target_navigability: Optional[str] = None
    """Navigable end settings from t_connector SourceStyle/DestStyle."""
    head_style: int = 0
    line_style: int = 0
    """Raw t_connector style codes; zero delegates to EA's connector defaults."""
    source_is_aggregate: int = 0
    target_is_aggregate: int = 0
    """EA aggregate end: 0 = none, 1 = shared, 2 = composite."""
    source_feature_guid: Optional[str] = None
    target_feature_guid: Optional[str] = None
    source_feature_side: Optional[str] = None
    target_feature_side: Optional[str] = None
    """LFSP/LFEP attribute attachment in the connector StyleEx."""
    association_class_object_id: Optional[int] = None
    """EA PDATA1 reference to an association class, when present."""

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
    show_foreign: bool = True
    """EA ShowForeign: display package qualifiers on foreign class names."""
    show_fqn: bool = False
    """EA ShowFQN: place a foreign class's full package path below its box."""
    hide_attributes: bool = False
    """EA diagram PDATA HideAtts: suppress all class attribute compartments."""
    view_id: Optional[str] = None
    """View id from StyleEx ``MDGDgm=<profile>::<view> - <title>`` (``P2``); EA prefixes the frame title with it."""

    nodes: List[NativeDiagramNode] = Field(default_factory=list)
    connectors: List[NativeDiagramConnector] = Field(default_factory=list)
    sequence_messages: List[NativeSequenceMessage] = Field(default_factory=list)
    """Populated only for ``diagram_type == 'Sequence'``."""
