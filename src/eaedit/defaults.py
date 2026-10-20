"""What EA writes into new rows: metaclass kinds, constant column values, GUIDs, timestamps, friendly field names.

Values come from EA-made rows in ``tests/data/nafv4.qea``. ``verified`` marks what a test proves against those rows;
anything else is a best guess and using it adds an ``unverified-default`` warning.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from eacore.records import Record
from eacore.tablemap import GuidKey
from eacore.translate import candidate_key
from eaedit.errors import InvalidOperationError


@dataclass(frozen=True)
class Kind:
    table: str
    type_column: str
    type_value: str
    extra: dict[str, Any] = field(default_factory=dict)
    verified: bool = False


def _element(type_value: str, verified: bool = False, **extra: Any) -> Kind:
    return Kind("t_object", "attr_object_type", type_value, extra, verified)


def _connector(type_value: str, verified: bool = False, **extra: Any) -> Kind:
    return Kind("t_connector", "attr_connector_type", type_value, extra, verified)


#: MDG metaclass name (``<Apply type=...>``) -> where and how EA stores it.
EA_KINDS: dict[str, Kind] = {
    "Class": _element("Class", True),
    "Package": _element("Package", True),
    "Part": _element("Part", True),
    "Note": _element("Note", True),
    "InteractionFragment": _element("InteractionFragment", True),
    "Object": _element("Object"),
    "Port": _element("Port"),
    "Interface": _element("Interface"),
    "Enumeration": _element("Enumeration"),
    "DataType": _element("DataType"),
    "Signal": _element("Signal"),
    "Component": _element("Component"),
    "Actor": _element("Actor"),
    "Activity": _element("Activity"),
    "Action": _element("Action"),
    "StateMachine": _element("StateMachine"),
    "Constraint": _element("Constraint"),
    "Requirement": _element("Requirement"),
    # EA stores a sequence-diagram lifeline as Object_Type "Sequence".
    "Lifeline": _element("Sequence"),
    "Association": _connector("Association", True),
    "Generalization": _connector("Generalization", True),
    "Abstraction": _connector("Abstraction", True),
    "NoteLink": _connector("NoteLink", True),
    # A sequence message: Connector_Type "Sequence" (nafv4.qea 'Message1').
    "Message": _connector("Sequence", True),
    "Dependency": _connector("Dependency"),
    "Realisation": _connector("Realisation"),
    "Realization": _connector("Realisation"),
    "Usage": _connector("Usage"),
    "Aggregation": _connector("Aggregation", attr_subtype="Weak"),
    "Composition": _connector("Aggregation", attr_subtype="Strong"),
    "InformationFlow": _connector("InformationFlow"),
    "ControlFlow": _connector("ControlFlow"),
    "ObjectFlow": _connector("ObjectFlow"),
    "Connector": _connector("Connector"),
}

#: Relationship metaclasses: an unknown one of these still belongs in t_connector.
CONNECTOR_NAMES = frozenset(
    {name for name, kind in EA_KINDS.items() if kind.table == "t_connector"}
    | {"Trace", "Nesting", "Assembly", "Delegate", "Extend", "Include", "Transition", "StateFlow", "Instantiation"}
)


def kind_for(metaclass: str) -> tuple[Kind, bool]:
    """``(kind, known)``; an unknown metaclass is stored under its own name, unverified."""
    kind = EA_KINDS.get(metaclass)
    if kind is not None:
        return kind, True
    if metaclass in CONNECTOR_NAMES:
        return _connector(metaclass), False
    return _element(metaclass), False


#: Column naming a row's kind, per table; the key of DEFAULTS entries for those tables.
TYPE_COLUMNS = {
    "t_object": "attr_object_type",
    "t_connector": "attr_connector_type",
    "t_xref": "attr_name",
    "t_diagram": "attr_diagram_type",
}


@dataclass(frozen=True)
class Defaults:
    values: dict[str, Any]
    verified: bool


# Constant non-NULL columns of EA-made rows. References EA leaves at 0 stay raw 0 in records.
_OBJECT = {
    "attr_diagram_id": 0,
    "attr_version": "1.0",
    "attr_complexity": "1",
    "attr_effort": 0,
    "attr_backcolor": -1,
    "attr_borderstyle": 0,
    "attr_fontcolor": -1,
    "attr_bordercolor": -1,
    "attr_status": "Proposed",
    "attr_abstract": "0",
    "attr_tagged": 0,
    "attr_gentype": "Java",
    "attr_phase": "1.0",
    "attr_scope": "Public",
    "attr_classifier": 0,
    "attr_isroot": 0,
    "attr_isleaf": 0,
    "attr_isspec": 0,
    "attr_isactive": 0,
}
_CONNECTOR = {
    "attr_direction": "Source -> Destination",
    "attr_sourceaccess": "Public",
    "attr_destaccess": "Public",
    "attr_sourcecontainment": "Unspecified",
    "attr_destcontainment": "Unspecified",
    "attr_sourceisaggregate": 0,
    "attr_destisaggregate": 0,
    "attr_sourceisordered": 0,
    "attr_destisordered": 0,
    "attr_headstyle": 0,
    "attr_linestyle": 0,
    "attr_isbold": 0,
    "attr_linecolor": -1,
    "attr_sourceisnavigable": 0,
    "attr_destisnavigable": 1,
    "attr_isroot": 0,
    "attr_isleaf": 0,
    "attr_sourcechangeable": "none",
    "attr_destchangeable": "none",
    "attr_sourcets": "instance",
    "attr_destts": "instance",
    "attr_target2": 0,
}
_DIAGRAM_FREE = {
    "attr_start_edge": 0,
    "attr_end_edge": 0,
    "attr_ptstartx": 0,
    "attr_ptstarty": 0,
    "attr_ptendx": 0,
    "attr_ptendy": 0,
    "attr_seqno": 0,
    "attr_routestyle": 3,
    "attr_diagramid": 0,
    "attr_pdata5": "SX=0;SY=0;EX=0;EY=0;",
}
_PLAIN_STYLE = {
    "attr_virtualinheritance": "0",
    "attr_sourcestyle": "Union=0;Derived=0;AllowDuplicates=0;",
    "attr_deststyle": "Union=0;Derived=0;AllowDuplicates=0;",
}
_NAVIGABLE_STYLE = {
    "attr_sourcestyle": "Union=0;Derived=0;AllowDuplicates=0;Owned=0;Navigable=Non-Navigable;",
    "attr_deststyle": "Union=0;Derived=0;AllowDuplicates=0;Owned=0;Navigable=Navigable;",
}

# Constant columns of hand-made diagrams. The page size is the value most hand-made Custom rows have (cx 776, cy 1126;
# the later P2 and p6 rows hold 791 x 1134). MDGDgm is set by the operation; SaveTag is omitted (EA fills it on save).
_DIAGRAM_PDATA = (
    "HideRel=0;ShowTags=0;ShowReqs=0;ShowCons=0;OpParams=1;ShowSN=0;ScalePI=0;PPgs.cx=0;PPgs.cy=0;PSize=9;ShowIcons=1;"
    "SuppCN=0;HideProps=0;HideParents=0;UseAlias=0;HideAtts=0;HideOps=0;HideStereo=0;HideEStereo=0;ShowRec=1;ShowRes=0;"
    "ShowShape=1;FormName=;"
)
_DIAGRAM_STYLEEX = (
    "ExcludeRTF=0;DocAll=0;HideQuals=0;AttPkg=1;ShowTests=0;ShowMaint=0;SuppressFOC=1;MatrixActive=0;SwimlanesActive=1;"
    "KanbanActive=0;MatrixLineWidth=1;MatrixLineClr=0;MatrixLocked=0;TConnectorNotation=UML 2.1;"
    "TExplicitNavigability=0;AdvancedElementProps=1;AdvancedFeatureProps=1;AdvancedConnectorProps=1;"
    "m_bElementClassifier=1;SPT=1;STBLDgm=;ShowNotes=0;VisibleAttributeDetail=0;ShowOpRetType=1;SuppressBrackets=0;"
    "SuppConnectorLabels=0;PrintPageHeadFoot=0;ShowAsList=0;SuppressedCompartments=;Theme=:119;"
)
# The hand-made sequence diagram (p6) adds its own margins and does not suppress folded operations (SuppressFOC=0).
_SEQUENCE_STYLEEX = _DIAGRAM_STYLEEX.replace(
    "SuppressFOC=1;", "SuppressFOC=0;INT_ARGS=;INT_RET=;INT_ATT=;SeqTopMargin=50;"
)
_DIAGRAM = {
    "attr_parentid": 0,
    "attr_version": "1.0",
    "attr_showdetails": 0,
    "attr_attpub": 1,
    "attr_attpri": 1,
    "attr_attpro": 1,
    "attr_orientation": "P",
    "attr_cx": 776,
    "attr_cy": 1126,
    "attr_scale": 100,
    "attr_showforeign": 1,
    "attr_showborder": 1,
    "attr_showpackagecontents": 1,
    "attr_pdata": _DIAGRAM_PDATA,
    "attr_locked": 0,
    "attr_swimlanes": (
        "locked=false;orientation=0;width=0;inbar=false;names=false;color=-1;bold=false;fcol=0;tcol=-1;ofCol=-1;"
        "ufCol=-1;hl=1;ufh=0;hh=0;cls=0;bw=0;hli=0;bro=0;"
    ),
    "attr_styleex": _DIAGRAM_STYLEEX,
}

DEFAULTS: dict[tuple[str, str], Defaults] = {
    # Sub-packages; the root "Model" row differs (Version NULL, Batch* 0) but is never created.
    ("t_package", "*"): Defaults(
        {"attr_iscontrolled": 0, "attr_version": "1.0", "attr_protected": 0, "attr_usedtd": 0, "attr_logxml": 0},
        True,
    ),
    ("t_object", "Package"): Defaults({**_OBJECT, "attr_ntype": 0, "attr_parentid": 0, "attr_borderwidth": -1}, True),
    ("t_object", "Class"): Defaults(
        {**_OBJECT, "attr_ntype": 0, "attr_parentid": 0, "attr_borderwidth": 1, "attr_pdata4": "0"}, True
    ),
    # Parts sit under their owning element (ParentID); their BorderWidth varies (1 or -1).
    ("t_object", "Part"): Defaults({**_OBJECT, "attr_ntype": 0, "attr_borderwidth": -1}, True),
    ("t_object", "Note"): Defaults(
        {**_OBJECT, "attr_ntype": 0, "attr_parentid": 0, "attr_borderwidth": -1, "attr_gentype": "<none>"}, True
    ),
    ("t_object", "*"): Defaults({**_OBJECT, "attr_ntype": 0, "attr_parentid": 0, "attr_borderwidth": -1}, False),
    ("t_connector", "Association"): Defaults({**_CONNECTOR, **_DIAGRAM_FREE, **_NAVIGABLE_STYLE}, True),
    ("t_connector", "Abstraction"): Defaults({**_CONNECTOR, **_DIAGRAM_FREE, **_PLAIN_STYLE, **_NAVIGABLE_STYLE}, True),
    ("t_connector", "Generalization"): Defaults({**_CONNECTOR, **_DIAGRAM_FREE, **_PLAIN_STYLE}, True),
    ("t_connector", "NoteLink"): Defaults({**_CONNECTOR, **_DIAGRAM_FREE, **_PLAIN_STYLE}, True),
    # Messages live on a sequence diagram: route style 1, ordered by SeqNo, PDATA1 is the call kind.
    ("t_connector", "Sequence"): Defaults(
        {
            **_CONNECTOR,
            **_NAVIGABLE_STYLE,
            "attr_virtualinheritance": "0",
            "attr_routestyle": 1,
            "attr_pdata1": "Asynchronous",
            "attr_pdata3": "Call",
            "attr_pdata4": "0",
        },
        True,
    ),
    ("t_connector", "*"): Defaults({**_CONNECTOR, **_DIAGRAM_FREE, **_PLAIN_STYLE}, False),
    ("t_attribute", "*"): Defaults(
        {
            "attr_scope": "Public",
            "attr_containment": "Not Specified",
            "attr_isstatic": 0,
            "attr_iscollection": 0,
            "attr_isordered": 0,
            "attr_allowduplicates": 0,
            "attr_lowerbound": "1",
            "attr_upperbound": "1",
            "attr_styleex": "volatile=0;",
        },
        True,
    ),
    ("t_diagram", "Custom"): Defaults(_DIAGRAM, True),
    ("t_diagram", "Sequence"): Defaults(
        {**_DIAGRAM, "attr_cx": 791, "attr_cy": 1134, "attr_styleex": _SEQUENCE_STYLEEX}, True
    ),
    # nafv4.qea has no hand-made UML (Class ...) diagram.
    ("t_diagram", "*"): Defaults(_DIAGRAM, False),
    # ObjectStyle (with its DUID) is built by the diagram operations.
    ("t_diagramobjects", "*"): Defaults({}, True),
    ("t_diagramlinks", "*"): Defaults({"attr_hidden": 0}, True),
    ("t_xref", "Stereotypes"): Defaults(
        {"attr_visibility": "Public", "attr_partition": "0", "attr_supplier": "<none>"}, True
    ),
    # CustomProperties rows differ by owner (diagram settings, a Part's isReference); callers give every column.
    ("t_xref", "CustomProperties"): Defaults({"attr_visibility": "Public", "attr_partition": "0"}, True),
    # Verified empty by design: EA-made tag rows have no constant columns beyond the owner ref, name and value.
    ("t_objectproperties", "*"): Defaults({}, True),
    ("t_connectortag", "*"): Defaults({}, True),
    # nafv4.qea has no attribute tags to prove the shape against.
    ("t_attributetag", "*"): Defaults({}, False),
}

_MISSING = Defaults({}, False)

#: Value EA stores in a reference column with nothing referenced, per ``(table, column, type)``; type ``"*"`` is any.
#: ``verified`` means EA-made rows of that type in nafv4.qea hold this value; deletes reset dangling references to it.
UNSET: dict[tuple[str, str, str], tuple[Any, bool]] = {
    ("t_attribute", "attr_classifier", "*"): ("0", True),
    # nafv4.qea has no operations; assumed to match attributes.
    ("t_operation", "attr_classifier", "*"): ("0", False),
    ("t_operationparams", "attr_classifier", "*"): ("0", False),
    ("t_operation", "attr_behaviour", "*"): (None, False),
    ("t_object", "attr_classifier", "*"): (0, True),
    ("t_object", "attr_classifier_guid", "*"): (None, True),
    ("t_object", "attr_diagram_id", "*"): (0, True),
    ("t_object", "attr_parentid", "*"): (0, True),
    ("t_object", "attr_pdata1", "Part"): (None, True),
    ("t_object", "attr_pdata2", "Note"): (None, True),
    ("t_object", "attr_pdata4", "Note"): (None, True),
    ("t_object", "attr_pdata4", "Class"): ("0", True),
    ("t_connector", "attr_diagramid", "*"): (0, True),
    ("t_connector", "attr_pdata1", "Association"): (None, True),
    ("t_diagram", "attr_parentid", "*"): (0, True),
    # Stereotype and element CustomProperties rows use '<none>'; diagram CustomProperties rows leave it NULL.
    ("t_xref", "attr_supplier", "*"): ("<none>", True),
}


def unset_value(table: str, column: str, values: dict[str, Any]) -> tuple[Any, bool]:
    """``(value, verified)`` EA stores in ``column`` of a ``table`` row like ``values`` when it references nothing."""
    type_value = values.get(TYPE_COLUMNS.get(table, ""), "*") if table in ("t_object", "t_connector") else "*"
    found = UNSET.get((table, column, type_value)) or UNSET.get((table, column, "*"))
    return found if found is not None else (None, False)


def defaults_for(table: str, type_value: str) -> Defaults:
    return DEFAULTS.get((table, type_value)) or DEFAULTS.get((table, "*")) or _MISSING


def new_guid() -> str:
    return "{" + str(uuid.uuid4()).upper() + "}"


def timestamp(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


#: ObjectStyle text after ``DUID=...;`` per object kind, as on the hand-made diagrams in nafv4.qea.
OBJECT_STYLES: dict[str, str] = {
    "Class": "HideIcon=0;",
    "Part": "HideIcon=0;",
    "Note": "",
    "InteractionFragment": "",
    # A Part or object shown on a sequence diagram (the hand-made p6 lifelines).
    "Lifeline": "NSL=0;BCol=-1;BFol=-1;LCol=-1;LWth=-1;fontsz=0;bold=0;black=0;italic=0;ul=0;charset=0;pitch=0;HideIcon=0;",
    "*": "HideIcon=0;",
}


def link_style(source_duid: str, target_duid: str) -> str:
    """``t_diagramlinks.Style`` of a fresh link, as on the hand-made L7 rows."""
    return f"Mode=3;EOID={target_duid};SOID={source_duid};Color=-1;LWidth=0;"


def link_geometry(edge: int) -> str:
    """``t_diagramlinks.Geometry`` of a fresh link, as on the hand-made L7 rows."""
    return f"SX=0;SY=0;EX=0;EY=0;EDGE={edge};$LLB=;LLT=;LMT=;LMB=;LRT=;LRB=;IRHS=;ILHS=;"


def _layered(session, table: str, values: dict[str, Any], kind_type: str):
    """``(columns, spec, row)``: NULL everywhere, then EA's defaults, then ``values``; warns on unverified defaults."""
    columns = session.columns(table)
    unknown = sorted(set(values) - set(columns))
    if unknown:
        raise ValueError(f"{table} has no column(s) {', '.join(unknown)}")
    spec = session.working.tablemap.spec(table)
    found = defaults_for(table, kind_type)
    if found is _MISSING or (found.values and not found.verified):
        session.warn("unverified-default", f"no EA-verified defaults for {table} {kind_type}")
    row = dict.fromkeys(columns)
    row.update(found.values)
    row.update(values)
    return spec, row


def new_row(session, table: str, values: dict[str, Any], kind_type: str = "*") -> Record:
    """A complete row for a table not keyed by GUID (diagram objects and links), layered like ``new_record``.

    The key comes from ``values`` (a DUID in ObjectStyle, or the natural key columns). Not yet put.
    """
    spec, row = _layered(session, table, values, kind_type)
    key = candidate_key(spec, row)
    if key is None:
        raise ValueError(f"{table} row has no key")
    return Record(table, key, row)


def new_record(session, table: str, values: dict[str, Any], kind_type: str = "*") -> Record:
    """A complete row for ``table``: NULL everywhere, then EA's defaults, then ``values``. Not yet put.

    The key column (``ea_guid``, or the table's GUID key such as ``XrefID``) is minted when not given.
    """
    if not isinstance(session.working.tablemap.spec(table).key, GuidKey):
        raise ValueError(f"new_record supports GUID-keyed tables only, not {table}")
    spec, row = _layered(session, table, values, kind_type)
    if not row.get(spec.key.column):
        row[spec.key.column] = session.new_guid()
    return Record(table, row[spec.key.column], row)


#: Friendly field name -> column key, per table. Stereotypes are not fields: use add/remove_stereotype.
FIELDS: dict[str, dict[str, str]] = {
    "t_object": {
        "name": "attr_name",
        "alias": "attr_alias",
        "notes": "attr_note",
        "status": "attr_status",
        "version": "attr_version",
        "phase": "attr_phase",
        "scope": "attr_scope",
        "complexity": "attr_complexity",
        "abstract": "attr_abstract",
        "author": "attr_author",
        # Inside EA: Element.Keywords is stored in PDATA5.
        "keywords": "attr_pdata5",
        "multiplicity": "attr_multiplicity",
        "leaf": "attr_isleaf",
        "root": "attr_isroot",
        "active": "attr_isactive",
        "gentype": "attr_gentype",
    },
    # The alias and other element properties of a package live on its t_object twin (FIELDS["t_object"]).
    "t_package": {"name": "attr_name", "notes": "attr_notes", "version": "attr_version"},
    "t_attribute": {
        "name": "attr_name",
        "notes": "attr_notes",
        "type": "attr_type",
        "default": "attr_default",
        "lower": "attr_lowerbound",
        "upper": "attr_upperbound",
        "scope": "attr_scope",
        "static": "attr_isstatic",
        "const": "attr_const",
        "collection": "attr_iscollection",
        "ordered": "attr_isordered",
        "containment": "attr_containment",
    },
    "t_connector": {
        "name": "attr_name",
        "notes": "attr_notes",
        "direction": "attr_direction",
        "source_role": "attr_sourcerole",
        "target_role": "attr_destrole",
        "source_card": "attr_sourcecard",
        "target_card": "attr_destcard",
        "source_access": "attr_sourceaccess",
        "target_access": "attr_destaccess",
        "source_containment": "attr_sourcecontainment",
        "target_containment": "attr_destcontainment",
        "source_role_note": "attr_sourcerolenote",
        "target_role_note": "attr_destrolenote",
    },
    "t_diagram": {
        "name": "attr_name",
        "notes": "attr_notes",
        "page_width": "attr_cx",
        "page_height": "attr_cy",
        "orientation": "attr_orientation",
    },
}

#: Boolean columns, with the representation EA uses there ("0"/"1" text or 0/1 integer).
_BOOLEANS: dict[tuple[str, str], type] = {
    ("t_object", "attr_abstract"): str,
    ("t_object", "attr_isleaf"): int,
    ("t_object", "attr_isroot"): int,
    ("t_object", "attr_isactive"): int,
    ("t_attribute", "attr_isstatic"): int,
    ("t_attribute", "attr_const"): int,
    ("t_attribute", "attr_iscollection"): int,
    ("t_attribute", "attr_isordered"): int,
}


def apply_fields(table: str, values: dict[str, Any], fields: dict[str, Any]) -> dict[str, Any]:
    """``values`` updated with ``fields`` given by friendly name; booleans written as EA stores them."""
    allowed = FIELDS.get(table, {})
    result = dict(values)
    for name, value in fields.items():
        if name == "stereotype":
            raise InvalidOperationError("stereotypes are not a field: use add_stereotype / remove_stereotype")
        column = allowed.get(name)
        if column is None:
            raise InvalidOperationError(f"unknown field {name!r} for {table}; allowed: {', '.join(sorted(allowed))}")
        kind = _BOOLEANS.get((table, column))
        if kind is not None and isinstance(value, bool):
            value = str(int(value)) if kind is str else int(value)
        result[column] = value
    return result
