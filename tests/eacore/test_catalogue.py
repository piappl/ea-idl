import pytest

from eacore.catalogue import (
    AmbiguousStereotype,
    Catalogue,
    CatalogueSet,
    Constraint,
    Source,
    StereotypeDef,
    UNKNOWN_PROFILE,
    TagDef,
)


def _cat(profile, *stereotypes, kind="yaml"):
    return Catalogue(profile=profile, source=Source(kind=kind, file=f"{profile}.yaml"), stereotypes=list(stereotypes))


def test_yaml_roundtrip(tmp_path):
    cat = _cat(
        "P",
        StereotypeDef(
            name="X",
            applies_to=["Class"],
            generalizes=["Y"],
            tags=[TagDef(name="t", type="enumeration", values=["a", "b"], default="a", stereotypes=["Z"])],
            constraints=[Constraint(role="source", target="P::Y")],
            properties={"direction": "in"},
            style={"bgcolor": 54216, "font": "x"},
            inferred_count=3,
        ),
    )
    path = tmp_path / "cat.yaml"
    cat.save_yaml(path)
    assert Catalogue.load_yaml(path) == cat


def test_lookup_bare_and_qualified():
    cs = CatalogueSet([_cat("P", StereotypeDef(name="X"))])
    assert cs.lookup("X") == "P::X"
    assert cs.lookup("P::X") == "P::X"
    assert cs.lookup("Q::X") is None
    assert cs.lookup("P::Nope") is None
    assert cs.lookup("Nope") is None


def test_lookup_ambiguous_bare_name():
    cs = CatalogueSet([_cat("P", StereotypeDef(name="DataElement")), _cat("Q", StereotypeDef(name="DataElement"))])
    with pytest.raises(AmbiguousStereotype) as exc:
        cs.lookup("DataElement")
    assert exc.value.candidates == ["P::DataElement", "Q::DataElement"]
    with pytest.raises(AmbiguousStereotype):
        cs.stereotype("DataElement")
    assert cs.lookup("Q::DataElement") == "Q::DataElement"


def test_earlier_catalogue_wins():
    first = _cat("P", StereotypeDef(name="X", notes="first"), kind="yaml")
    second = _cat("P", StereotypeDef(name="X", notes="second"), kind="mdg")
    cs = CatalogueSet([first, second])
    assert cs.stereotype("P::X").notes == "first"
    assert cs.origin("P::X").kind == "yaml"
    assert cs.fqnames() == ["P::X"]


def test_resolved_inherits_tags_nearest_first():
    cs = CatalogueSet(
        [
            _cat(
                "P",
                StereotypeDef(name="C", generalizes=["B"], tags=[TagDef(name="own")]),
                StereotypeDef(name="B", generalizes=["P::A"], tags=[TagDef(name="t1", default="b")]),
                StereotypeDef(
                    name="A",
                    applies_to=["Class"],
                    tags=[TagDef(name="t1", default="a"), TagDef(name="t2")],
                    constraints=[Constraint(role="r", target="P::A")],
                ),
            )
        ]
    )
    res = cs.resolved("C")
    assert res.fqname == "P::C"
    assert [t.name for t in res.tags] == ["own", "t1", "t2"]
    assert next(t for t in res.tags if t.name == "t1").default == "b"
    assert res.applies_to == ["Class"]
    assert res.constraints == [Constraint(role="r", target="P::A")]
    assert cs.resolved("Nope") is None


def test_resolved_cycle_terminates():
    cs = CatalogueSet(
        [
            _cat(
                "P",
                StereotypeDef(name="A", generalizes=["B", "Missing"], tags=[TagDef(name="t")]),
                StereotypeDef(name="B", generalizes=["A"], tags=[TagDef(name="t"), TagDef(name="u")]),
            )
        ]
    )
    assert [t.name for t in cs.resolved("A").tags] == ["t", "u"]


def test_lookup_bare_name_prefers_named_profile_over_unknown():
    named = _cat("IDL", StereotypeDef(name="idlStruct"))
    unknown = _cat(UNKNOWN_PROFILE, StereotypeDef(name="idlStruct"), StereotypeDef(name="collapse"), kind="inferred")
    cs = CatalogueSet([named, unknown])
    assert cs.lookup("idlStruct") == "IDL::idlStruct"
    assert cs.lookup("collapse") == "(unknown)::collapse"
    assert cs.lookup("(unknown)::idlStruct") == "(unknown)::idlStruct"
    # Two named profiles stay ambiguous, with or without an unknown-profile entry.
    cs = CatalogueSet([named, _cat("Q", StereotypeDef(name="idlStruct")), unknown])
    with pytest.raises(AmbiguousStereotype) as exc:
        cs.lookup("idlStruct")
    assert exc.value.candidates == ["IDL::idlStruct", "Q::idlStruct"]
