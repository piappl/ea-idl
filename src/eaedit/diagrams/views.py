"""Map a diagram type name (UML type or NAF view) to what EA stores in t_diagram."""

from __future__ import annotations

import difflib
from dataclasses import dataclass

from eacore.catalogue import CatalogueSet
from eaedit.errors import InvalidOperationError

# Views with hand-made samples in nafv4.qea; every other view is written from the MDG alone.
_VERIFIED = {
    "P2 - Resource Structure",
    "P6 - Resource Sequence",
    "L7 - Information Model",
    "P7 - Data Model",
}


@dataclass(frozen=True)
class ResolvedView:
    mdg_name: str | None
    diagram_type: str
    view_id: str
    verified: bool


# UML diagram types are accepted as given; nafv4.qea has no hand-made sample of any, so none is verified.
_UML_TYPES = {
    "Class", "Sequence", "Activity", "Component", "Package", "Custom", "Object", "Deployment", "Statechart",
    "UseCase", "Collaboration", "Analysis", "CompositeStructure", "Timing", "InteractionOverview",
}  # fmt: skip


def resolve_view(catalogues: CatalogueSet, type: str) -> ResolvedView:
    if "::" not in type:
        if type in _UML_TYPES:
            return ResolvedView(None, type, "", False)
        raise InvalidOperationError(_unknown(type, sorted(_UML_TYPES)))
    prefix, _, rest = type.partition("::")
    views = [(cat, d) for cat in catalogues.catalogues for d in cat.diagrams if d.profile]
    for cat, d in views:
        if rest not in (d.name, d.id):
            continue
        if prefix in (cat.profile, d.profile):
            return ResolvedView(f"{d.profile}::{d.name}", d.base, d.id, d.name in _VERIFIED)
    names = [f"{cat.profile}::{d.name}" for cat, d in views]
    raise InvalidOperationError(_unknown(type, names))


def _unknown(type: str, names: list[str]) -> str:
    near = difflib.get_close_matches(type, names, n=5, cutoff=0.4)
    msg = f"unknown diagram type or view {type!r}"
    return msg + (f"; near matches: {', '.join(near)}" if near else "")
