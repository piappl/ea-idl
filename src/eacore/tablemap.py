"""Declarative map of EA tables: identity, references and ownership.

Facts and citations: docs/superpowers/specs/2026-10-14-eacore-reference-map.md.
Rule of thumb: EA's data is ground truth. When an EA-made file breaks a rule, the rule is wrong.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

Row = dict[str, Any]
Predicate = Callable[[Row], bool]

#: Values EA uses for "no reference".
NOTHING: tuple = (None, "", 0, "0")


@dataclass(frozen=True)
class GuidKey:
    column: str


@dataclass(frozen=True)
class NaturalKey:
    columns: tuple[str, ...]


@dataclass(frozen=True)
class DuidKey:
    """``t_diagramobjects``: (diagram, DUID from ObjectStyle); falls back to (diagram, element)."""

    diagram: str
    style: str
    element: str


@dataclass(frozen=True)
class ContentKey:
    """Weak identity: the row's values themselves (lookup tables, unmapped tables)."""


KeyKind = GuidKey | NaturalKey | DuidKey | ContentKey


@dataclass(frozen=True)
class RefRule:
    """Column holding file-local integer ID(s) of rows in ``target``.

    ``encoding``: ``"int"`` (INTEGER column), ``"text"`` (ID stored as text) or ``"pattern"``
    (IDs inside text; ``pattern`` is a regex whose group 1 is one ID). Rules for the same column
    are tried in order; the first whose ``when`` holds and whose value decodes wins.
    """

    column: str
    target: str
    encoding: str = "int"
    when: Predicate | None = None
    null: tuple = NOTHING
    pattern: str | None = None


@dataclass(frozen=True)
class GuidRefRule:
    """Column holding the GUID of a record in one of ``targets``. Kept as text; checked by integrity."""

    column: str
    targets: tuple[str, ...]
    when: Predicate | None = None
    sentinels: tuple = (None, "", "<none>")


@dataclass(frozen=True)
class EmbeddedGuidRule:
    """GUIDs inside free text (``pattern`` group 1). Only the integrity checker uses these."""

    column: str
    pattern: str
    targets: tuple[str, ...]


@dataclass(frozen=True)
class LiteralRule:
    """Documents that ``column`` holds a plain value (not a reference) when ``when`` holds."""

    column: str
    when: Predicate | None = None


Rule = RefRule | GuidRefRule | EmbeddedGuidRule | LiteralRule


@dataclass(frozen=True)
class TableSpec:
    name: str
    key: KeyKind
    rules: tuple[Rule, ...] = ()
    #: Column leading to the parent record: a ``Ref``, or GUID text when ``owner_is_guid``.
    owner: str | None = None
    owner_is_guid: bool = False

    def encoding_for(self, column: str, target: str) -> str:
        """Encoding used to write a plain ``Ref`` back into ``column``."""
        for rule in self.rules:
            if (
                isinstance(rule, RefRule)
                and rule.column == column
                and rule.target == target
                and rule.encoding in ("int", "text")
            ):
                return rule.encoding
        raise KeyError(f"{self.name}.{column} has no int/text reference rule to {target}")


class TableMap:
    def __init__(self, specs, lookup_tables=(), volatile=()) -> None:
        self._specs: dict[str, TableSpec] = {spec.name: spec for spec in specs}
        self.lookup_tables = frozenset(lookup_tables)
        #: (table, column) pairs EA rewrites on every save; filled from history mining.
        self.volatile: frozenset[tuple[str, str]] = frozenset(volatile)
        for spec in self._specs.values():
            for rule in spec.rules:
                if isinstance(rule, RefRule):
                    target = self._specs.get(rule.target)
                    if target is None or not isinstance(target.key, GuidKey):
                        raise ValueError(f"{spec.name}.{rule.column}: target {rule.target} must be GUID-keyed")

    def spec(self, table: str) -> TableSpec:
        """Spec for ``table``; unmapped and lookup tables get a content-keyed spec without rules."""
        return self._specs.get(table) or TableSpec(table, ContentKey())

    def is_mapped(self, table: str) -> bool:
        return table in self._specs or table in self.lookup_tables

    @staticmethod
    def is_system(table: str) -> bool:
        """Tables the backend maintains itself; never records."""
        return table == "sqlite_sequence" or table.lower().startswith("usys")


def is_type(*types: str) -> Predicate:
    return lambda row: row.get("attr_object_type") in types


def not_type(*types: str) -> Predicate:
    return lambda row: row.get("attr_object_type") not in types


def has_ntype(value: int) -> Predicate:
    return lambda row: row.get("attr_ntype") == value


def is_connector_type(*types: str) -> Predicate:
    return lambda row: row.get("attr_connector_type") in types


GUID = r"(\{[0-9A-Fa-f-]{36}\})"
ALL_GUID_TABLES = (
    "t_package",
    "t_object",
    "t_attribute",
    "t_operation",
    "t_operationparams",
    "t_connector",
    "t_diagram",
)

EA_TABLEMAP = TableMap(
    specs=[
        TableSpec(
            "t_package",
            GuidKey("attr_ea_guid"),
            rules=(RefRule("attr_parent_id", "t_package"),),
            owner="attr_parent_id",
        ),
        TableSpec(
            "t_object",
            GuidKey("attr_ea_guid"),
            rules=(
                RefRule("attr_package_id", "t_package"),
                RefRule("attr_parentid", "t_object"),
                RefRule("attr_classifier", "t_object"),
                RefRule("attr_diagram_id", "t_diagram"),
                # PDATA1..4 meaning depends on the element type (IEA §4.1.6). First match wins.
                RefRule("attr_pdata1", "t_package", encoding="text", when=is_type("Package")),
                # InteractionFragment: nafv4.qea has PDATA1=12 = the sequence diagram it sits on;
                # its NType holds the operator (0 = alt), IEA §10.
                RefRule(
                    "attr_pdata1",
                    "t_diagram",
                    encoding="text",
                    when=is_type("InteractionFragment", "InteractionOccurrence", "UMLDiagram", "Text", "Frame"),
                ),
                RefRule("attr_pdata1", "t_diagram", encoding="text", when=has_ntype(8)),
                GuidRefRule("attr_pdata1", ("t_object",), when=is_type("Part", "Object", "Port")),
                # Plain values: Requirement Status; Note feature name; Boundary flags (seen in history).
                LiteralRule("attr_pdata1", when=is_type("Requirement", "Note", "Boundary")),
                RefRule("attr_pdata2", "t_object", encoding="text", when=is_type("Note")),
                LiteralRule("attr_pdata2", when=is_type("Requirement", "Boundary")),
                RefRule("attr_pdata3", "t_diagram", encoding="text", when=is_type("State")),
                GuidRefRule("attr_pdata3", ("t_object",), when=is_type("Port")),
                LiteralRule("attr_pdata3", when=is_type("Requirement", "Note")),
                RefRule(
                    "attr_pdata4", "t_connector", encoding="pattern", pattern=r"idref\d*=(\d+);", when=is_type("Note")
                ),
                # Association class: IEA reference map, "For elements: If > 0 this is the primary key of
                # the connector for which this element is defined as association class". Association
                # classes are Classes; nafv4.qea and its history have no non-Note PDATA4 > 0, so any
                # other element type with a numeric PDATA4 is reported unexplained, not dangling.
                RefRule("attr_pdata4", "t_connector", encoding="text", when=is_type("Class")),
                GuidRefRule("attr_classifier_guid", ("t_connector", "t_operation")),
            ),
            owner="attr_package_id",
        ),
        TableSpec(
            "t_attribute",
            GuidKey("attr_ea_guid"),
            rules=(
                RefRule("attr_object_id", "t_object"),
                RefRule("attr_classifier", "t_object", encoding="text"),
                EmbeddedGuidRule("attr_genoption", r"SourceClass=" + GUID, ("t_object",)),
            ),
            owner="attr_object_id",
        ),
        TableSpec(
            "t_operation",
            GuidKey("attr_ea_guid"),
            rules=(
                RefRule("attr_object_id", "t_object"),
                RefRule("attr_classifier", "t_object", encoding="text"),
                GuidRefRule("attr_behaviour", ("t_object",)),
                EmbeddedGuidRule("attr_genoption", r"SourceClass=" + GUID, ("t_object",)),
            ),
            owner="attr_object_id",
        ),
        TableSpec(
            "t_operationparams",
            GuidKey("attr_ea_guid"),
            rules=(
                RefRule("attr_operationid", "t_operation"),
                RefRule("attr_classifier", "t_object", encoding="text"),
            ),
            owner="attr_operationid",
        ),
        TableSpec(
            "t_connector",
            GuidKey("attr_ea_guid"),
            rules=(
                RefRule("attr_start_object_id", "t_object"),
                RefRule("attr_end_object_id", "t_object"),
                RefRule("attr_diagramid", "t_diagram"),
                RefRule(
                    "attr_pdata1", "t_object", encoding="text", when=is_connector_type("Association", "Aggregation")
                ),
                # Sequence messages keep their synchronisation kind here ("Asynchronous").
                LiteralRule("attr_pdata1", when=is_connector_type("Sequence")),
                EmbeddedGuidRule("attr_styleex", r"(?:LFSP|LFEP)=" + GUID, ("t_attribute", "t_operation")),
                EmbeddedGuidRule("attr_styleex", r"DCBMGUID=" + GUID, ("t_connector",)),
            ),
            owner="attr_start_object_id",
        ),
        TableSpec(
            "t_objectproperties",
            GuidKey("attr_ea_guid"),
            rules=(RefRule("attr_object_id", "t_object"),),
            owner="attr_object_id",
        ),
        TableSpec(
            "t_attributetag",
            GuidKey("attr_ea_guid"),
            rules=(RefRule("attr_elementid", "t_attribute"),),
            owner="attr_elementid",
        ),
        TableSpec(
            "t_operationtag",
            GuidKey("attr_ea_guid"),
            rules=(RefRule("attr_elementid", "t_operation"),),
            owner="attr_elementid",
        ),
        TableSpec(
            "t_connectortag",
            GuidKey("attr_ea_guid"),
            rules=(RefRule("attr_elementid", "t_connector"),),
            owner="attr_elementid",
        ),
        TableSpec(
            "t_objectconstraint",
            NaturalKey(("attr_object_id", "attr_constrainttype", "attr_constraint")),
            rules=(RefRule("attr_object_id", "t_object"),),
            owner="attr_object_id",
        ),
        TableSpec(
            "t_diagram",
            GuidKey("attr_ea_guid"),
            rules=(RefRule("attr_package_id", "t_package"), RefRule("attr_parentid", "t_object")),
            owner="attr_package_id",
        ),
        TableSpec(
            "t_diagramobjects",
            DuidKey("attr_diagram_id", "attr_objectstyle", "attr_object_id"),
            rules=(RefRule("attr_diagram_id", "t_diagram"), RefRule("attr_object_id", "t_object")),
            owner="attr_diagram_id",
        ),
        TableSpec(
            "t_diagramlinks",
            NaturalKey(("attr_diagramid", "attr_connectorid")),
            rules=(RefRule("attr_diagramid", "t_diagram"), RefRule("attr_connectorid", "t_connector")),
            owner="attr_diagramid",
        ),
        TableSpec(
            "t_xref",
            GuidKey("attr_xrefid"),
            rules=(GuidRefRule("attr_client", ALL_GUID_TABLES), GuidRefRule("attr_supplier", ALL_GUID_TABLES)),
            owner="attr_client",
            owner_is_guid=True,
        ),
        TableSpec(
            "t_xrefsystem",
            GuidKey("attr_xrefid"),
            # nafv4.qea's t_xrefsystem row holds plain values here ('ModelRoot', 'PView', '8'), not GUIDs.
            rules=(
                EmbeddedGuidRule("attr_supplier", GUID, ALL_GUID_TABLES),
                EmbeddedGuidRule("attr_link", GUID, ALL_GUID_TABLES),
            ),
        ),
        TableSpec(
            "t_taggedvalue",
            GuidKey("attr_propertyid"),
            rules=(GuidRefRule("attr_elementid", ALL_GUID_TABLES),),
            owner="attr_elementid",
            owner_is_guid=True,
        ),
        TableSpec(
            "t_document",
            GuidKey("attr_docid"),
            rules=(GuidRefRule("attr_elementid", ALL_GUID_TABLES),),
            owner="attr_elementid",
            owner_is_guid=True,
        ),
        TableSpec("t_stereotypes", NaturalKey(("attr_stereotype", "attr_appliesto"))),
    ],
    # Repository-wide reference data without references. t_diagramtypes.Package_ID is listed as a
    # foreign key by IEA, but EA's own base data sets it to 1 regardless of the model's packages
    # (refs/EABase_1714_Postgres.sql), so it is lookup data.
    lookup_tables=(
        "t_cardinality",
        "t_complexitytypes",
        "t_connectortypes",
        "t_constants",
        "t_constrainttypes",
        "t_datatypes",
        "t_diagramtypes",
        "t_ecf",
        "t_efforttypes",
        "t_genopt",
        "t_implement",
        "t_lists",
        "t_metrictypes",
        "t_objecttypes",
        "t_ocf",
        "t_problemtypes",
        "t_projectroles",
        "t_requiretypes",
        "t_rtf",
        "t_scenariotypes",
        "t_script",
        "t_statustypes",
        "t_tcf",
        "t_testtypes",
        "t_trxtypes",
    ),
    # Columns EA rewrites on records a commit was not about (evidence: nafv4.qea git history, Task 10).
    # Whenever a diagram is saved EA bumps its ModifiedDate and renumbers Sequence of every object on it by a
    # uniform offset (relative z-order unchanged): a98332bc (attribute rename: all 14 objects +1), 1a5e981b
    # (genlinks edit: all 14 objects -1), 023499e8 (notes added: 11 existing objects +3); 16 diagram saves in total.
    # Not listed although they also change on every diagram save, because the same column carries real data:
    # t_diagram.StyleEx (only the SaveTag key changes) and the diagram's DGS t_xref.Description (a swimlane
    # segment is appended). t_object.ModifiedDate is not volatile: it changed 3 times, twice with a package move
    # of that element (a97ac559, b7944f62) and once alone on MessageTypeEnum (421588e5), never on elements
    # untouched by the commit; attribute edits (6bae0ef6, 9ef25a9e) left it alone.
    volatile=(
        ("t_diagram", "attr_modifieddate"),
        ("t_diagramobjects", "attr_sequence"),
    ),
)
