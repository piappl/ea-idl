"""Learn a catalogue from how a model already uses stereotypes."""

from collections import Counter, defaultdict

from eacore.catalogue import Catalogue, Source, StereotypeDef, TagDef
from eacore.embedded import StereoFormatError, parse_stereotypes
from eacore.records import Ref, RecordSet

# table -> (metaclass column or fixed metaclass, tag table, tag owner column)
_TARGETS = {
    "t_object": ("attr_object_type", "t_objectproperties", "attr_object_id"),
    "t_attribute": ("Attribute", "t_attributetag", "attr_elementid"),
    "t_connector": ("attr_connector_type", "t_connectortag", "attr_elementid"),
    "t_operation": ("Operation", None, None),
}
UNKNOWN_PROFILE = "(unknown)"


def _target(rs: RecordSet, guid: str) -> Ref | None:
    return next((ref for ref in rs.by_guid(guid) if ref.table in _TARGETS), None)


def _tags_by_owner(rs: RecordSet) -> dict[Ref, list[tuple[str, str]]]:
    tags: dict[Ref, list[tuple[str, str]]] = defaultdict(list)
    for _, tag_table, owner_col in _TARGETS.values():
        if tag_table is None:
            continue
        for record in rs.records(tag_table):
            owner = record.values.get(owner_col)
            if isinstance(owner, Ref):
                tags[owner].append((record.values.get("attr_property") or "", record.values.get("attr_value") or ""))
    return tags


def infer(rs: RecordSet) -> list[Catalogue]:
    """One catalogue per profile seen in ``t_xref`` stereotype lists; defaults are the most common tag values."""
    tags_of = _tags_by_owner(rs)
    # (profile, name) -> set of target refs
    targets: dict[tuple[str, str], set[Ref]] = defaultdict(set)
    for xref in rs.records("t_xref"):
        if xref.values.get("attr_name") != "Stereotypes":
            continue
        try:
            entries = parse_stereotypes(xref.values.get("attr_description"))
        except StereoFormatError:
            continue
        target = _target(rs, xref.values.get("attr_client") or "")
        if target is None:
            continue
        for entry in entries:
            profile, _, name = entry.fqname.rpartition("::") if entry.fqname else (UNKNOWN_PROFILE, "", entry.name)
            targets[(profile or UNKNOWN_PROFILE, name)].add(target)

    by_profile: dict[str, list[StereotypeDef]] = defaultdict(list)
    for (profile, name), refs in sorted(targets.items()):
        applies = set()
        values: dict[str, Counter] = defaultdict(Counter)
        for ref in refs:
            metaclass = _TARGETS[ref.table][0]
            record = rs.resolve(ref)
            applies.add(record.values.get(metaclass) if metaclass.startswith("attr_") and record else metaclass)
            for tag, value in tags_of.get(ref, ()):
                values[tag][value] += 1
        tags = [
            TagDef(name=tag, default=min(counts, key=lambda v: (-counts[v], v)))
            for tag, counts in sorted(values.items())
        ]
        by_profile[profile].append(
            StereotypeDef(
                name=name,
                applies_to=sorted(a for a in applies if a),
                tags=tags,
                inferred_count=len(refs),
            )
        )
    source = Source(kind="inferred", file=str(rs.meta.get("path", "")))
    return [Catalogue(profile=p, source=source, stereotypes=defs) for p, defs in sorted(by_profile.items())]
