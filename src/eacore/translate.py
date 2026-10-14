"""Translate raw rows to record values (integer IDs → ``Ref``) and back."""

import re
from dataclasses import dataclass
from typing import Any

from eacore.embedded import duid, is_guid
from eacore.records import Key, Ref, TextRefs
from eacore.tablemap import (
    NOTHING,
    ContentKey,
    DuidKey,
    GuidKey,
    GuidRefRule,
    LiteralRule,
    NaturalKey,
    RefRule,
    Row,
    TableSpec,
)

#: table -> row id -> record key (built at load for GUID-keyed tables with a surrogate ID)
IdMaps = dict[str, dict[int, Key]]
#: table -> record key -> row id (used when writing)
RidMaps = dict[str, dict[Key, int]]


class UnresolvedReferenceError(KeyError):
    """A ``Ref`` being written points at a record the target repository does not have."""


@dataclass(frozen=True)
class Problem:
    kind: str  # "dangling" | "unexplained"
    column: str
    value: Any
    message: str


def _is_canonical_id(text: str) -> bool:
    """ASCII digits that ``str(int(text))`` reproduces exactly, so encoding gives back the same text.

    Rejects other Unicode digits ('²', '٣'), leading zeros and whitespace: such values stay raw.
    """
    return re.fullmatch(r"[0-9]+", text) is not None and str(int(text)) == text


def _ids(rule: RefRule, raw: Any) -> list[int] | None:
    """Integer IDs in ``raw`` according to ``rule``; None if the value does not fit the rule."""
    if rule.encoding == "int":
        if isinstance(raw, bool):
            return None
        if isinstance(raw, int):
            return [raw]
        return [int(raw)] if isinstance(raw, str) and _is_canonical_id(raw) else None
    if rule.encoding == "text":
        return [int(raw)] if isinstance(raw, str) and _is_canonical_id(raw) else None
    matches = list(re.finditer(rule.pattern, str(raw)))
    return [int(m.group(1)) for m in matches] or None


def _escape(text: str) -> str:
    return text.replace("{", "{{").replace("}", "}}")


def _template(rule: RefRule, raw: str) -> str:
    parts, last = [], 0
    for index, match in enumerate(re.finditer(rule.pattern, raw)):
        parts.append(_escape(raw[last : match.start(1)]))
        parts.append("{" + str(index) + "}")
        last = match.end(1)
    parts.append(_escape(raw[last:]))
    return "".join(parts)


def _explaining_columns(spec: TableSpec) -> list[str]:
    columns: list[str] = []
    for rule in spec.rules:
        if isinstance(rule, (RefRule, GuidRefRule, LiteralRule)) and rule.column not in columns:
            columns.append(rule.column)
    return columns


def decode_row(spec: TableSpec, row: Row, idmaps: IdMaps) -> tuple[dict[str, Any], list[Problem]]:
    """Return record values for ``row`` plus problems found. Unresolvable values stay raw."""
    values = dict(row)
    problems: list[Problem] = []
    for column in _explaining_columns(spec):
        raw = row.get(column)
        explained = raw in NOTHING
        for rule in spec.rules:
            if not isinstance(rule, (RefRule, GuidRefRule, LiteralRule)) or rule.column != column:
                continue
            if rule.when is not None and not rule.when(row):
                continue
            if isinstance(rule, LiteralRule):
                explained = True
                break
            if isinstance(rule, GuidRefRule):
                if raw in rule.sentinels or is_guid(raw):
                    explained = True
                    break
                continue
            if raw in rule.null:
                explained = True
                break
            ids = _ids(rule, raw)
            if ids is None:
                continue
            explained = True
            idmap = idmaps.get(rule.target, {})
            missing = [i for i in ids if i not in idmap]
            if missing:
                problems.append(Problem("dangling", column, raw, f"{rule.target} row(s) {missing} do not exist"))
                break
            refs = tuple(Ref(rule.target, idmap[i]) for i in ids)
            values[column] = TextRefs(_template(rule, str(raw)), refs) if rule.encoding == "pattern" else refs[0]
            break
        if not explained:
            problems.append(Problem("unexplained", column, raw, f"no rule explains {column}={raw!r}"))
    return values, problems


def _rid(ref: Ref, ridmaps: RidMaps) -> int:
    try:
        return ridmaps[ref.table][ref.key]
    except KeyError:
        raise UnresolvedReferenceError(f"no row for {ref.table} {ref.key}") from None


def encode_value(spec: TableSpec, column: str, value: Any, ridmaps: RidMaps) -> Any:
    """Raw database value for a record value (inverse of ``decode_row``)."""
    if isinstance(value, Ref):
        rid = _rid(value, ridmaps)
        return str(rid) if spec.encoding_for(column, value.table) == "text" else rid
    if isinstance(value, TextRefs):
        return value.template.format(*(_rid(ref, ridmaps) for ref in value.refs))
    return value


def candidate_key(spec: TableSpec, values: dict[str, Any]) -> Key | None:
    """Key computed from decoded values; None if a GUID key column is empty."""
    kind = spec.key
    if isinstance(kind, GuidKey):
        return values.get(kind.column) or None
    if isinstance(kind, NaturalKey):
        return tuple(values.get(column) for column in kind.columns)
    if isinstance(kind, DuidKey):
        diagram_duid = duid(values.get(kind.style))
        if diagram_duid:
            return (values.get(kind.diagram), diagram_duid)
        return (values.get(kind.diagram), values.get(kind.element), "#no-duid")
    assert isinstance(kind, ContentKey)
    return tuple(sorted(values.items()))
