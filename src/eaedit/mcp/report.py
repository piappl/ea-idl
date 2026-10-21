"""Markdown change report of a session's staged changes, for people (pasted into a change-proposal document)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from eacore.catalogue import AmbiguousStereotype
from eacore.embedded import parse_stereotypes
from eacore.records import Record, RecordSet, Ref
from eaedit.defaults import FIELDS
from eaedit.ops.common import stereotype_names
from eaedit.resolve import is_package_twin, qualified_name

TITLE = "Model changes"
_REPOSITORY = "Repository"
_QUOTES = "«{}»"
_ARROW = "→"
#: Tag tables: owner column, name column, value column (t_taggedvalue keeps the name in TagValue, the value in Notes).
_TAGS = {
    "t_objectproperties": ("attr_object_id", "attr_property", "attr_value"),
    "t_attributetag": ("attr_elementid", "attr_property", "attr_value"),
    "t_connectortag": ("attr_elementid", "attr_property", "attr_value"),
    "t_operationtag": ("attr_elementid", "attr_property", "attr_value"),
    "t_taggedvalue": ("attr_elementid", "attr_tagvalue", "attr_notes"),
}
_ITEMS = ("t_package", "t_object", "t_attribute", "t_operation", "t_connector", "t_diagram")
_LAYOUT = ("t_diagramobjects", "t_diagramlinks")
#: Column -> friendly field name, per table (the reverse of ``FIELDS``); anything else is not shown.
_FRIENDLY = {table: {column: name for name, column in fields.items()} for table, fields in FIELDS.items()}
_FRIENDLY["t_operation"] = {"attr_name": "name", "attr_notes": "notes", "attr_type": "type"}


#: Order of items within a list: packages, elements, diagrams, attributes, operations, connectors, tags.
_RANK = {"t_package": 0, "t_object": 1, "t_diagram": 2, "t_attribute": 3, "t_operation": 4, "t_connector": 5}
_RANK.update({table: 6 for table in _TAGS})


@dataclass
class _Section:
    added: list[tuple[int, str, tuple]] = field(default_factory=list)
    changed: list[tuple[int, str, tuple]] = field(default_factory=list)
    removed: list[tuple[int, str, tuple]] = field(default_factory=list)


def _text(value: Any, empty: str = "(none)") -> str:
    if value is None or value == "":
        return empty
    return " ".join(str(value).split())


def _stereo(values: dict) -> str:
    stereotype = values.get("attr_stereotype")
    return _QUOTES.format(stereotype) + " " if stereotype else ""


def _name(rs: RecordSet, value: Any) -> str:
    record = rs.resolve(value) if isinstance(value, Ref) else None
    if record is None and isinstance(value, str):
        found = rs.by_guid(value)
        record = rs.resolve(found[0]) if found else None
    return _text(record.values.get("attr_name"), "(unnamed)") if record is not None else "?"


def _owner_label(rs: RecordSet, record: Record, column: str) -> str:
    """What a tag or stereotype list belongs to, as a person names it."""
    value = record.values.get(column)
    if record.table == "t_xref":
        found = rs.by_guid(value or "")
        value = found[0] if found else None
    owner = rs.resolve(value) if isinstance(value, Ref) else None
    if owner is None:
        return "?"
    return _label(rs, owner, short_attribute=True, plain=True)


def _label(rs: RecordSet, record: Record, short_attribute: bool = False, plain: bool = False) -> str:
    """One item as a line: ``«stereo» Name (Type)``; ``plain`` leaves out stereotype and type (an owner reference)."""
    values = record.values
    if record.table == "t_package" or (record.table == "t_object" and is_package_twin(record)):
        package = rs.get("t_package", record.key) if record.table == "t_package" else None
        if package is None and record.table == "t_object":
            ref = values.get("attr_pdata1")
            package = rs.resolve(ref) if isinstance(ref, Ref) else None
        name = qualified_name(rs, Ref("t_package", package.key)) if package else _text(values.get("attr_name"))
        return name if plain else f"Package {name}"
    if record.table == "t_object":
        name = _text(values.get("attr_name"), "(unnamed)")
        return name if plain else f"{_stereo(values)}{name} ({_text(values.get('attr_object_type'))})"
    if record.table in ("t_attribute", "t_operation"):
        owner = _name(rs, values.get("attr_object_id"))
        name = f"{owner}.{_text(values.get('attr_name'))}"
        if plain or record.table == "t_operation":
            return name + ("()" if record.table == "t_operation" else "")
        bounds = f"[{_text(values.get('attr_lowerbound'))}..{_text(values.get('attr_upperbound'))}]"
        return f"{_stereo(values)}{name}: {_text(values.get('attr_type'))} {bounds}"
    if record.table == "t_connector":
        kind = _text(values.get("attr_connector_type"))
        ends = f"{_name(rs, values.get('attr_start_object_id'))} -> {_name(rs, values.get('attr_end_object_id'))}"
        return f"{kind} {_stereo(values)}{ends}"
    if record.table == "t_diagram":
        name = _text(values.get("attr_name"))
        return name if plain else f"Diagram {name} ({_text(values.get('attr_diagram_type'))})"
    return "?"


def _twin(record: Record) -> bool:
    return record.table == "t_object" and is_package_twin(record)


def _tag_parts(rs: RecordSet, record: Record) -> tuple[str, str]:
    """``(owner: tag, value)`` of a tag row."""
    owner_col, name_col, value_col = _TAGS[record.table]
    value = record.values.get(value_col)
    if value == "<memo>":
        value = record.values.get("attr_notes")
    return f"{_owner_label(rs, record, owner_col)}: {_text(record.values.get(name_col))}", _text(value)


def _tag_line(rs: RecordSet, record: Record) -> str:
    head, value = _tag_parts(rs, record)
    return f"{head} = {value}"


def _stereotypes(record: Record) -> str:
    names = [s.name for s in parse_stereotypes(record.values.get("attr_description"))]
    return ", ".join(names) if names else "(none)"


def _fields(table: str, changes: dict) -> list[str]:
    friendly = _FRIENDLY.get(table, {})
    lines = []
    for column, (old, new) in changes.items():
        # A t_object twin of a package is shown through the package: its columns follow t_object's names.
        name = friendly.get(column) or (_FRIENDLY["t_object"].get(column) if table == "t_package" else None)
        if name is not None:
            lines.append(f"{name}: {_text(old)} {_ARROW} {_text(new)}")
    return lines


def diagram_file_stem(name: str, used: set[str]) -> str:
    """A plain file name for a diagram (as ``eaedit`` writes them), kept apart from earlier ones of the same name."""
    stem = "".join("_" if c in '/\\:*?"<>|' else c for c in name).strip() or "diagram"
    unique, count = stem, 1
    while unique.lower() in used:
        count += 1
        unique = f"{stem} ({count})"
    used.add(unique.lower())
    return unique


_TABLE_WORDS = {
    "t_object": "element",
    "t_package": "package",
    "t_attribute": "attribute",
    "t_operation": "operation",
    "t_connector": "connector",
    "t_diagram": "diagram",
    "t_xref": "stereotype list",
}


def _plain_words(text: str) -> str:
    """Warning text for people: table names (which operations put in some messages) as plain words."""
    return re.sub(r"\bt_[a-z]+\b", lambda m: _TABLE_WORDS.get(m.group(0), "model data"), text)


def _fence(text: str) -> str:
    longest = max((len(run) for run in re.findall(r"`+", text)), default=0)
    return "`" * max(3, longest + 1)


def change_report(
    session,
    title: str | None = None,
    diagrams_dir: str | None = None,
    idl_diffs: dict[str, str] | None = None,
    idl_files: bool = False,
) -> str:
    """The staged changes as Markdown. ``idl_files`` points at ``idl-<name>.diff`` instead of embedding each diff."""
    preview = session.preview(render=False)
    original, working = session.original, session.working
    sections: dict[str, _Section] = {}

    def add(rs: RecordSet, record: Record, kind: str, lines: list[str], package: Ref | None = None) -> None:
        owner = package if package is not None else rs.owner_package(Ref(record.table, record.key))
        name = qualified_name(rs, owner) if owner is not None else _REPOSITORY
        item = (_RANK.get(record.table, 9), "\n".join(lines), (record.table, record.key))
        getattr(sections.setdefault(name, _Section()), kind).append(item)

    def item_package(rs: RecordSet, record: Record) -> Ref | None:
        """Package twins and the tags and stereotypes on them belong to the package itself."""
        if record.table == "t_object" and is_package_twin(record):
            ref = record.values.get("attr_pdata1")
            return ref if isinstance(ref, Ref) else None
        return None

    def owner_record(rs: RecordSet, record: Record) -> Record | None:
        column = _TAGS[record.table][0] if record.table in _TAGS else "attr_client"
        value = record.values.get(column)
        if isinstance(value, str):
            found = rs.by_guid(value)
            value = found[0] if found else None
        return rs.resolve(value) if isinstance(value, Ref) else None

    def package_of(rs: RecordSet, record: Record) -> Ref | None:
        owner = owner_record(rs, record)
        return item_package(rs, owner) if owner is not None else None

    changes = preview.changes
    # Rows folded into their owner: what the owner's own change already says is not repeated.
    inserted = {(i.record.table, i.record.key) for i in changes.inserts}
    deleted = {(d.table, d.key) for d in changes.deletes}
    layout: dict[Any, tuple[RecordSet, Record, str]] = {}
    stereo_changes: dict[Any, tuple[RecordSet, Record, str, str]] = {}
    other = 0
    stems = diagram_file_stems(session, preview.changes) if diagrams_dir is not None else {}
    folded = _default_tags(session, changes, inserted)

    def note_layout(rs: RecordSet, row: Record) -> None:
        column = "attr_diagram_id" if row.table == "t_diagramobjects" else "attr_diagramid"
        ref = row.values.get(column)
        diagram = rs.resolve(ref) if isinstance(ref, Ref) else None
        if diagram is None or (diagram.table, diagram.key) in inserted | deleted:
            return
        layout[diagram.key] = (rs, diagram, "")

    for delete in changes.deletes:
        record = delete.record or original.get(delete.table, delete.key)
        if record is None:
            continue
        if record.table in _ITEMS and not (record.table == "t_object" and is_package_twin(record)):
            add(original, record, "removed", [_label(original, record)], item_package(original, record))
        elif record.table in _TAGS:
            owner = owner_record(original, record)
            if owner is not None and (owner.table, owner.key) not in deleted:
                add(original, record, "removed", [_tag_line(original, record)], package_of(original, record))
        elif record.table in _LAYOUT:
            note_layout(original, record)
        elif record.table == "t_xref" and record.values.get("attr_name") == "Stereotypes":
            owner = owner_record(original, record)
            if owner is not None and (owner.table, owner.key) not in deleted:
                stereo_changes[owner.key] = (original, owner, _stereotypes(record), "(none)")
        elif record.table != "t_xref" and not _twin(record):
            other += 1

    for insert in changes.inserts:
        record = insert.record
        if record.table in _ITEMS and not (record.table == "t_object" and is_package_twin(record)):
            lines = [_label(working, record)]
            if folded.get((record.table, record.key)):
                lines[0] += f" (+{folded[(record.table, record.key)]} default tags)"
            if record.table == "t_diagram" and diagrams_dir is not None:
                lines[0] += f"\n  ![{_text(record.values.get('attr_name'))}](<{diagrams_dir}/{stems[record.key]}.svg>)"
            add(working, record, "added", lines, item_package(working, record))
        elif record.table in _TAGS:
            if (record.table, record.key) in folded.get("rows", ()):
                continue
            add(working, record, "added", [_tag_line(working, record)], package_of(working, record))
        elif record.table in _LAYOUT:
            note_layout(working, record)
        elif record.table == "t_xref" and record.values.get("attr_name") == "Stereotypes":
            owner = owner_record(working, record)
            if owner is not None and (owner.table, owner.key) not in inserted:
                stereo_changes[owner.key] = (working, owner, "(none)", _stereotypes(record))
        elif record.table not in ("t_xref", "t_stereotypes") and not _twin(record):
            other += 1

    for update in changes.updates:
        record = working.get(update.table, update.key)
        if record is None:
            continue
        if update.table in _ITEMS or (update.table == "t_object" and is_package_twin(record)):
            lines = _fields(update.table, update.changes)
            if lines:
                add(
                    working,
                    record,
                    "changed",
                    [_label(working, record)] + [f"  - {x}" for x in lines],
                    item_package(working, record),
                )
        elif update.table in _TAGS:
            before = original.get(update.table, update.key)
            old = _tag_parts(original, before)[1] if before else "(none)"
            head, value = _tag_parts(working, record)
            if old != value:
                add(working, record, "changed", [f"{head}: {old} {_ARROW} {value}"], package_of(working, record))
        elif update.table in _LAYOUT:
            note_layout(working, record)
        elif update.table == "t_xref" and record.values.get("attr_name") == "Stereotypes":
            owner = owner_record(working, record)
            before = original.get("t_xref", update.key)
            if owner is not None and before is not None:
                stereo_changes[owner.key] = (working, owner, _stereotypes(before), _stereotypes(record))
        elif update.table != "t_xref":
            other += 1

    for rs, owner, old, new in stereo_changes.values():
        if old != new:
            add(
                rs,
                owner,
                "changed",
                [_label(rs, owner), f"  - stereotypes: {old} {_ARROW} {new}"],
                item_package(rs, owner),
            )
    for rs, diagram, _ in layout.values():
        line = f"{_label(rs, diagram, plain=True)}: diagram layout changed"
        if diagram.key in stems:
            line += f"\n  ![{_text(diagram.values.get('attr_name'))}](<{diagrams_dir}/{stems[diagram.key]}.svg>)"
        add(rs, diagram, "changed", [line])
    if other:
        sections.setdefault(_REPOSITORY, _Section()).changed.append(
            (9, f"{other} other change(s) to model data", ("other", 0))
        )

    out = [f"# {title or TITLE}", ""]
    if not sections:
        out += ["No changes.", ""]
    for name in sorted(sections, key=lambda n: (n == _REPOSITORY, n)):
        section = sections[name]
        out += [f"## {name}", ""]
        for heading, items in (("Added", section.added), ("Changed", section.changed), ("Removed", section.removed)):
            if items:
                out += [f"### {heading}", ""]
                out += [f"- {line}" if not line.startswith("  ") else line for line in _fold(items)]
                out.append("")
    if preview.warnings:
        out += ["## Warnings", ""] + [f"- {w.code}: {_plain_words(w.message)}" for w in preview.warnings] + [""]
    if preview.new_issues:
        out += ["## Integrity", ""]
        out += [f"- {i.severity}: {i.message}" for i in preview.new_issues] + [""]
    if idl_diffs:
        out += ["## IDL", ""]
        for name, diff in idl_diffs.items():
            if idl_files:
                out += [f"- {name}: see idl-{name}.diff", ""]
                continue
            fence = _fence(diff)
            out += [f"### {name}", "", f"{fence}diff", diff.rstrip("\n"), fence, ""]
    return "\n".join(out).rstrip("\n") + "\n"


def _default_tags(session, changes, inserted: set) -> dict:
    """Tags of newly added items that hold no value or the catalogue's default: ``{item: count}``, plus the folded
    tag rows under ``"rows"``. The item line carries the count; only tags with another value are listed."""
    working = session.working
    counts: dict = {}
    rows: set = set()
    defaults: dict = {}
    for insert in changes.inserts:
        record = insert.record
        if record.table not in _TAGS:
            continue
        owner_col, name_col, value_col = _TAGS[record.table]
        value = record.values.get(owner_col)
        if isinstance(value, str):
            found = working.by_guid(value)
            value = found[0] if found else None
        owner = working.resolve(value) if isinstance(value, Ref) else None
        if owner is None:
            continue
        item = owner
        if _twin(owner):
            ref = owner.values.get("attr_pdata1")
            item = working.resolve(ref) if isinstance(ref, Ref) else None
        if item is None or (item.table, item.key) not in inserted or item.table not in _ITEMS:
            continue
        if (owner.table, owner.key) not in defaults:
            entries = stereotype_names(session, owner)
            tags = {}
            for name, fqname in entries:
                try:
                    resolved = session.catalogues.resolved(fqname or name)
                except AmbiguousStereotype:
                    continue
                tags.update({t.name: t.default for t in resolved.tags} if resolved else {})
            defaults[(owner.table, owner.key)] = tags
        text = record.values.get(value_col)
        wanted = defaults[(owner.table, owner.key)].get(record.values.get(name_col))
        if text in (None, "") or (wanted and text == wanted):
            counts[(item.table, item.key)] = counts.get((item.table, item.key), 0) + 1
            rows.add((record.table, record.key))
    counts["rows"] = rows
    return counts


def _fold(items: list[tuple[int, str, tuple]]) -> list[str]:
    """Lines of one list: multi-line items (detail or image) stay together, sorted by kind then first line.
    Entries about the same record (several changes to one row) share one head line; equal lines of different
    records stay apart."""
    merged: dict[tuple, tuple[int, str, list[str]]] = {}
    for rank, item, ident in items:
        first, *rest = item.split("\n")
        _, _, details = merged.setdefault(ident, (rank, first, []))
        details.extend(line for line in rest if line not in details)
    out = []
    for _, first, details in sorted(merged.values(), key=lambda e: e[:2]):
        out.append(first)
        out.extend(details)
    return out


def diagram_file_stems(session, changes=None) -> dict:
    """Diagram key -> file stem, in the order the changed diagrams are written (``eaedit`` CLI naming)."""
    used: set[str] = set()
    stems = {}
    for key in session.changed_diagrams(changes):
        record = session.working.get("t_diagram", key)
        stems[key] = diagram_file_stem(str(record.values.get("attr_name") or ""), used)
    return stems
