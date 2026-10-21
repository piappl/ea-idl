"""Agent words: eacore and eaedit messages name tables, columns and raw keys; the agent and the reports read kinds,
field names, qualified names and GUIDs instead.

``agent_words(text, *record_sets)`` rewrites one message. Keys are resolved in the record sets given, in order (the
working copy first, then the original, so deleted rows still get their names); what resolves nowhere keeps its GUID.
"""

from __future__ import annotations

import re

from eacore.records import RecordSet, Ref
from eaedit.defaults import FIELDS
from eaedit.resolve import qualified_name

KINDS = {
    "t_package": "package",
    "t_object": "element",
    "t_attribute": "attribute",
    "t_attributeconstraints": "attribute constraint",
    "t_attributetag": "attribute tag",
    "t_operation": "operation",
    "t_operationparams": "operation parameter",
    "t_operationposts": "operation postcondition",
    "t_operationpres": "operation precondition",
    "t_operationtag": "operation tag",
    "t_connector": "connector",
    "t_connectorconstraint": "connector constraint",
    "t_connectortag": "connector tag",
    "t_roleconstraint": "role constraint",
    "t_diagram": "diagram",
    "t_diagramobjects": "diagram object",
    "t_diagramlinks": "diagram link",
    "t_objectconstraint": "element constraint",
    "t_objectproperties": "tag",
    "t_taggedvalue": "tag",
    "t_xref": "stereotype list",
    "t_xrefsystem": "model data",
    "t_stereotypes": "stereotype definition",
    "t_document": "document",
}

#: Column key -> friendly field name (FIELDS agrees across tables where a column repeats).
_COLUMNS = {column: name for fields in FIELDS.values() for name, column in fields.items()}

_GUID = r"\{[0-9A-Fa-f-]{36}\}"
_REF = re.compile(rf"\b(t_[a-z]+):({_GUID})")
#: A diagram object key (diagram, DUID) or (diagram, element), or a diagram link key (diagram, connector),
#: with the table name that may come before it.
_PLACED = re.compile(
    rf"(?:\bt_diagram(?:objects|links) )?\(t_diagram:({_GUID}), (t_object:{_GUID}|t_connector:{_GUID}|\w+)\)"
)
#: One pass over a message, so names put in are never scanned again. At each position the first alternative that
#: matches wins: raw keys, then text that is left alone (quoted input or model text, qualified names), then table
#: names and column keys.
_TOKEN = re.compile(
    "|".join(
        [
            rf"(?P<placed>{_PLACED.pattern})",
            rf"(?P<ref>{_REF.pattern})",
            r"(?P<kept>'[^'\n]*'|\"[^\"\n]*\"|[\w.{}-]*(?:::[\w.{}-]+)+)",
            r"(?P<table>\bt_[a-z]+\b)",
            r"(?P<column>\battr_[a-z0-9_]+\b)",
        ]
    )
)


def _name(record_sets: tuple[RecordSet, ...], ref: Ref) -> str | None:
    for rs in record_sets:
        if rs.resolve(ref) is not None:
            try:
                return qualified_name(rs, ref)
            except Exception:  # rows without a qualified name
                return None
    return None


def _ref(record_sets: tuple[RecordSet, ...], table: str, guid: str) -> str:
    return f"{KINDS.get(table, 'model data')} {_name(record_sets, Ref(table, guid)) or guid}"


def _placed(record_sets: tuple[RecordSet, ...], match: re.Match) -> str:
    diagram = Ref("t_diagram", match.group(1))
    on = f"on diagram {_name(record_sets, diagram) or diagram.key}"
    second = match.group(2)
    if second.startswith("t_connector:"):
        connector = Ref("t_connector", second.split(":", 1)[1])
        return f"link of connector {_name(record_sets, connector) or connector.key} {on}"
    if second.startswith("t_object:"):
        element = Ref("t_object", second.split(":", 1)[1])
    else:
        element = None
        for rs in record_sets:
            record = rs.resolve(Ref("t_diagramobjects", (diagram, second)))
            if record is not None and isinstance(record.values.get("attr_object_id"), Ref):
                element = record.values["attr_object_id"]
                break
    if element is None:
        return f"object {second} {on}"
    return f"object of {_name(record_sets, element) or element.key} {on}"


def agent_words(text: str, *record_sets: RecordSet) -> str:
    """Message ``text`` with raw keys as names (or GUIDs), table names as kinds and column keys as field names.

    Only for messages (errors, warnings, integrity issues): quoted text and qualified names stay as they are, but
    other model data (a reply listing names) would be rewritten wherever it looks like a table or column.
    """
    if "t_" not in text and "attr_" not in text:
        return text

    def replace(match: re.Match) -> str:
        token = match.group(0)
        if match.group("placed") is not None:
            return _placed(record_sets, _PLACED.fullmatch(token))
        if match.group("ref") is not None:
            ref = _REF.fullmatch(token)
            return _ref(record_sets, ref.group(1), ref.group(2))
        if match.group("table") is not None:
            return KINDS.get(token, "model data")
        if match.group("column") is not None:
            return _COLUMNS.get(token, token.removeprefix("attr_").replace("_", " "))
        return token

    return _TOKEN.sub(replace, text)
