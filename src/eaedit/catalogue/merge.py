"""Combine catalogues from several sources; the most authoritative source wins per stereotype."""

from eacore.catalogue import Catalogue, CatalogueSet

PRECEDENCE = {"yaml": 0, "eaidl": 0, "mdg": 1, "inferred": 2}


def merge(*catalogues: Catalogue) -> CatalogueSet:
    # sorted() is stable, so equal-precedence catalogues keep the order the caller gave.
    return CatalogueSet(sorted(catalogues, key=lambda c: PRECEDENCE[c.source.kind]))


def by_profile(catalogues: CatalogueSet) -> list[Catalogue]:
    """One catalogue per profile, as ``merge`` resolves it: per name, the first (most authoritative) entry wins.

    The source is the most authoritative contributor's; profiles keep their first-seen order.
    """
    grouped: dict[str, list[Catalogue]] = {}
    for cat in catalogues.catalogues:
        grouped.setdefault(cat.profile, []).append(cat)

    def first_by(items, key):
        chosen: dict = {}
        for item in items:
            chosen.setdefault(key(item), item)
        return list(chosen.values())

    result = []
    for profile, cats in grouped.items():
        result.append(
            Catalogue(
                profile=profile,
                source=cats[0].source,
                stereotypes=first_by((s for c in cats for s in c.stereotypes), lambda s: s.name),
                relationships=first_by((r for c in cats for r in c.relationships), lambda r: (r.metaclass, r.target)),
                diagrams=first_by((d for c in cats for d in c.diagrams), lambda d: d.name),
                toolboxes=first_by((t for c in cats for t in c.toolboxes), lambda t: t.name),
            )
        )
    return result
