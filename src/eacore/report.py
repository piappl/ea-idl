"""Human-readable and JSON renderings of records and change sets."""

import json
from typing import Any

from eacore.changes import ChangeSet
from eacore.records import Record, RecordSet, Ref, TextRefs, key_str

MAX_VALUE = 200
REPOSITORY = "Repository settings"
PARENT_COLUMNS = ("attr_object_id", "attr_elementid", "attr_operationid")


def fmt_value(value: Any) -> str:
    if isinstance(value, Ref):
        return f"->{value.table}:{key_str(value.key)}"
    if isinstance(value, TextRefs):
        return f"{value.template!r} % [{', '.join(fmt_value(r) for r in value.refs)}]"
    if isinstance(value, bytes):
        return f"<{len(value)} bytes>"
    text = repr(value)
    return text if len(text) <= MAX_VALUE else text[:MAX_VALUE] + "…"


def _name(rs: RecordSet, value: Any) -> str:
    record = rs.resolve(value) if isinstance(value, Ref) else None
    if record is None:
        return "?" if value in (None, "") else str(value)
    return str(record.values.get("attr_name") or key_str(record.key))


def package_path(rs: RecordSet, ref: Ref | None) -> str:
    names: list[str] = []
    seen = set()
    while ref is not None and ref not in seen:
        seen.add(ref)
        record = rs.resolve(ref)
        if record is None:
            break
        names.append(str(record.values.get("attr_name")))
        parent = record.values.get("attr_parent_id")
        ref = parent if isinstance(parent, Ref) else None
    return "/".join(reversed(names))


def describe(rs: RecordSet, record: Record) -> str:
    values = record.values
    if record.table == "t_diagramobjects":
        label = f"{_name(rs, values.get('attr_object_id'))} on diagram {_name(rs, values.get('attr_diagram_id'))}"
    elif record.table == "t_diagramlinks":
        label = f"{_name(rs, values.get('attr_connectorid'))} on diagram {_name(rs, values.get('attr_diagramid'))}"
    elif record.table == "t_xref":
        owners = rs.by_guid(values.get("attr_client") or "")
        owner = _name(rs, owners[0]) if owners else values.get("attr_client")
        label = f"{values.get('attr_name')} ({values.get('attr_type')}) of {owner}"
    else:
        label = str(values.get("attr_name") or values.get("attr_property") or "")
        parent = next((values[c] for c in PARENT_COLUMNS if isinstance(values.get(c), Ref)), None)
        if parent is not None:
            label = f"{_name(rs, parent)}.{label}"
    stereotype = values.get("attr_stereotype")
    prefix = f"«{stereotype}» " if stereotype else ""
    return f"{record.table} {prefix}{label} [{key_str(record.key)}]"


def _group(rs: RecordSet, table: str, key) -> str:
    owner = rs.owner_package(Ref(table, key))
    return package_path(rs, owner) if owner else REPOSITORY


def render_text(changes: ChangeSet, before: RecordSet, after: RecordSet) -> str:
    """Changes grouped by owning package; repository-wide rows last."""
    groups: dict[str, list[tuple[str, str]]] = {}

    def add(group: str, sort_key: str, text: str) -> None:
        groups.setdefault(group, []).append((sort_key, text))

    for delete in changes.deletes:
        record = delete.record or before.get(delete.table, delete.key)
        text = describe(before, record) if record else f"{delete.table} [{key_str(delete.key)}]"
        add(_group(before, delete.table, delete.key), f"{delete.table}{key_str(delete.key)}", f"- {text}")
    for insert in changes.inserts:
        record = insert.record
        add(
            _group(after, record.table, record.key),
            f"{record.table}{key_str(record.key)}",
            f"+ {describe(after, record)}",
        )
    for update in changes.updates:
        record = after.get(update.table, update.key) or before.get(update.table, update.key)
        lines = [f"~ {describe(after, record)}"] + [
            f"    {column}: {fmt_value(old)} -> {fmt_value(new)}" for column, (old, new) in update.changes.items()
        ]
        add(_group(after, update.table, update.key), f"{update.table}{key_str(update.key)}", "\n".join(lines))

    out = []
    for group in sorted(groups, key=lambda g: (g == REPOSITORY, g)):
        out.append(f"== {group} ==")
        out.extend(text for _, text in sorted(groups[group]))
        out.append("")
    return "\n".join(out) if out else "No changes.\n"


def _jsonable(value: Any) -> Any:
    if isinstance(value, Ref):
        return {"ref": value.table, "key": key_str(value.key)}
    if isinstance(value, TextRefs):
        return {"template": value.template, "refs": [_jsonable(r) for r in value.refs]}
    if isinstance(value, bytes):
        return {"bytes_hex": value.hex()}
    return value


def to_json(changes: ChangeSet) -> str:
    data = {
        "inserts": [
            {
                "table": i.record.table,
                "key": key_str(i.record.key),
                "values": {c: _jsonable(v) for c, v in i.record.values.items()},
            }
            for i in changes.inserts
        ],
        "updates": [
            {
                "table": u.table,
                "key": key_str(u.key),
                "changes": {c: [_jsonable(o), _jsonable(n)] for c, (o, n) in u.changes.items()},
            }
            for u in changes.updates
        ],
        "deletes": [{"table": d.table, "key": key_str(d.key)} for d in changes.deletes],
    }
    return json.dumps(data, indent=2, ensure_ascii=False)


def dump_text(rs: RecordSet) -> str:
    """One line per value, sorted: ``table<TAB>key<TAB>column<TAB>value``. Used for git textconv."""
    lines = []
    for table in rs.tables():
        for record in sorted(rs.records(table), key=lambda r: key_str(r.key)):
            for column in sorted(record.values):
                lines.append(f"{table}\t{key_str(record.key)}\t{column}\t{fmt_value(record.values[column])}")
    return "\n".join(lines) + "\n"
