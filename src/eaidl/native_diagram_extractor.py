"""
Native EA Diagram Extractor — reads EA-authored diagram data from the database
and decodes all proprietary encoding into :class:`~eaidl.native_diagram_model.NativeDiagram`
objects.

This module is *independent* of the IDL model pipeline.  It does not require
``ModelParser`` to have run first, and it loads every object that appears on
the diagram regardless of whether it falls within ``config.root_packages``.

Usage (standalone)::

    extractor = NativeDiagramExtractor.from_url("sqlite:///path/to/model.qea")
    diagrams = extractor.extract_all()
    extractor.close()

Usage (alongside ModelParser)::

    parser = ModelParser(config)
    parser.load()
    extractor = NativeDiagramExtractor(parser.session)
    diagrams = extractor.extract_all()
"""

from __future__ import annotations

import logging
import re
from typing import Dict, List, Optional, Tuple

import sqlalchemy
from sqlalchemy.ext.automap import automap_base
from sqlalchemy.orm import Session, sessionmaker

from eaidl.native_diagram_model import (
    NativeDiagram,
    NativeDiagramAttribute,
    NativeDiagramConnector,
    NativeDiagramNode,
    NativeLabelPosition,
    NativeLinkGeometry,
    NativeLinkStyle,
    NativeObjectStyle,
    NativeSequenceMessage,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level automap base (separate from load.py's base so this module can
# be used standalone without bootstrapping the full IDL pipeline).
# ---------------------------------------------------------------------------
_base = automap_base()


@sqlalchemy.event.listens_for(_base.metadata, "column_reflect")
def _column_reflect(inspector, table, column_info):
    column_info["key"] = "attr_%s" % column_info["name"].lower()


# ---------------------------------------------------------------------------
# String decoders
# ---------------------------------------------------------------------------


def _parse_kv(s: Optional[str], sep: str = ";") -> Dict[str, str]:
    """Parse ``key=value;key=value;…`` strings into a plain dict."""
    if not s:
        return {}
    result: Dict[str, str] = {}
    for token in s.split(sep):
        token = token.strip()
        if "=" in token:
            k, _, v = token.partition("=")
            result[k.strip()] = v.strip()
    return result


def parse_object_style(raw: Optional[str]) -> NativeObjectStyle:
    """
    Decode an EA ``ObjectStyle`` string into :class:`NativeObjectStyle`.

    Format: ``KEY=VALUE;KEY=VALUE;…``

    Known keys::

        DUID       — diagram-unique placement ID
        HideIcon   — 0/1
        NSL        — (unknown flag)
        BCol       — background colour (ARGB int, -1 = default)
        BFol       — (unknown)
        LCol       — line/border colour (-1 = default)
        LWth       — line width (-1 = default)
        fontsz     — font size (0 = default)
        bold, black, italic, ul  — font flags (0/1)
        AttCustom  — show custom attributes (0/1)
        OpCustom   — show custom operations (0/1)
        AttInh     — show inherited attributes (0/1)
        RzO        — resize to content (0/1)
    """
    kv = _parse_kv(raw)
    known = {
        "DUID",
        "HideIcon",
        "NSL",
        "BCol",
        "BFol",
        "LCol",
        "LWth",
        "fontsz",
        "bold",
        "black",
        "italic",
        "ul",
        "charset",
        "pitch",
        "AttCustom",
        "OpCustom",
        "AttInh",
        "RzO",
    }

    def _b(key: str, default: bool = False) -> bool:
        return kv.get(key, "0") == "1"

    def _i(key: str, default: int = -1) -> int:
        try:
            return int(kv.get(key, str(default)))
        except (ValueError, TypeError):
            return default

    extra = {k: v for k, v in kv.items() if k not in known}

    return NativeObjectStyle(
        duid=kv.get("DUID"),
        hide_icon=_b("HideIcon"),
        background_color=_i("BCol"),
        line_color=_i("LCol"),
        line_width=_i("LWth"),
        font_size=_i("fontsz", 0),
        bold=_b("bold"),
        italic=_b("italic"),
        underline=_b("ul"),
        show_inherited_attrs=_b("AttInh"),
        show_custom_attrs=_b("AttCustom"),
        extra=extra,
    )


def _parse_label_slot(raw: str) -> Optional[NativeLabelPosition]:
    """
    Parse one label-slot string from the geometry ``$…`` section.

    Format: ``CX=26:CY=14:OX=0:OY=0:HDN=0:BLD=0:ITA=0:UND=0:CLR=-1:ALN=1:DIR=0:ROT=0``
    Returns ``None`` if ``raw`` is empty/whitespace.
    """
    raw = raw.strip()
    if not raw:
        return None
    kv = _parse_kv(raw, sep=":")

    def _i(k: str, d: int = 0) -> int:
        try:
            return int(kv.get(k, str(d)))
        except (ValueError, TypeError):
            return d

    return NativeLabelPosition(
        cx=_i("CX"),
        cy=_i("CY"),
        ox=_i("OX"),
        oy=_i("OY"),
        hidden=kv.get("HDN", "0") == "1",
        bold=kv.get("BLD", "0") == "1",
        italic=kv.get("ITA", "0") == "1",
        underline=kv.get("UND", "0") == "1",
        color=_i("CLR", -1),
        align=_i("ALN", 1),
        direction=_i("DIR"),
        rotation=_i("ROT"),
    )


# Label slot names in the order EA emits them after the '$' separator.
_LABEL_SLOTS = ("LLB", "LLT", "LMT", "LMB", "LRT", "LRB", "IRHS", "ILHS")


def parse_link_geometry(geometry: Optional[str], path: Optional[str]) -> NativeLinkGeometry:
    """
    Decode an EA ``Geometry`` string and the companion ``Path`` field into
    :class:`NativeLinkGeometry`.

    Geometry format (before ``$``)::

        SX=<int>;SY=<int>;EX=<int>;EY=<int>;EDGE=<int>

    After ``$``, label slots separated by ``;``::

        LLB=<slot>;LLT=<slot>;LMT=<slot>;LMB=<slot>;LRT=<slot>;LRB=<slot>;IRHS=<slot>;ILHS=<slot>

    Each slot is either empty or ``CX=…:CY=…:…``.

    Path format (separate column)::

        x1:y1;x2:y2;…
    """
    waypoints = _parse_path(path)

    if not geometry:
        return NativeLinkGeometry(waypoints=waypoints)

    # Split main body from label section on '$'
    if "$" in geometry:
        main_part, label_part = geometry.split("$", 1)
    else:
        main_part, label_part = geometry, ""

    kv = _parse_kv(main_part)

    def _opt_int(key: str) -> Optional[int]:
        v = kv.get(key)
        if v is None:
            return None
        try:
            return int(v)
        except (ValueError, TypeError):
            return None

    edge_style = int(kv.get("EDGE", "1"))

    # Parse label slots from the '' section.
    # Format: LLB=<data>;LLT=<data>;… where <data> may be empty or CX=:CY=:…
    labels: Dict[str, NativeLabelPosition] = {}
    if label_part:
        # The label_part looks like: LLB=;LLT=;LMT=;LMB=CX=60:CY=15:…;LRT=;LRB=;IRHS=;ILHS=
        # We need to split on ";LLB=", ";LLT=", etc.  rather than plain ";" because
        # slot content itself contains ":"-separated values (not ";").
        slot_pattern = "|".join(re.escape(s) for s in _LABEL_SLOTS)
        raw_slots = re.split(rf";?({slot_pattern})=", label_part)
        # raw_slots alternates between separators and values: ['', 'LLB', '', 'LLT', '', …]
        slot_iter = iter(raw_slots)
        next(slot_iter)  # skip leading empty string
        for slot_name, slot_value in zip(slot_iter, slot_iter):
            pos = _parse_label_slot(slot_value)
            if pos is not None:
                labels[slot_name] = pos

    return NativeLinkGeometry(
        source_x=_opt_int("SX"),
        source_y=_opt_int("SY"),
        end_x=_opt_int("EX"),
        end_y=_opt_int("EY"),
        edge_style=edge_style,
        waypoints=waypoints,
        labels=labels,
    )


def _parse_path(path: Optional[str]) -> List[Tuple[int, int]]:
    """
    Decode ``t_diagramlinks.Path`` into a list of (x, y) waypoints.

    Format: ``x1:y1;x2:y2;…``  (EA canvas coordinates).
    """
    if not path:
        return []
    points: List[List[int]] = []
    for token in path.split(";"):
        token = token.strip()
        if not token:
            continue
        if ":" in token:
            x_str, _, y_str = token.partition(":")
            try:
                points.append([int(x_str), int(y_str)])
            except ValueError:
                log.debug("Skipping invalid path waypoint: %r", token)
    return points


def parse_link_style(raw: Optional[str]) -> NativeLinkStyle:
    """
    Decode an EA ``Style`` string from ``t_diagramlinks`` into
    :class:`NativeLinkStyle`.

    Format: ``Mode=3;EOID=…;SOID=…;Color=-1;LWidth=0;``
    """
    kv = _parse_kv(raw)

    def _i(k: str, d: int = 0) -> int:
        try:
            return int(kv.get(k, str(d)))
        except (ValueError, TypeError):
            return d

    return NativeLinkStyle(
        mode=_i("Mode", 3),
        end_duid=kv.get("EOID"),
        start_duid=kv.get("SOID"),
        color=_i("Color", -1),
        line_width=_i("LWidth", 0),
    )


# ---------------------------------------------------------------------------
# Extractor
# ---------------------------------------------------------------------------


class NativeDiagramExtractor:
    """
    Extracts fully-decoded :class:`~eaidl.native_diagram_model.NativeDiagram`
    objects directly from an EA database.

    This class is *independent* of the IDL model pipeline.  It does not care
    about ``config.root_packages`` and will include every object that appears
    on the diagram, even if those objects live outside your configured scope.
    """

    def __init__(self, session: Session) -> None:
        self.session = session

    @classmethod
    def from_url(cls, database_url: str) -> "NativeDiagramExtractor":
        """
        Create an extractor connected directly to ``database_url``.

        The caller is responsible for calling :meth:`close` when done.

        :param database_url: SQLAlchemy connection URL
                             (e.g. ``"sqlite:///path/to/model.qea"``).
        """
        engine = sqlalchemy.create_engine(database_url, echo=False, future=True)
        _base.prepare(autoload_with=engine)
        session = sessionmaker(engine)()
        instance = cls(session)
        instance._owns_session = True
        instance._engine = engine
        return instance

    def close(self) -> None:
        """Close the session (and engine if we own it)."""
        self.session.close()
        if getattr(self, "_owns_session", False):
            self._engine.dispose()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def extract_all(self) -> List[NativeDiagram]:
        """Return all diagrams in the database."""
        TDiagram = _base.classes.t_diagram
        rows = self.session.query(TDiagram).all()
        diagrams = []
        for row in rows:
            try:
                diagrams.append(self._extract_diagram(row))
            except Exception:
                log.warning(
                    "Failed to extract diagram %s (id=%s)",
                    getattr(row, "attr_name", "?"),
                    getattr(row, "attr_diagram_id", "?"),
                    exc_info=True,
                )
        return diagrams

    def extract_by_id(self, diagram_id: int) -> NativeDiagram:
        """Return one diagram by its integer primary key."""
        TDiagram = _base.classes.t_diagram
        row = self.session.query(TDiagram).filter(TDiagram.attr_diagram_id == diagram_id).one()
        return self._extract_diagram(row)

    def extract_by_package(self, package_id: int) -> List[NativeDiagram]:
        """Return all diagrams belonging to the given package."""
        TDiagram = _base.classes.t_diagram
        rows = self.session.query(TDiagram).filter(TDiagram.attr_package_id == package_id).all()
        return [self._extract_diagram(r) for r in rows]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _extract_diagram(self, t_diagram) -> NativeDiagram:
        diagram_id: int = t_diagram.attr_diagram_id
        diagram_type = getattr(t_diagram, "attr_diagram_type", None)
        nodes = self._extract_nodes(diagram_id)
        connectors = self._extract_connectors(diagram_id)
        sequence_messages = self._extract_sequence_messages(diagram_id) if diagram_type == "Sequence" else []
        return NativeDiagram(
            diagram_id=diagram_id,
            name=t_diagram.attr_name,
            diagram_type=diagram_type,
            stereotype=getattr(t_diagram, "attr_stereotype", None),
            author=getattr(t_diagram, "attr_author", None),
            notes=getattr(t_diagram, "attr_notes", None),
            canvas_width=getattr(t_diagram, "attr_cx", 0) or 0,
            canvas_height=getattr(t_diagram, "attr_cy", 0) or 0,
            nodes=nodes,
            connectors=connectors,
            sequence_messages=sequence_messages,
        )

    def _extract_nodes(self, diagram_id: int) -> List[NativeDiagramNode]:
        TDiagramObjects = _base.classes.t_diagramobjects
        TObject = _base.classes.t_object
        TAttribute = _base.classes.t_attribute

        rows = (
            self.session.query(TDiagramObjects, TObject)
            .join(TObject, TDiagramObjects.attr_object_id == TObject.attr_object_id)
            .filter(TDiagramObjects.attr_diagram_id == diagram_id)
            .order_by(TDiagramObjects.attr_sequence.desc())  # higher sequence = lower z-order
            .all()
        )

        nodes: List[NativeDiagramNode] = []
        for t_do, t_obj in rows:
            object_id: int = t_obj.attr_object_id
            object_type: str = getattr(t_obj, "attr_object_type", "Class") or "Class"

            style = parse_object_style(getattr(t_do, "attr_objectstyle", None))

            # For Note objects, text lives in Name or Note fields
            note_text: Optional[str] = None
            note_connector_ref: Optional[int] = None
            if object_type == "Note":
                note_text = getattr(t_obj, "attr_note", None) or getattr(t_obj, "attr_name", None)
                # PDATA4 may contain 'idref1=<connector_id>;' linking note to a sequence message
                pdata4 = getattr(t_obj, "attr_pdata4", None) or ""
                for part in pdata4.split(";"):
                    if part.startswith("idref1="):
                        try:
                            note_connector_ref = int(part[7:].strip())
                        except ValueError:
                            pass
                        break

            # Load attributes (for Class / Part objects)
            attributes: List[NativeDiagramAttribute] = []
            if object_type in {"Class", "Part"}:
                attr_rows = (
                    self.session.query(TAttribute)
                    .filter(TAttribute.attr_object_id == object_id)
                    .order_by(TAttribute.attr_pos)
                    .all()
                )
                # Bulk-resolve Classifier → ea_guid in one query
                classifier_ids = [
                    int(getattr(a, "attr_classifier", 0) or 0) for a in attr_rows if getattr(a, "attr_classifier", 0)
                ]
                classifier_guid_map: Dict[int, str] = {}
                if classifier_ids:
                    guid_rows = (
                        self.session.query(
                            TObject.attr_object_id,
                            TObject.attr_ea_guid,
                        )
                        .filter(TObject.attr_object_id.in_(classifier_ids))
                        .all()
                    )
                    classifier_guid_map = {
                        row.attr_object_id: row.attr_ea_guid for row in guid_rows if row.attr_ea_guid
                    }

                # Fallback: resolve by type name for attrs where Classifier = 0.
                # EA often omits the Classifier FK (leaves it 0) and stores only
                # the text type name.  Skip well-known primitives — they have no
                # t_object row and can never be hyperlinked.
                _PRIMITIVES = frozenset(
                    {
                        "int",
                        "integer",
                        "long",
                        "short",
                        "byte",
                        "float",
                        "double",
                        "real",
                        "boolean",
                        "bool",
                        "string",
                        "char",
                        "character",
                        "void",
                        "any",
                        "object",
                    }
                )
                unresolved_type_names = {
                    (getattr(a, "attr_type", "") or "").strip()
                    for a in attr_rows
                    if not int(getattr(a, "attr_classifier", 0) or 0)
                    and (getattr(a, "attr_type", "") or "").strip()
                    and (getattr(a, "attr_type", "") or "").strip().lower() not in _PRIMITIVES
                }
                name_guid_map: Dict[str, str] = {}
                if unresolved_type_names:
                    name_rows = (
                        self.session.query(
                            TObject.attr_name,
                            TObject.attr_ea_guid,
                        )
                        .filter(TObject.attr_name.in_(unresolved_type_names))
                        .all()
                    )
                    # Keep first match per name (names should be unique within a model)
                    for row in name_rows:
                        if row.attr_name and row.attr_ea_guid:
                            name_guid_map.setdefault(row.attr_name, row.attr_ea_guid)

                for a in attr_rows:
                    classifier_id = int(getattr(a, "attr_classifier", 0) or 0)
                    type_name = (getattr(a, "attr_type", "") or "").strip()
                    type_guid = classifier_guid_map.get(classifier_id)
                    if type_guid is None and not classifier_id and type_name:
                        type_guid = name_guid_map.get(type_name)
                    attributes.append(
                        NativeDiagramAttribute(
                            name=getattr(a, "attr_name", "") or "",
                            type=type_name,
                            lower_bound=getattr(a, "attr_lowerbound", None),
                            upper_bound=getattr(a, "attr_upperbound", None),
                            position=getattr(a, "attr_pos", 0) or 0,
                            type_guid=type_guid,
                        )
                    )

            nodes.append(
                NativeDiagramNode(
                    object_id=object_id,
                    name=getattr(t_obj, "attr_name", "") or "",
                    object_type=object_type,
                    stereotype=getattr(t_obj, "attr_stereotype", None),
                    is_abstract=(getattr(t_obj, "attr_abstract", "0") or "0") == "1",
                    ea_guid=getattr(t_obj, "attr_ea_guid", None) or None,
                    note_text=note_text,
                    note_connector_ref=note_connector_ref,
                    rect_left=getattr(t_do, "attr_rectleft", 0) or 0,
                    rect_top=getattr(t_do, "attr_recttop", 0) or 0,
                    rect_right=getattr(t_do, "attr_rectright", 0) or 0,
                    rect_bottom=getattr(t_do, "attr_rectbottom", 0) or 0,
                    z_order=getattr(t_do, "attr_sequence", 0) or 0,
                    style=style,
                    attributes=attributes,
                )
            )

        return nodes

    def _extract_connectors(self, diagram_id: int) -> List[NativeDiagramConnector]:
        TDiagramLinks = _base.classes.t_diagramlinks
        TConnector = _base.classes.t_connector

        rows = (
            self.session.query(TDiagramLinks, TConnector)
            .join(TConnector, TDiagramLinks.attr_connectorid == TConnector.attr_connector_id)
            .filter(TDiagramLinks.attr_diagramid == diagram_id)
            .all()
        )

        connectors: List[NativeDiagramConnector] = []
        for t_dl, t_cn in rows:
            geometry = parse_link_geometry(
                getattr(t_dl, "attr_geometry", None),
                getattr(t_dl, "attr_path", None),
            )
            style = parse_link_style(getattr(t_dl, "attr_style", None))

            connectors.append(
                NativeDiagramConnector(
                    connector_id=t_cn.attr_connector_id,
                    connector_type=getattr(t_cn, "attr_connector_type", "Association") or "Association",
                    name=getattr(t_cn, "attr_name", None) or None,
                    stereotype=getattr(t_cn, "attr_stereotype", None) or None,
                    source_object_id=t_cn.attr_start_object_id,
                    target_object_id=t_cn.attr_end_object_id,
                    source_role=getattr(t_cn, "attr_sourcerole", None) or None,
                    target_role=getattr(t_cn, "attr_destrole", None) or None,
                    source_cardinality=getattr(t_cn, "attr_sourcecard", None) or None,
                    target_cardinality=getattr(t_cn, "attr_destcard", None) or None,
                    hidden=bool(getattr(t_dl, "attr_hidden", 0)),
                    geometry=geometry,
                    style=style,
                )
            )

        return connectors

    # ------------------------------------------------------------------
    # Sequence diagram messages (stored directly on t_connector.DiagramID)
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_pdata5_sy(pdata5: Optional[str]) -> int:
        """Extract ``SY`` value from PDATA5 geometry string; returns 0 if absent."""
        if not pdata5:
            return 0
        for part in pdata5.split(";"):
            if part.startswith("SY="):
                try:
                    return abs(int(part[3:].strip()))
                except ValueError:
                    pass
        return 0

    @staticmethod
    def _parse_pdata2_retval(pdata2: Optional[str]) -> Optional[str]:
        """Extract ``retval=…`` from PDATA2 string; returns None if void/empty."""
        if not pdata2:
            return None
        for part in pdata2.split(";"):
            if part.startswith("retval="):
                val = part[7:].strip()
                return val if val and val.lower() not in ("void", "") else None
        return None

    @staticmethod
    def _parse_styleex_params(styleex: Optional[str]) -> Optional[str]:
        """Extract ``paramvalues=…`` from StyleEx string; returns None if empty."""
        if not styleex:
            return None
        for part in styleex.split(";"):
            if part.startswith("paramvalues="):
                val = part[12:].strip()
                return val if val else None
        return None

    def _extract_sequence_messages(self, diagram_id: int) -> List[NativeSequenceMessage]:
        """Return sequence messages for *diagram_id* ordered by SeqNo."""
        TConnector = _base.classes.t_connector

        rows = (
            self.session.query(TConnector)
            .filter(
                TConnector.attr_diagramid == diagram_id,
                TConnector.attr_connector_type == "Sequence",
            )
            .order_by(TConnector.attr_seqno)
            .all()
        )

        messages: List[NativeSequenceMessage] = []
        for t_cn in rows:
            messages.append(
                NativeSequenceMessage(
                    connector_id=t_cn.attr_connector_id,
                    name=getattr(t_cn, "attr_name", None) or None,
                    stereotype=getattr(t_cn, "attr_stereotype", None) or None,
                    source_object_id=t_cn.attr_start_object_id,
                    target_object_id=t_cn.attr_end_object_id,
                    seq_no=getattr(t_cn, "attr_seqno", 0) or 0,
                    call_type=getattr(t_cn, "attr_pdata1", None) or None,
                    return_value=self._parse_pdata2_retval(getattr(t_cn, "attr_pdata2", None)),
                    param_values=self._parse_styleex_params(getattr(t_cn, "attr_styleex", None)),
                    activation_bar_height=self._parse_pdata5_sy(getattr(t_cn, "attr_pdata5", None)),
                    start_x=getattr(t_cn, "attr_ptstartx", 0) or 0,
                    start_y=getattr(t_cn, "attr_ptstarty", 0) or 0,
                    end_x=getattr(t_cn, "attr_ptendx", 0) or 0,
                    end_y=getattr(t_cn, "attr_ptendy", 0) or 0,
                )
            )

        return messages
