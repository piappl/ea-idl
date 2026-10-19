from eacore.catalogue import CatalogueSet, Constraint, DiagramDef
from eaedit.catalogue import mdg
from eaedit.catalogue.mdg import Erratum, parse_mdg


def _stereo(cat, name):
    return next(s for s in cat.stereotypes if s.name == name)


def test_parse_mini_profile(mini_mdg_path):
    cats = parse_mdg(mini_mdg_path)
    assert len(cats) == 1
    cat = cats[0]
    assert cat.profile == "MINI"
    assert cat.source.kind == "mdg"
    assert cat.source.version == "1.0"
    assert cat.source.file == "mini-mdg.xml"
    assert {s.name for s in cat.stereotypes} == {"Base", "Thing", "Link"}
    assert _stereo(cat, "Base").abstract
    assert _stereo(cat, "Thing").generalizes == ["Base"]
    assert _stereo(cat, "Thing").applies_to == ["Class"]
    assert _stereo(cat, "Thing").properties == {"_defaultName": "Thing"}
    assert _stereo(cat, "Base").style == {"bgcolor": 255}
    assert cat.relationships[0].metaclass == "Dependency"


def test_non_ascii_notes_decoded(mini_mdg_path):
    assert "Café" in _stereo(parse_mdg(mini_mdg_path)[0], "Base").notes


def test_tag_types_from_property_types(mini_mdg_path):
    thing = _stereo(parse_mdg(mini_mdg_path)[0], "Thing")
    ref = next(t for t in thing.tags if t.name == "ref")
    assert (ref.type, ref.values, ref.stereotypes) == ("RefGUID", ["Class"], ["Thing"])
    kind = next(t for t in thing.tags if t.name == "kind")
    assert kind.values == ["a", "b"]
    assert kind.default == "a"


def test_erratum_applied_and_recorded(mini_mdg_path, monkeypatch):
    erratum = Erratum("realizingMeassage", "realizingMessage", "typo")
    monkeypatch.setitem(mdg.ERRATA, ("MINI", "1.0"), [erratum])
    cat = parse_mdg(mini_mdg_path)[0]
    assert Constraint(role="realizingMessage", target="MINI::Thing") in _stereo(cat, "Link").constraints
    assert cat.source.errata == ["realizingMeassage -> realizingMessage"]


def test_no_erratum_keeps_text(mini_mdg_path):
    cat = parse_mdg(mini_mdg_path)[0]
    assert Constraint(role="realizingMeassage", target="MINI::Thing") in _stereo(cat, "Link").constraints
    assert cat.source.errata == []


def test_multi_target_constraint_split(mini_mdg_path):
    constraints = _stereo(parse_mdg(mini_mdg_path)[0], "Link").constraints
    assert [c.target for c in constraints if c.role == "source"] == ["MINI::Thing", "MINI::Base"]


def test_diagrams_and_toolboxes(mini_mdg_path):
    cat = parse_mdg(mini_mdg_path)[0]
    assert cat.diagrams == [DiagramDef(name="D1", base="Custom", id="D1", alias="Diagram one", toolbox="MINI-D1")]
    assert [(t.name, t.items) for t in cat.toolboxes] == [("MINI-D1", ["MINI::Thing"])]


def test_real_naf_mdg(naf_mdg_path):
    (cat,) = parse_mdg(naf_mdg_path)
    assert cat.profile == "NAFv4-Core"
    assert len(cat.stereotypes) > 150
    assert "realizingMeassage -> realizingMessage" in cat.source.errata
    assert all(c.role != "realizingMeassage" for s in cat.stereotypes for c in s.constraints)
    assert len(cat.toolboxes) > 30
    assert len(cat.diagrams) > 40
    resolved = CatalogueSet([cat]).resolved("ActualEnterprisePhase")
    assert {"startDate", "endDate"} <= {t.name for t in resolved.tags}
    to_be = next(t for t in CatalogueSet([cat]).resolved("ArchitecturalDescription").tags if t.name == "toBe")
    assert (to_be.type, to_be.values) == ("boolean", ["true", "false"])
