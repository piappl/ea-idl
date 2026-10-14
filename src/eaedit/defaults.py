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
TYPE_COLUMNS = {"t_object": "attr_object_type", "t_connector": "attr_connector_type", "t_xref": "attr_name"}


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
    ("t_xref", "Stereotypes"): Defaults(
        {"attr_visibility": "Public", "attr_partition": "0", "attr_supplier": "<none>"}, True
    ),
    # Verified empty by design: EA-made tag rows have no constant columns beyond the owner ref, name and value.
    ("t_objectproperties", "*"): Defaults({}, True),
    ("t_connectortag", "*"): Defaults({}, True),
    # nafv4.qea has no attribute tags to prove the shape against.
    ("t_attributetag", "*"): Defaults({}, False),
}

_MISSING = Defaults({}, False)


def defaults_for(table: str, type_value: str) -> Defaults:
    return DEFAULTS.get((table, type_value)) or DEFAULTS.get((table, "*")) or _MISSING


def new_guid() -> str:
    return "{" + str(uuid.uuid4()).upper() + "}"


def timestamp(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def new_record(session, table: str, values: dict[str, Any], kind_type: str = "*") -> Record:
    """A complete row for ``table``: NULL everywhere, then EA's defaults, then ``values``. Not yet put.

    The key column (``ea_guid``, or the table's GUID key such as ``XrefID``) is minted when not given.
    """
    columns = session.columns(table)
    unknown = sorted(set(values) - set(columns))
    if unknown:
        raise ValueError(f"{table} has no column(s) {', '.join(unknown)}")
    spec = session.working.tablemap.spec(table)
    if not isinstance(spec.key, GuidKey):
        raise ValueError(f"new_record supports GUID-keyed tables only, not {table}")
    found = defaults_for(table, kind_type)
    if found is _MISSING or (found.values and not found.verified):
        session.warn("unverified-default", f"no EA-verified defaults for {table} {kind_type}")
    row = dict.fromkeys(columns)
    row.update(found.values)
    row.update(values)
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
