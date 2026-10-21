"""Exploration text for the agent: compact, paged, read-only. Qualified names and GUIDs only, never row ids."""

from __future__ import annotations

import re
from collections import Counter
from typing import Callable

from eacore.catalogue import AmbiguousStereotype
from eacore.records import Record, Ref
from eaedit.errors import AmbiguousNameError, InvalidOperationError, NotFoundError
from eaedit.ops.common import package_twin, stereotype_names
from eaedit.ops.diagrams import shown_element
from eaedit.resolve import find, guid_of, is_package_twin, qualified_name

KINDS = ("package", "element", "attribute", "connector", "diagram")
_KIND_OF = {"t_package": "package", "t_object": "element", "t_attribute": "attribute", "t_connector": "connector"}
_KIND_OF["t_diagram"] = "diagram"
_TYPE_COLUMN = {
    "t_object": "attr_object_type",
    "t_attribute": "attr_type",
    "t_connector": "attr_connector_type",
    "t_diagram": "attr_diagram_type",
}
KINDS_TABLES = {"package": ("t_package",), "element": ("t_object",), "attribute": ("t_attribute",)}
KINDS_TABLES.update({"connector": ("t_connector",), "diagram": ("t_diagram",)})
MAX_LINE = 200


_TAIL = re.compile(r"(\s+\{[^{}]*\})?(\s+\[\+\d+ packages\])?$")


def _clip(text: str, limit: int = MAX_LINE) -> str:
    """One line of at most ``limit`` characters; the name part is cut, a trailing ``{guid}`` or suffix kept."""
    text = text.replace("\r", " ").replace("\n", " ")
    if len(text) <= limit:
        return text
    tail = _TAIL.search(text).group(0)
    head = text[: len(text) - len(tail)]
    room = max(limit - len(tail) - 1, 1)
    return head[:room] + "…" + tail


def page_lines(lines: list[str], page: int, page_size: int, clip: bool = True) -> str:
    """One page of ``lines``; a truncated page ends with ``… N more (page=K)``. ``clip`` cuts long lines."""
    page, page_size = max(page, 1), max(page_size, 1)
    start = (page - 1) * page_size
    if start >= len(lines) and lines:
        return f"no page {page}: {len(lines)} lines in all (page_size={page_size})"
    out = [_clip(line) if clip else line for line in lines[start : start + page_size]]
    left = len(lines) - start - len(out)
    if left > 0:
        out.append(f"… {left} more (page={page + 1})")
    return "\n".join(out)


def _ref(record: Record) -> Ref:
    return Ref(record.table, record.key)


def _qname(session, record: Record) -> str:
    return qualified_name(session.working, _ref(record))


def _guid(record: Record) -> str:
    return guid_of(record) or "-"


def _stereos(session, record: Record) -> list[str]:
    if record.table == "t_diagram":
        return []
    if record.table == "t_package" and _package_object(session, record) is None:
        return []
    return [name for name, _ in stereotype_names(session, record)]


def _package_object(session, package: Record) -> Record | None:
    """A package's element row; a package without one (the model root) has no stereotypes, tags or connectors."""
    try:
        return package_twin(session, package)
    except NotFoundError:
        return None


def _element_key(session, record: Record):
    """The ``t_object`` key standing for ``record`` (a package: its element row), None when there is none."""
    if record.table != "t_package":
        return record.key
    twin = _package_object(session, record)
    return twin.key if twin is not None else None


def _type(record: Record) -> str:
    column = _TYPE_COLUMN.get(record.table)
    return (record.values.get(column) if column else "Package") or ""


def _braced(record: Record) -> str:
    guid = _guid(record)
    return guid if guid == "-" else guid if guid.startswith("{") else "{" + guid + "}"


def _line(session, record: Record) -> str:
    stereo = ", ".join(_stereos(session, record))
    parts = [_KIND_OF[record.table], _qname(session, record), f"«{stereo}»" if stereo else "", _type(record)]
    return "  ".join(p for p in parts if p) + "  " + _braced(record)


class _Reply(Exception):
    """A finished reply to return instead of continuing (the ambiguity listing)."""


def _matches(rs, identifier: str, kinds) -> list[Record]:
    """Every record ``identifier`` names, as ``resolve.find`` counts them (a package's object twin excluded)."""
    wanted = identifier.strip()
    by_guid = wanted.startswith("{") and wanted.endswith("}")
    tables = sorted({t for kind in kinds for t in KINDS_TABLES[kind]})
    found = []
    for table in tables:
        for rec in rs.records(table):
            if "package" in kinds and is_package_twin(rec):
                continue
            if by_guid:
                if (guid_of(rec) or "").upper() == wanted.upper():
                    found.append(rec)
            elif qualified_name(rs, _ref(rec)) == wanted:
                found.append(rec)
    return found


def _resolve(session, identifier: str, kinds=KINDS) -> Record:
    rs = session.working
    try:
        return rs.resolve(find(rs, identifier, kinds=kinds))
    except AmbiguousNameError as exc:
        # Candidates are re-found as records: the exception's strings may be internal keys, which never print.
        lines = [f"ambiguous: {identifier}"] + [_line(session, r) for r in _matches(rs, identifier, kinds)]
        raise _Reply("\n".join(lines)) from exc


def _replies(fn: Callable) -> Callable:
    def wrapper(*args, **kwargs) -> str:
        try:
            return fn(*args, **kwargs)
        except _Reply as reply:
            return str(reply)

    wrapper.__name__, wrapper.__doc__ = fn.__name__, fn.__doc__
    return wrapper


# --- overview ---------------------------------------------------------------------------------------------------


def _subpackages(session) -> dict:
    by_parent: dict = {}
    for pkg in session.working.records("t_package"):
        parent = pkg.values.get("attr_parent_id")
        by_parent.setdefault(parent.key if isinstance(parent, Ref) else None, []).append(pkg)
    for children in by_parent.values():
        children.sort(key=lambda p: (p.values.get("attr_name") or "", str(p.key)))
    return by_parent


@_replies
def overview(session, package: str | None = None, depth: int = 2, page: int = 1, page_size: int = 40) -> str:
    """The package tree to ``depth`` levels (the starting package is level 1), with element counts."""
    rs = session.working
    by_parent = _subpackages(session)
    counts: dict = {}
    for obj in rs.records("t_object"):
        holder = obj.values.get("attr_package_id")
        if not is_package_twin(obj) and isinstance(holder, Ref):
            counts.setdefault(holder.key, Counter())[obj.values.get("attr_object_type") or "?"] += 1
    if package is None:
        roots = by_parent.get(None, [])
    else:
        roots = [_resolve(session, package, ("package",))]
    lines: list[str] = []

    def visit(pkg: Record, level: int) -> None:
        kinds = counts.get(pkg.key, Counter())
        detail = ", ".join(f"{n} {k}" for k, n in sorted(kinds.items()))
        info = f"{sum(kinds.values())} elements" + (f": {detail}" if detail else "")
        children = by_parent.get(pkg.key, [])
        hidden = f"  [+{len(children)} packages]" if children and level >= depth else ""
        lines.append(f"{'  ' * (level - 1)}{pkg.values.get('attr_name') or ''}  ({info})  {_braced(pkg)}{hidden}")
        if level < depth:
            for child in children:
                visit(child, level + 1)

    for root in roots:
        visit(root, 1)
    return page_lines(lines, page, page_size)


# --- search -----------------------------------------------------------------------------------------------------


def _matcher(text: str) -> Callable[[str], bool]:
    if len(text) >= 2 and text.startswith("/") and text.endswith("/"):
        try:
            pattern = re.compile(text[1:-1], re.IGNORECASE)
        except re.error as exc:
            raise InvalidOperationError(f"bad pattern {text}: {exc}") from exc
        return lambda name: pattern.search(name) is not None
    needle = text.casefold()
    return lambda name: needle in name.casefold()


#: What ``search`` looks in.
FIELDS = ("name", "notes", "tags", "any")
#: Notes column of each kind (a package's notes may also sit on its element row).
_NOTES = {
    "t_package": "attr_notes",
    "t_object": "attr_note",
    "t_attribute": "attr_notes",
    "t_connector": "attr_notes",
    "t_diagram": "attr_notes",
}
#: Tag table and owner column per owner table.
_TAG_TABLES = (
    ("t_objectproperties", "attr_object_id"),
    ("t_attributetag", "attr_elementid"),
    ("t_connectortag", "attr_elementid"),
)


def _plain_text(text: str) -> str:
    """Notes without EA's markup, on one line."""
    return " ".join(re.sub(r"<[^>]+>", " ", text).split())


def _tag_index(rs) -> dict[tuple[str, object], list[tuple[str, str]]]:
    """(owner table, owner key) -> [(tag name, value)]; a package's tags (on its element row) count as its own."""
    index: dict[tuple[str, object], list[tuple[str, str]]] = {}
    for table, column in _TAG_TABLES:
        for tag in rs.records(table):
            owner = tag.values.get(column)
            if not isinstance(owner, Ref):
                continue
            key = (owner.table, owner.key)
            record = rs.resolve(owner)
            if record is not None and is_package_twin(record):
                key = ("t_package", record.values["attr_pdata1"].key)
            value = tag.values.get("attr_value")
            if value == "<memo>":
                value = tag.values.get("attr_notes")
            index.setdefault(key, []).append(
                (tag.values.get("attr_property") or "", "" if value is None else str(value))
            )
    return index


def _snippet(text: str, query: str, width: int = 60) -> str:
    """``text`` on one line, cut to ``width`` around the first match of ``query`` (substring or ``/regex/``)."""
    text = _plain_text(text)
    if len(text) <= width:
        return text
    if len(query) >= 2 and query.startswith("/") and query.endswith("/"):
        found = re.search(query[1:-1], text, re.IGNORECASE)
        at = found.start() if found else 0
    else:
        at = max(text.casefold().find(query.casefold()), 0)
    start = max(0, min(at - width // 4, len(text) - width))
    return ("…" if start else "") + text[start : start + width] + ("…" if start + width < len(text) else "")


@_replies
def search(
    session,
    text: str = "",
    kind: str | None = None,
    stereotype: str | None = None,
    package: str | None = None,
    field: str = "name",
    page: int = 1,
    page_size: int = 40,
) -> str:
    """Things whose ``field`` matches ``text`` (substring, or ``/regex/``), case-insensitively.

    ``field``: ``name`` (default), ``notes``, ``tags`` (tag names and values) or ``any``. A match outside the name
    adds what matched to the line (``notes: "…"`` or ``tag name = value``).
    """
    if kind is not None and kind not in KINDS:
        return f"unknown kind {kind!r}: use one of {', '.join(KINDS)}"
    if field not in FIELDS:
        raise InvalidOperationError(f"unknown field {field!r}: use one of {', '.join(FIELDS)}")
    match = _matcher(text)
    prefix = _qname(session, _resolve(session, package, ("package",))) if package else None
    rs = session.working
    tags = _tag_index(rs) if field in ("tags", "any") else {}
    rows: list[tuple[str, str, Record, str]] = []
    for table in ("t_package", "t_object", "t_attribute", "t_connector", "t_diagram"):
        if kind is not None and _KIND_OF[table] != kind:
            continue
        for rec in rs.records(table):
            if is_package_twin(rec):
                continue
            hit = _hit(session, rec, field, match, text, tags)
            if hit is None:
                continue
            qn = _qname(session, rec)
            if prefix is not None and not (qn == prefix or qn.startswith(prefix + "::")):
                continue
            if stereotype is not None and not any(stereotype in (n, fq) for n, fq in _names(session, rec)):
                continue
            rows.append((qn, _guid(rec), rec, hit))
    rows.sort(key=lambda r: (r[0], r[1]))
    lines = [_line(session, rec) + (f"  {hit}" if hit else "") for _, _, rec, hit in rows]
    return page_lines(lines or ["no matches"], page, page_size)


def _hit(session, record: Record, field: str, match, query: str, tags) -> str | None:
    """What of ``record`` matches: "" for its name, a short note or tag text, or None when nothing does."""
    if field in ("name", "any") and match(record.values.get("attr_name") or ""):
        return ""
    if field in ("notes", "any"):
        notes = [record.values.get(_NOTES[record.table])]
        if record.table == "t_package":
            twin = _package_object(session, record)
            notes.append(None if twin is None else twin.values.get("attr_note"))
        for note in notes:
            if note and match(_plain_text(note)):
                return f'notes: "{_snippet(note, query)}"'
    if field in ("tags", "any"):
        for name, value in tags.get((record.table, record.key), []):
            if match(name) or match(value):
                return f"tag {name} = {_snippet(value, query, 40)}"
    return None


def _names(session, record: Record) -> list[tuple[str, str | None]]:
    return [] if record.table == "t_diagram" else stereotype_names(session, record)


# --- describe ---------------------------------------------------------------------------------------------------


def _end(session, ref) -> tuple[str, str]:
    record = session.working.resolve(ref) if isinstance(ref, Ref) else None
    if record is None:
        return "?", "-"
    return _qname(session, record), _braced(record)


def _short(qualified: str) -> str:
    return qualified.rpartition("::")[2] or qualified


def _diagrams_showing(session, element: Record) -> list[str]:
    target = _element_key(session, element)
    if target is None:
        return []
    seen: dict[str, str] = {}
    for obj in session.working.records("t_diagramobjects"):
        shown = shown_element(session, obj)
        # An orphan row (its diagram deleted, which EA leaves behind) keeps a raw ID instead of a reference.
        ref = obj.values.get("attr_diagram_id")
        diagram = session.working.resolve(ref) if isinstance(ref, Ref) else None
        if shown is not None and shown.key == target and diagram is not None:
            seen[_guid(diagram)] = f"  {_qname(session, diagram)}  {_braced(diagram)}"
    return [seen[g] for g in sorted(seen, key=lambda g: seen[g])]


def _connectors_of(session, element: Record) -> list[tuple[Record, bool]]:
    """Connectors touching ``element`` (a package: its twin), with True when the element is the source."""
    key = _element_key(session, element)
    if key is None:
        return []
    this = Ref("t_object", key)
    found = []
    for conn in session.working.records("t_connector"):
        if conn.values.get("attr_start_object_id") == this:
            found.append((conn, True))
        if conn.values.get("attr_end_object_id") == this:
            found.append((conn, False))
    return found


def _connector_line(session, conn: Record, outgoing: bool) -> str:
    qn, _ = _end(session, conn.values.get("attr_end_object_id" if outgoing else "attr_start_object_id"))
    stereo = ", ".join(_stereos(session, conn))
    kind = conn.values.get("attr_connector_type") or "?"
    arrow = "->" if outgoing else "<-"
    return f"  {kind}{f' «{stereo}»' if stereo else ''} {arrow} {_short(qn)} ({qn}) {_braced(conn)}"


def _bounds(rec: Record) -> str:
    lo, up = rec.values.get("attr_lowerbound"), rec.values.get("attr_upperbound")
    return f"[{lo or '?'}..{up or '?'}]" if lo or up else ""


def _attribute_line(session, rec: Record, with_owner: bool = False) -> str:
    classifier = rec.values.get("attr_classifier")
    cls = session.working.resolve(classifier) if isinstance(classifier, Ref) else None
    default = rec.values.get("attr_default")
    name = _qname(session, rec) if with_owner else rec.values.get("attr_name")
    text = f"  {name}: {rec.values.get('attr_type') or '?'}" + (f" {_bounds(rec)}" if _bounds(rec) else "")
    return text + (f" = {default}" if default else "") + f"  {_braced(cls) if cls is not None else '-'}"


def _tag_lines(tags: dict) -> list[str]:
    return [f"  {name} = {'' if value is None else value}" for name, value in tags.items()]


def _common(session, info: dict) -> list[str]:
    lines = []
    if info.get("stereotypes"):
        lines.append("stereotypes: " + ", ".join(info["stereotypes"]))
    if info.get("alias"):
        lines.append(f"alias: {info['alias']}")
    if info.get("notes"):
        lines.append("notes: " + _clip(str(info["notes"]), 160))
    if info.get("tags"):
        lines += ["tags:"] + _tag_lines(info["tags"])
    return lines


@_replies
def describe(session, identifier: str, page: int = 1, page_size: int = 40) -> str:
    """One thing in compact detail: header line, then short sections."""
    record = _resolve(session, identifier)
    header = _line(session, record)
    lines = [header]
    if record.table == "t_diagram":
        from eaedit.mcp.diagram_text import diagram_text  # imported late: diagram_text builds on this module

        return diagram_text(session, _braced(record), page, page_size)
    if record.table == "t_package" and _package_object(session, record) is None:
        info = {"notes": record.values.get("attr_notes")}
    else:
        info = session.get(_braced(record))
    lines += _common(session, info)
    if record.table == "t_attribute":
        lines.append(f"owner: {info['owner']}")
        lines.append("type:" + _attribute_line(session, record).split(":", 1)[1])
    elif record.table == "t_connector":
        for end, role, card in (("source", "source_role", "source_card"), ("target", "target_role", "target_card")):
            qn, guid = _end(session, record.values.get(f"attr_{'start' if end == 'source' else 'end'}_object_id"))
            extra = "".join(f" {k}={info[v]}" for k, v in (("role", role), ("card", card)) if info.get(v))
            lines.append(f"{end}: {qn} {guid}{extra}")
        if info.get("direction"):
            lines.append(f"direction: {info['direction']}")
    else:
        if record.table == "t_package":
            lines += _contents(session, record)
        else:
            lines += _element_sections(session, record)
        shown = _diagrams_showing(session, record)
        lines += ["diagrams:"] + shown if shown else ["diagrams: none"]
    return page_lines(lines, page, page_size)


def _element_sections(session, record: Record) -> list[str]:
    rs = session.working
    this = Ref("t_object", record.key)
    attrs = [a for a in rs.records("t_attribute") if a.values.get("attr_object_id") == this]
    attrs.sort(key=lambda a: (a.values.get("attr_pos") or 0, a.values.get("attr_name") or ""))
    lines = ["attributes:"] + [_attribute_line(session, a) for a in attrs] if attrs else ["attributes: none"]
    parents, others = [], []
    for conn, outgoing in _connectors_of(session, record):
        other_ref = conn.values.get("attr_end_object_id" if outgoing else "attr_start_object_id")
        qn, guid = _end(session, other_ref)
        if conn.values.get("attr_connector_type") == "Generalization":
            if outgoing:
                parents.append(f"  -> {qn} {guid}")
            continue
        others.append(_connector_line(session, conn, outgoing))
    lines += ["generalizations:"] + sorted(parents) if parents else ["generalizations: none"]
    lines += ["connectors:"] + sorted(others) if others else ["connectors: none"]
    return lines


def _contents(session, package: Record) -> list[str]:
    rs = session.working
    this = Ref("t_package", package.key)
    rows = [p for p in rs.records("t_package") if p.values.get("attr_parent_id") == this]
    rows += [
        o
        for o in rs.records("t_object")
        if not is_package_twin(o) and o.values.get("attr_package_id") == this and not o.values.get("attr_parentid")
    ]
    rows += [d for d in rs.records("t_diagram") if d.values.get("attr_package_id") == this]
    rows.sort(key=lambda r: (_qname(session, r), _guid(r)))
    return ["contents:"] + [f"  {_line(session, r)}" for r in rows] if rows else ["contents: none"]


# --- usages -----------------------------------------------------------------------------------------------------


@_replies
def usages(session, identifier: str, page: int = 1, page_size: int = 40) -> str:
    """Where an element (or package) is used: typed attributes, connectors, diagrams, specialisations."""
    rs = session.working
    record = _resolve(session, identifier, ("package", "element"))
    key = _element_key(session, record)
    this = Ref("t_object", key) if key is not None else None
    typed = sorted(
        _attribute_line(session, a, with_owner=True)
        for a in rs.records("t_attribute")
        if this is not None and a.values.get("attr_classifier") == this
    )
    links, children = [], []
    for conn, outgoing in _connectors_of(session, record):
        qn, guid = _end(session, conn.values.get("attr_end_object_id" if outgoing else "attr_start_object_id"))
        kind = conn.values.get("attr_connector_type") or "?"
        if kind == "Generalization" and not outgoing:
            children.append(f"  {qn} {guid}")
            continue
        links.append(_connector_line(session, conn, outgoing))
    shown = _diagrams_showing(session, record)

    def section(title: str, rows: list[str]) -> list[str]:
        return [f"{title}:"] + rows if rows else [f"{title}: none"]

    lines = [_line(session, record)]
    lines += section("attributes typed by it", typed)
    lines += section("connectors", sorted(links))
    lines += section("specialised by", sorted(children))
    lines += section("diagrams", shown)
    return page_lines(lines, page, page_size)


# --- stereotype info --------------------------------------------------------------------------------------------


def stereotype_info(session, name: str, page: int = 1, page_size: int = 40) -> str:
    """A stereotype's catalogue definition: applies-to, tags, ancestors, end rules, source."""
    catalogues = session.catalogues
    try:
        resolved = catalogues.resolved(name)
    except AmbiguousStereotype as exc:
        return "\n".join([f"ambiguous: {name}"] + [f"stereotype  {fq}" for fq in exc.candidates])
    if resolved is None:
        return f"no stereotype named {name!r} in the loaded catalogues or the model"
    definition = resolved.definition
    source = resolved.source
    lines = [f"«{resolved.fqname}»" + ("  (abstract)" if definition.abstract else "")]
    lines.append("source: " + " ".join(p for p in (source.kind, source.file, source.version) if p))
    lines.append("applies to: " + (", ".join(resolved.applies_to) or "-"))
    lines.append("generalizes: " + (", ".join(definition.generalizes) or "-"))
    if resolved.missing:
        lines.append("undefined ancestors: " + ", ".join(resolved.missing))
    lines.append("tags:" if resolved.tags else "tags: none")
    for tag in resolved.tags:
        extra = (f" values={'|'.join(tag.values)}" if tag.values else "") + (
            f" default={tag.default}" if tag.default else ""
        )
        lines.append(f"  {tag.name}: {tag.type or '-'}{extra}")
    if resolved.constraints:
        lines.append("connector end rules:")
        lines += [f"  {c.role} -> {c.target}" for c in resolved.constraints]
    return page_lines(lines, page, page_size)
