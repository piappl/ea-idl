"""Combine catalogues from several sources; the most authoritative source wins per stereotype."""

from eacore.catalogue import Catalogue, CatalogueSet

PRECEDENCE = {"yaml": 0, "eaidl": 0, "mdg": 1, "inferred": 2}


def merge(*catalogues: Catalogue) -> CatalogueSet:
    # sorted() is stable, so equal-precedence catalogues keep the order the caller gave.
    return CatalogueSet(sorted(catalogues, key=lambda c: PRECEDENCE[c.source.kind]))
