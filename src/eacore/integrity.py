"""Integrity checker: the Project Integrity Check rules that matter for writing outside EA.

EA-made files are ground truth: a rule that fires on an EA-made file is wrong, not the file.
"""

import re
from dataclasses import dataclass
from typing import Callable, Iterable

from eacore.embedded import StereoFormatError, duid, is_guid, link_ends, parse_stereotypes
from eacore.records import RecordSet, Ref, TextRefs, key_str
from eacore.tablemap import NOTHING, EmbeddedGuidRule, GuidKey, GuidRefRule


@dataclass(frozen=True)
class Issue:
    severity: str  # "error" | "warning"
    rule: str
    ref: Ref | None
    message: str


RuleFn = Callable[[RecordSet], Iterable[Issue]]
RULES: dict[str, RuleFn] = {}


def _rule(name: str) -> Callable[[RuleFn], RuleFn]:
    def register(fn: RuleFn) -> RuleFn:
        RULES[name] = fn
        return fn

    return register


def check(rs: RecordSet) -> list[Issue]:
    issues: list[Issue] = []
    for fn in RULES.values():
        issues.extend(fn(rs))
    return issues


def _guid_in(rs: RecordSet, guid: str, targets: tuple[str, ...]) -> bool:
    return any(ref.table in targets for ref in rs.by_guid(guid))


LOAD_ISSUE_RULES = {
    "dangling": ("error", "dangling-reference"),
    "unexplained": ("warning", "unexplained-value"),
    "missing_guid": ("error", "missing-guid"),
    "duplicate_key": ("warning", "duplicate-key"),
}


@_rule("load-issues")
def load_issues(rs: RecordSet) -> Iterable[Issue]:
    for issue in rs.issues:
        severity, name = LOAD_ISSUE_RULES[issue.kind]
        ref = Ref(issue.table, issue.key) if issue.key is not None else None
        column = f"{issue.column}: " if issue.column else ""
        yield Issue(severity, name, ref, f"{issue.table} {column}{issue.message}")


@_rule("dangling-reference")
def dangling_references(rs: RecordSet) -> Iterable[Issue]:
    for table in rs.tables():
        spec = rs.tablemap.spec(table)
        for record in rs.records(table):
            here = Ref(table, record.key)
            for column, value in record.values.items():
                refs = (value,) if isinstance(value, Ref) else value.refs if isinstance(value, TextRefs) else ()
                for ref in refs:
                    if rs.resolve(ref) is None:
                        yield Issue("error", "dangling-reference", here, f"{column} -> missing {key_str(ref)}")
            for rule in spec.rules:
                if isinstance(rule, GuidRefRule):
                    if rule.when is not None and not rule.when(record.values):
                        continue
                    value = record.values.get(rule.column)
                    if is_guid(value) and not _guid_in(rs, value, rule.targets):
                        yield Issue("error", "dangling-reference", here, f"{rule.column} -> unknown GUID {value}")
                elif isinstance(rule, EmbeddedGuidRule):
                    for guid in re.findall(rule.pattern, record.values.get(rule.column) or ""):
                        if not _guid_in(rs, guid, rule.targets):
                            yield Issue("error", "dangling-reference", here, f"{rule.column} -> unknown GUID {guid}")


@_rule("duplicate-guid")
def duplicate_guids(rs: RecordSet) -> Iterable[Issue]:
    owners: dict[str, list[Ref]] = {}
    for table in rs.tables():
        for record in rs.records(table):
            guid = record.values.get("attr_ea_guid")
            if guid:
                owners.setdefault(guid, []).append(Ref(table, record.key))
    for guid, refs in owners.items():
        # A package is a t_package row plus a t_object row sharing the GUID (IEA §4.1).
        if len(refs) > 1 and sorted(r.table for r in refs) != ["t_object", "t_package"]:
            yield Issue("error", "duplicate-guid", refs[0], f"{guid} used by {', '.join(key_str(r) for r in refs)}")


@_rule("malformed-guid")
def malformed_guids(rs: RecordSet) -> Iterable[Issue]:
    for table in rs.tables():
        spec = rs.tablemap.spec(table)
        columns = {"attr_ea_guid"} | ({spec.key.column} if isinstance(spec.key, GuidKey) else set())
        for record in rs.records(table):
            for column in columns:
                value = record.values.get(column)
                if value is not None and not is_guid(value):
                    yield Issue("error", "malformed-guid", Ref(table, record.key), f"{column}={value!r}")


@_rule("package-pair")
def package_pairs(rs: RecordSet) -> Iterable[Issue]:
    partnered = set()
    for element in rs.records("t_object"):
        if element.values.get("attr_object_type") != "Package":
            continue
        pdata = element.values.get("attr_pdata1")
        package = rs.resolve(pdata) if isinstance(pdata, Ref) else None
        if package is None:
            continue  # already reported as dangling or unexplained
        partnered.add(package.key)
        if package.values.get("attr_ea_guid") != element.values.get("attr_ea_guid"):
            yield Issue(
                "error",
                "package-pair",
                Ref("t_object", element.key),
                f"package element GUID differs from its t_package row {key_str(package.key)}",
            )
    for package in rs.records("t_package"):
        if package.key not in partnered and package.values.get("attr_parent_id") not in NOTHING:
            yield Issue("error", "package-pair", Ref("t_package", package.key), "package has no t_object element row")


STEREO_XREF_TYPES = {
    "t_object": "element property",
    "t_attribute": "attribute property",
    "t_operation": "operation property",
    "t_connector": "connector property",
}


@_rule("stereotypes")
def stereotypes(rs: RecordSet) -> Iterable[Issue]:
    lists: dict[tuple, list[str]] = {}
    for xref in rs.records("t_xref"):
        if xref.values.get("attr_name") != "Stereotypes":
            continue
        try:
            names = [s.name for s in parse_stereotypes(xref.values.get("attr_description"))]
        except StereoFormatError as exc:
            yield Issue("error", "stereotype-format", Ref("t_xref", xref.key), str(exc))
            continue
        lists[(xref.values.get("attr_client"), xref.values.get("attr_type"))] = names
    for table, xref_type in STEREO_XREF_TYPES.items():
        for record in rs.records(table):
            primary = record.values.get("attr_stereotype") or ""
            names = lists.get((record.values.get("attr_ea_guid"), xref_type))
            if primary and names and names[0] != primary:
                yield Issue(
                    "error",
                    "stereotype-mismatch",
                    Ref(table, record.key),
                    f"Stereotype column {primary!r} but t_xref lists {names}",
                )


@_rule("diagram-duids")
def diagram_duids(rs: RecordSet) -> Iterable[Issue]:
    per_diagram: dict = {}
    shown: set[tuple] = set()  # (diagram, element) pairs placed on a diagram
    for obj in rs.records("t_diagramobjects"):
        shown.add((obj.values.get("attr_diagram_id"), obj.values.get("attr_object_id")))
        value = duid(obj.values.get("attr_objectstyle"))
        if value:
            counts = per_diagram.setdefault(obj.values.get("attr_diagram_id"), {})
            counts[value] = counts.get(value, 0) + 1
    for diagram, counts in per_diagram.items():
        for value, count in counts.items():
            if count > 1:
                ref = diagram if isinstance(diagram, Ref) else None
                yield Issue("error", "duplicate-duid", ref, f"DUID {value} used {count} times on one diagram")
    for link in rs.records("t_diagramlinks"):
        diagram = link.values.get("attr_diagramid")
        known = per_diagram.get(diagram, {})
        connector_ref = link.values.get("attr_connectorid")
        connector = rs.resolve(connector_ref) if isinstance(connector_ref, Ref) else None
        elements = (
            (connector.values.get("attr_start_object_id"), connector.values.get("attr_end_object_id"))
            if connector is not None
            else (None, None)
        )
        for end, value, element in zip(("SOID", "EOID"), link_ends(link.values.get("attr_style")), elements):
            if not value or value in known:
                continue
            # EA keeps link rows whose connector end is no longer on the diagram, with a stale DUID:
            # nafv4.qea from a97ac559 on, diagram 'measurement' link of connector
            # {2E9BC562-577D-4fda-88E2-2554AC842197} has SOID=C52111B5 while its start element DataMessage
            # is not on that diagram (no t_diagramobjects row has that DUID in any version); a98332bc adds
            # nine such links on 'message' with EOID=2AB0F8A2 for end element Identifier, also absent.
            # EA does not draw these links, so a stale DUID there is a warning; it is an error only when the
            # end element is on the diagram and the DUID still matches none of its objects.
            on_diagram = element is None or (diagram, element) in shown
            yield Issue(
                "error" if on_diagram else "warning",
                "link-duid",
                Ref("t_diagramlinks", link.key),
                f"{end}={value} matches no DUID" + ("" if on_diagram else " (end element not on the diagram)"),
            )


@_rule("sqlite-sequence")
def sqlite_sequence(rs: RecordSet) -> Iterable[Issue]:
    sequences = rs.meta.get("sequences", {})
    for table, max_id in rs.meta.get("max_ids", {}).items():
        if table in sequences and sequences[table] < max_id:
            yield Issue("error", "sqlite-sequence", None, f"{table}: sequence {sequences[table]} < max ID {max_id}")


@_rule("unmapped-table")
def unmapped_tables(rs: RecordSet) -> Iterable[Issue]:
    for table in rs.meta.get("unmapped_tables", []):
        yield Issue("warning", "unmapped-table", None, f"{table}: not in the table map, references untranslated")
