import pytest

from eacore.catalogue import CatalogueSet
from eaedit.catalogue.mdg import parse_mdg
from eaedit.diagrams.views import ResolvedView, resolve_view
from eaedit.errors import InvalidOperationError

FULL = "NAFv4-Core Physical Resource Specification Viewpoints::P2 - Resource Structure"


def test_resolve_view_forms(naf_mdg_path):
    cats = CatalogueSet(parse_mdg(naf_mdg_path))
    for name in ("NAFv4-Core::P2", "NAFv4-Core::P2 - Resource Structure", FULL):
        assert resolve_view(cats, name) == ResolvedView(FULL, "Custom", "P2", True)
    assert resolve_view(cats, "NAFv4-Core::P1").verified is False


def test_resolve_uml_type():
    assert resolve_view(CatalogueSet([]), "Class") == ResolvedView(None, "Class", "", False)


def test_resolve_unknown_view(naf_mdg_path):
    cats = CatalogueSet(parse_mdg(naf_mdg_path))
    with pytest.raises(InvalidOperationError, match="P99"):
        resolve_view(cats, "NAFv4-Core::P99")
    with pytest.raises(InvalidOperationError, match="Clas"):
        resolve_view(cats, "Clas")


def test_uml_type_spellings():
    cats = CatalogueSet([])
    for given in ("UseCase", "Use Case"):
        assert resolve_view(cats, given).diagram_type == "Use Case"
    assert resolve_view(cats, "StateMachine").diagram_type == "Statechart"
    assert resolve_view(cats, "Communication").diagram_type == "Collaboration"
    assert resolve_view(cats, "Class").verified is False
