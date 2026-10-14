"""Parse an MDG technology XML into eacore catalogues, repairing known upstream errors first."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from eacore.catalogue import Catalogue, Constraint, DiagramDef, Relationship, Source, StereotypeDef, TagDef, Toolbox


@dataclass(frozen=True)
class Erratum:
    find: str
    replace: str
    reason: str


_REALIZING = Erratum(
    "realizingMeassage",
    "realizingMessage",
    "typo blocks P2 ResourceExchange -> P6 ResourceMessage realization",
)

# (Documentation id or name, version) -> textual fixes applied to the raw XML before parsing.
ERRATA: dict[tuple[str, str], list[Erratum]] = {
    ("NAFv4-Core", "2021.12"): [_REALIZING],
    ("NAFv4-ADMBw", "2022.12"): [_REALIZING],
}

_STYLE_KEYS = ("bgcolor", "fontcolor", "bordercolor", "borderwidth")
_ENCODING = re.compile(rb'encoding="([^"]+)"')
_NOTE_FIELD = re.compile(r"(\w+)\s*=\s*([^;]*)")


def _split(value: str, sep: str) -> list[str]:
    return [part.strip() for part in value.split(sep) if part.strip()]


def _declared_encoding(raw: bytes) -> str:
    match = _ENCODING.search(raw[:200])
    return match.group(1).decode("ascii") if match else "utf-8"


def _load(path: Path) -> tuple[ET.Element, list[str]]:
    raw = path.read_bytes()
    root = ET.fromstring(raw)  # honours the declared encoding
    doc = root.find("Documentation")
    key = (doc.get("id") or doc.get("name") or "", doc.get("version", "")) if doc is not None else ("", "")
    errata = ERRATA.get(key, [])
    if not errata:
        return root, []
    encoding = _declared_encoding(raw)
    text = raw.decode(encoding)
    applied = []
    for erratum in errata:
        if erratum.find in text:
            text = text.replace(erratum.find, erratum.replace)
            applied.append(f"{erratum.find} -> {erratum.replace}")
    return ET.fromstring(text.encode(encoding)), applied


def _property_types(root: ET.Element) -> dict[str, dict[str, str]]:
    """Tag type name -> fields of its ``Notes`` column (``Type=RefGUID; Values=Class; ...``)."""
    types: dict[str, dict[str, str]] = {}
    for row in root.findall("TaggedValueTypes/RefData/DataSet/DataRow"):
        cols = {c.get("name"): c.get("value", "") for c in row.findall("Column")}
        if cols.get("Property"):
            types[cols["Property"]] = dict(_NOTE_FIELD.findall(cols.get("Notes", "")))
    return types


def _tag(el: ET.Element, types: dict[str, dict[str, str]]) -> TagDef:
    tag = TagDef(
        name=el.get("name", ""),
        type=el.get("type", ""),
        default=el.get("default", ""),
        description=el.get("description", ""),
    )
    fields = types.get(tag.type)
    if fields is not None:
        tag.type = fields.get("Type", "")
        tag.values = _split(fields.get("Values", ""), ",")
        tag.stereotypes = _split(fields.get("Stereotypes", ""), ",")
    elif tag.type == "enumeration":
        tag.values = _split(el.get("values", ""), ",")
    return tag


def _stereotype(el: ET.Element, types: dict[str, dict[str, str]]) -> StereotypeDef:
    style: dict[str, str | int] = {}
    for key in _STYLE_KEYS:
        value = el.get(key)
        if value is not None and value != "-1":
            style[key] = int(value) if value.lstrip("-").isdigit() else value
    properties: dict[str, str] = {}
    applies_to = []
    for apply in el.findall("AppliesTo/Apply"):
        applies_to.append(apply.get("type", ""))
        for prop in apply.findall("Property"):
            properties[prop.get("name", "")] = prop.get("value", "")
    constraints = []
    for mc in el.findall("metaconstraints/metaconstraint"):
        # One metaconstraint may allow several targets, separated by ";".
        constraints += [Constraint(role=mc.get("umlRole", ""), target=t) for t in _split(mc.get("constraint", ""), ";")]
    return StereotypeDef(
        name=el.get("name", ""),
        applies_to=applies_to,
        abstract=el.get("isAbstract", "").lower() == "true",
        generalizes=el.get("generalizes", "").split(),
        tags=[_tag(t, types) for t in el.findall("TaggedValues/Tag")],
        constraints=constraints,
        properties=properties,
        style=style,
        notes=el.get("notes", ""),
    )


def _diagram(el: ET.Element) -> DiagramDef:
    apply = el.find("AppliesTo/Apply")
    props: dict[str, str] = {}
    base = ""
    if apply is not None:
        base = apply.get("type", "").removeprefix("Diagram_")
        props = {p.get("name", ""): p.get("value", "") for p in apply.findall("Property")}
    return DiagramDef(
        name=el.get("name", ""),
        base=base,
        id=props.get("diagramID", ""),
        alias=props.get("alias", ""),
        toolbox=props.get("toolbox", ""),
    )


def _toolbox(profile: ET.Element) -> Toolbox:
    items: list[str] = []
    for st in profile.findall("Content/Stereotypes/Stereotype"):
        if st.find("AppliesTo/Apply[@type='ToolboxPage']") is None:
            continue
        for tag in st.findall("TaggedValues/Tag"):
            name = tag.get("name", "")
            # Page settings such as isCollapsed are tags too; items always carry a "(metaclass)" suffix.
            if "(" in name:
                item = name.split("(", 1)[0]
                if item not in items:
                    items.append(item)
    return Toolbox(name=profile.find("Documentation").get("name", ""), items=items)


def parse_mdg(path: str | Path) -> list[Catalogue]:
    """One catalogue per ``UMLProfile``; diagrams and toolboxes go to the profile of the same name, else the first."""
    path = Path(path)
    root, errata = _load(path)
    doc = root.find("Documentation")
    version = doc.get("version", "") if doc is not None else ""
    types = _property_types(root)

    catalogues = []
    for profile in root.findall("UMLProfiles/UMLProfile"):
        stereotypes = [_stereotype(s, types) for s in profile.findall("Content/Stereotypes/Stereotype")]
        relationships = [
            Relationship(metaclass=r.get("metaclass", ""), target=r.get("constraint", ""))
            for r in profile.findall("Content/Stereotypes/Stereotype/metarelationships/metarelationship")
        ]
        catalogues.append(
            Catalogue(
                profile=profile.find("Documentation").get("name", ""),
                source=Source(kind="mdg", file=path.name, version=version, errata=list(errata)),
                stereotypes=stereotypes,
                relationships=relationships,
            )
        )
    if not catalogues:
        return catalogues

    def target(name: str) -> Catalogue:
        return next((c for c in catalogues if c.profile == name), catalogues[0])

    for profile in root.findall("DiagramProfile/UMLProfile"):
        cat = target(profile.find("Documentation").get("name", ""))
        cat.diagrams += [_diagram(s) for s in profile.findall("Content/Stereotypes/Stereotype")]
    for profile in root.findall("UIToolboxes/UMLProfile"):
        cat = target(profile.find("Documentation").get("name", ""))
        cat.toolboxes.append(_toolbox(profile))
    return catalogues
