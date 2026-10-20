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
from eacore.embedded import parse_stereotypes
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


def _view_id(style_ex: str) -> Optional[str]:
    """``MDGDgm=<profile>::<view> - <title>`` -> the text before `` - `` in the view name."""
    value = _parse_kv(style_ex).get("MDGDgm", "")
    if "::" not in value:
        return None
    view = value.split("::", 1)[1]
    if " - " not in view:
        return None
    return view.split(" - ", 1)[0].strip() or None


def parse_object_style(raw: Optional[str]) -> NativeObjectStyle:
    """
    Decode an EA ``ObjectStyle`` string into :class:`NativeObjectStyle`.

    Format: ``KEY=VALUE;KEY=VALUE;…``

    Known keys::

        DUID       — diagram-unique placement ID
        HideIcon   — 0/1
        NSL        — (unknown flag)
        BCol       — background colour (Windows COLORREF int, -1 = default)
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
        show_foreign = bool(int(getattr(t_diagram, "attr_showforeign", 1) or 0))
        style_ex = getattr(t_diagram, "attr_styleex", None) or ""
        pdata = getattr(t_diagram, "attr_pdata", None) or ""
        show_fqn = _parse_kv(style_ex).get("ShowFQN") == "1"
        hide_attributes = _parse_kv(pdata).get("HideAtts") == "1"
        nodes = self._extract_nodes(
            diagram_id, getattr(t_diagram, "attr_package_id", 0) or 0, show_foreign=show_foreign, show_fqn=show_fqn
        )
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
            show_foreign=show_foreign,
            show_fqn=show_fqn,
            hide_attributes=hide_attributes,
            view_id=_view_id(style_ex),
            nodes=nodes,
            connectors=connectors,
            sequence_messages=sequence_messages,
        )

    def _extract_nodes(
        self, diagram_id: int, diagram_package_id: int = 0, show_foreign: bool = True, show_fqn: bool = False
    ) -> List[NativeDiagramNode]:
        TDiagramObjects = _base.classes.t_diagramobjects
        TObject = _base.classes.t_object
        TPackage = _base.classes.t_package
        TAttribute = _base.classes.t_attribute
        TConnector = _base.classes.t_connector
        TXref = _base.classes.t_xref

        rows = (
            self.session.query(TDiagramObjects, TObject)
            .join(TObject, TDiagramObjects.attr_object_id == TObject.attr_object_id)
            .filter(TDiagramObjects.attr_diagram_id == diagram_id)
            .order_by(TDiagramObjects.attr_sequence.desc())  # higher sequence = lower z-order
            .all()
        )

        object_ids = [t_obj.attr_object_id for _, t_obj in rows]
        package_ids = {t_obj.attr_package_id for _, t_obj in rows if t_obj.attr_package_id}
        package_names = (
            {
                package_id: name
                for package_id, name in self.session.query(TPackage.attr_package_id, TPackage.attr_name)
                .filter(TPackage.attr_package_id.in_(package_ids))
                .all()
            }
            if package_ids
            else {}
        )
        package_paths: Dict[int, str] = {}
        if show_fqn and package_ids:
            parents: Dict[int, Tuple[int, str]] = {}
            pending = set(package_ids)
            while pending:
                package_rows = (
                    self.session.query(
                        TPackage.attr_package_id,
                        TPackage.attr_parent_id,
                        TPackage.attr_name,
                    )
                    .filter(TPackage.attr_package_id.in_(pending))
                    .all()
                )
                pending = set()
                for package_id, parent_id, name in package_rows:
                    parents[package_id] = (parent_id or 0, name or "")
                    if parent_id and parent_id not in parents:
                        pending.add(parent_id)
            for package_id in package_ids:
                names = []
                current = package_id
                while current in parents:
                    parent, name = parents[current]
                    if parent == 0:
                        break  # EA omits its outermost Model package.
                    names.append(name)
                    current = parent
                package_paths[package_id] = "::".join(reversed(names))
        nested_parent_ids = {
            t_obj.attr_parentid
            for _, t_obj in rows
            if getattr(t_obj, "attr_object_type", None) == "Class" and getattr(t_obj, "attr_parentid", 0)
        }
        nested_parent_names = (
            {
                object_id: name
                for object_id, name, object_type in self.session.query(
                    TObject.attr_object_id, TObject.attr_name, TObject.attr_object_type
                )
                .filter(TObject.attr_object_id.in_(nested_parent_ids))
                .all()
                if object_type == "Class" and name
            }
            if nested_parent_ids
            else {}
        )
        parent_names: Dict[int, str] = {}
        if object_ids:
            parent_rows = (
                self.session.query(TConnector.attr_start_object_id, TConnector.attr_end_object_id, TObject.attr_name)
                .join(TObject, TConnector.attr_end_object_id == TObject.attr_object_id)
                .filter(TConnector.attr_connector_type == "Generalization")
                .filter(TConnector.attr_start_object_id.in_(object_ids))
                .all()
            )
            for child_id, parent_id, parent_name in parent_rows:
                if parent_id not in object_ids:
                    parent_names.setdefault(child_id, parent_name)

        nodes: List[NativeDiagramNode] = []
        for t_do, t_obj in rows:
            object_id: int = t_obj.attr_object_id
            object_type: str = getattr(t_obj, "attr_object_type", "Class") or "Class"

            style = parse_object_style(getattr(t_do, "attr_objectstyle", None))

            # For Note objects, text can live in Name or Note. Classes carry
            # documentation in the same Note column.
            note_text: Optional[str] = getattr(t_obj, "attr_note", None) or None
            note_connector_ref: Optional[int] = None
            legend_title: Optional[str] = None
            legend_entries: List[Tuple[str, str]] = []
            legend_is_line = False
            legend_background_color: Optional[str] = None
            legend_text_color: Optional[str] = None
            classifier_name: Optional[str] = None
            interaction_operands: List[Tuple[str, int]] = []
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
            elif object_type == "InteractionFragment":
                xref = (
                    self.session.query(TXref)
                    .filter(TXref.attr_client == getattr(t_obj, "attr_ea_guid", None))
                    .filter(TXref.attr_name == "Partitions")
                    .first()
                )
                if xref is not None:
                    for encoded in re.findall(r"@PAR;(.*?)@ENDPAR;", xref.attr_description or "", re.DOTALL):
                        values = _parse_kv(encoded)
                        if values.get("Size", "").isdigit():
                            interaction_operands.append((values.get("Name", ""), int(values["Size"])))
                    # EA stores the bottom partition first in t_xref.
                    interaction_operands.reverse()
            elif object_type == "Text" and getattr(t_obj, "attr_ntype", 0) == 76:
                xref = (
                    self.session.query(TXref)
                    .filter(TXref.attr_client == getattr(t_obj, "attr_ea_guid", None))
                    .filter(TXref.attr_name == "CustomProperties")
                    .first()
                )
                if xref is not None:
                    for prop in re.findall(r"@PROP=(.*?)@ENDPROP;", xref.attr_description or "", re.DOTALL):
                        name_match = re.search(r"@NAME=(.*?)@ENDNAME;", prop)
                        color_match = re.search(r"#Back_Ground_Color#=(\d+);", prop)
                        line_color_match = re.search(r"#Pen_Color#=(\d+);", prop)
                        title_match = re.search(r"#TITLE#=(.*?);", prop)
                        if title_match:
                            legend_title = title_match.group(1)
                            background_match = re.search(r"#BACKGROUNDCOLOR#=(\d+);", prop)
                            text_match = re.search(r"#FONTCOLOR#=(\d+);", prop)
                            if background_match:
                                color = int(background_match.group(1))
                                legend_background_color = (
                                    f"#{color & 255:02x}{color >> 8 & 255:02x}{color >> 16 & 255:02x}"
                                )
                            if text_match:
                                color = int(text_match.group(1))
                                legend_text_color = f"#{color & 255:02x}{color >> 8 & 255:02x}{color >> 16 & 255:02x}"
                        elif name_match and color_match:
                            if "LEGEND_LINESTYLE" in prop:
                                legend_is_line = True
                            color = int(
                                (line_color_match if legend_is_line and line_color_match else color_match).group(1)
                            )
                            legend_entries.append(
                                (
                                    name_match.group(1),
                                    f"#{color & 255:02x}{color >> 8 & 255:02x}{color >> 16 & 255:02x}",
                                )
                            )

            stereo_xref = (
                self.session.query(TXref)
                .filter(TXref.attr_client == getattr(t_obj, "attr_ea_guid", None))
                .filter(TXref.attr_name == "Stereotypes")
                .first()
            )
            try:
                stereotypes = [s.name for s in parse_stereotypes(stereo_xref.attr_description)] if stereo_xref else []
            except ValueError:
                stereotypes = []

            if object_type == "Part":
                classifier_id = getattr(t_obj, "attr_classifier", 0) or 0
                classifier_guid = getattr(t_obj, "attr_pdata1", None)
                if classifier_id:
                    classifier = (
                        self.session.query(TObject.attr_name).filter(TObject.attr_object_id == classifier_id).first()
                    )
                    classifier_name = classifier[0] if classifier else None
                elif classifier_guid:
                    classifier = (
                        self.session.query(TObject.attr_name).filter(TObject.attr_ea_guid == classifier_guid).first()
                    )
                    classifier_name = classifier[0] if classifier else None

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
                            visibility=getattr(a, "attr_scope", None) or None,
                            stereotype=getattr(a, "attr_stereotype", None) or None,
                            ea_guid=getattr(a, "attr_ea_guid", None) or None,
                            type_guid=type_guid,
                        )
                    )
                if style.show_inherited_attrs:
                    # AttInh is a diagram-object setting. Keep the inherited
                    # fields and their owner so EA's grouped compartments can
                    # be reproduced without changing the model's own fields.
                    ancestor_id = object_id
                    seen_ancestors = {object_id}
                    depth = 0
                    while True:
                        parent = (
                            self.session.query(TConnector.attr_end_object_id, TObject.attr_name)
                            .join(TObject, TConnector.attr_end_object_id == TObject.attr_object_id)
                            .filter(TConnector.attr_connector_type == "Generalization")
                            .filter(TConnector.attr_start_object_id == ancestor_id)
                            .order_by(TConnector.attr_connector_id)
                            .first()
                        )
                        if parent is None or parent[0] in seen_ancestors:
                            break
                        ancestor_id, ancestor_name = parent
                        seen_ancestors.add(ancestor_id)
                        depth += 1
                        inherited_rows = (
                            self.session.query(TAttribute)
                            .filter(TAttribute.attr_object_id == ancestor_id)
                            .order_by(TAttribute.attr_pos)
                            .all()
                        )
                        for a in inherited_rows:
                            classifier_id = int(getattr(a, "attr_classifier", 0) or 0)
                            type_guid = None
                            if classifier_id:
                                type_row = (
                                    self.session.query(TObject.attr_ea_guid)
                                    .filter(
                                        TObject.attr_object_id == classifier_id,
                                    )
                                    .first()
                                )
                                type_guid = type_row[0] if type_row else None
                            attributes.append(
                                NativeDiagramAttribute(
                                    name=getattr(a, "attr_name", "") or "",
                                    type=(getattr(a, "attr_type", "") or "").strip(),
                                    lower_bound=getattr(a, "attr_lowerbound", None),
                                    upper_bound=getattr(a, "attr_upperbound", None),
                                    position=getattr(a, "attr_pos", 0) or 0,
                                    visibility=getattr(a, "attr_scope", None) or None,
                                    stereotype=getattr(a, "attr_stereotype", None) or None,
                                    inherited_from=ancestor_name,
                                    inheritance_depth=depth,
                                    ea_guid=getattr(a, "attr_ea_guid", None) or None,
                                    type_guid=type_guid,
                                )
                            )
                # EA's class compartment is alphabetic even when t_attribute
                # Pos values are duplicated or stale.
                attributes.sort(key=lambda a: (a.inheritance_depth, a.name.casefold(), a.name))

            display_context = None
            if object_type == "Class":
                display_context = nested_parent_names.get(getattr(t_obj, "attr_parentid", 0))
            if (
                display_context is None
                and show_foreign
                and t_obj.attr_package_id != diagram_package_id
                and object_type in ("Class", "Part")
            ):
                display_context = package_names.get(t_obj.attr_package_id)
            foreign_package_path = (
                package_paths.get(t_obj.attr_package_id)
                if show_fqn
                and show_foreign
                and t_obj.attr_package_id != diagram_package_id
                and object_type in ("Class", "Part")
                else None
            )

            nodes.append(
                NativeDiagramNode(
                    object_id=object_id,
                    parent_object_id=getattr(t_obj, "attr_parentid", 0) or 0,
                    name=getattr(t_obj, "attr_name", "") or "",
                    object_type=object_type,
                    ntype=getattr(t_obj, "attr_ntype", 0) or 0,
                    stereotype=getattr(t_obj, "attr_stereotype", None),
                    stereotypes=stereotypes,
                    is_abstract=(getattr(t_obj, "attr_abstract", "0") or "0") == "1",
                    parent_name=parent_names.get(object_id),
                    classifier_name=classifier_name,
                    display_context=display_context,
                    foreign_package_path=foreign_package_path,
                    ea_guid=getattr(t_obj, "attr_ea_guid", None) or None,
                    note_text=note_text,
                    legend_title=legend_title,
                    legend_entries=legend_entries,
                    legend_is_line=legend_is_line,
                    legend_background_color=legend_background_color,
                    legend_text_color=legend_text_color,
                    interaction_operands=interaction_operands,
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

        # EA draws every connector whose two ends are on the diagram, even without a
        # t_diagramlinks row (as the elements-only diagrams eaedit writes); those get default geometry.
        TDiagramObjects = _base.classes.t_diagramobjects
        linked_ids = {t_cn.attr_connector_id for _, t_cn in rows}
        on_diagram = [
            r[0]
            for r in self.session.query(TDiagramObjects.attr_object_id).filter(
                TDiagramObjects.attr_diagram_id == diagram_id
            )
        ]
        unlinked = (
            self.session.query(TConnector)
            .filter(TConnector.attr_start_object_id.in_(on_diagram))
            .filter(TConnector.attr_end_object_id.in_(on_diagram))
            .filter(sqlalchemy.or_(TConnector.attr_diagramid.is_(None), TConnector.attr_diagramid == 0))
            .order_by(TConnector.attr_connector_id)
            .all()
            if on_diagram
            else []
        )
        rows = list(rows) + [(None, t_cn) for t_cn in unlinked if t_cn.attr_connector_id not in linked_ids]

        connectors: List[NativeDiagramConnector] = []
        for t_dl, t_cn in rows:
            geometry = parse_link_geometry(
                getattr(t_dl, "attr_geometry", None),
                getattr(t_dl, "attr_path", None),
            )
            style = parse_link_style(getattr(t_dl, "attr_style", None))
            style_ex = getattr(t_cn, "attr_styleex", None) or ""
            source_feature = re.search(r"(?:^|;)LFSP=(\{[^}]+\})([LR]);", style_ex)
            target_feature = re.search(r"(?:^|;)LFEP=(\{[^}]+\})([LR]);", style_ex)
            source_nav = re.search(r"(?:^|;)Navigable=([^;]+)", getattr(t_cn, "attr_sourcestyle", None) or "")
            target_nav = re.search(r"(?:^|;)Navigable=([^;]+)", getattr(t_cn, "attr_deststyle", None) or "")
            pdata1 = getattr(t_cn, "attr_pdata1", None) or ""
            association_class_id = int(pdata1) if pdata1.isdecimal() else None

            connectors.append(
                NativeDiagramConnector(
                    connector_id=t_cn.attr_connector_id,
                    connector_type=getattr(t_cn, "attr_connector_type", "Association") or "Association",
                    ea_guid=getattr(t_cn, "attr_ea_guid", None) or None,
                    name=getattr(t_cn, "attr_name", None) or None,
                    stereotype=getattr(t_cn, "attr_stereotype", None) or None,
                    top_mid_label=getattr(t_cn, "attr_top_mid_label", None) or None,
                    bottom_mid_label=getattr(t_cn, "attr_btm_mid_label", None) or None,
                    transition_event=pdata1 if getattr(t_cn, "attr_connector_type", None) == "StateFlow" else None,
                    source_object_id=t_cn.attr_start_object_id,
                    target_object_id=t_cn.attr_end_object_id,
                    direction=getattr(t_cn, "attr_direction", None) or None,
                    source_navigability=source_nav.group(1) if source_nav else None,
                    target_navigability=target_nav.group(1) if target_nav else None,
                    head_style=getattr(t_cn, "attr_headstyle", 0) or 0,
                    line_style=getattr(t_cn, "attr_linestyle", 0) or 0,
                    source_is_aggregate=getattr(t_cn, "attr_sourceisaggregate", 0) or 0,
                    target_is_aggregate=getattr(t_cn, "attr_destisaggregate", 0) or 0,
                    source_feature_guid=source_feature.group(1) if source_feature else None,
                    source_feature_side=source_feature.group(2) if source_feature else None,
                    target_feature_guid=target_feature.group(1) if target_feature else None,
                    target_feature_side=target_feature.group(2) if target_feature else None,
                    association_class_object_id=association_class_id,
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
