import pytest

from eacore.backends.sql import load_file
from eacore.catalogue import Catalogue, Source, StereotypeDef
from eacore.records import Record, RecordSet, Ref
from eaedit.catalogue import load_catalogues
from eaedit.catalogue.infer import infer
from eaedit.catalogue.merge import merge


def test_infer_nafv4(nafv4_path):
    cats = {c.profile: c for c in infer(load_file(nafv4_path))}
    assert {"NAFv4-Core", "IDL"} <= set(cats)
    element = next(s for s in cats["NAFv4-Core"].stereotypes if s.name == "DataElement")
    assert element.applies_to == ["Class"]
    assert element.inferred_count >= 20
    assert cats["IDL"].source.kind == "inferred"


def _model() -> RecordSet:
    rs = RecordSet()
    values = [
        ("x", "{A0000000-0000-0000-0000-000000000001}"),
        ("x", "{A0000000-0000-0000-0000-000000000002}"),
        ("y", "{A0000000-0000-0000-0000-000000000003}"),
    ]
    for i, (value, guid) in enumerate(values):
        rs.add(Record("t_object", guid, {"attr_ea_guid": guid, "attr_object_type": "Class"}))
        rs.add(
            Record(
                "t_objectproperties",
                f"p{i}",
                {"attr_object_id": Ref("t_object", guid), "attr_property": "k", "attr_value": value},
            )
        )
        rs.add(
            Record(
                "t_xref",
                f"x{i}",
                {
                    "attr_name": "Stereotypes",
                    "attr_client": guid,
                    "attr_description": "@STEREO;Name=S;FQName=P::S;@ENDSTEREO;",
                },
            )
        )
    return rs


def test_infer_tag_default_most_common():
    (cat,) = infer(_model())
    (stereo,) = cat.stereotypes
    assert (cat.profile, stereo.name, stereo.inferred_count) == ("P", "S", 3)
    assert [(t.name, t.default) for t in stereo.tags] == [("k", "x")]


def test_merge_precedence():
    def cat(kind):
        return Catalogue(profile="P", source=Source(kind=kind), stereotypes=[StereotypeDef(name="S")])

    cats = [cat("inferred"), cat("mdg"), cat("yaml")]
    assert merge(*cats).origin("P::S").kind == "yaml"
    assert merge(*cats[:2]).origin("P::S").kind == "mdg"


def test_load_catalogues_dispatch(tmp_path, mini_mdg_path, nafv4_path):
    yaml_path = tmp_path / "mine.yaml"
    Catalogue(profile="Y", source=Source(kind="yaml"), stereotypes=[StereotypeDef(name="Own")]).save_yaml(yaml_path)
    cats = load_catalogues([yaml_path, mini_mdg_path, nafv4_path])
    assert cats.lookup("MINI::Thing") and cats.lookup("Y::Own")
    assert cats.origin("IDL::idlStruct").kind == "inferred"
    with pytest.raises(ValueError):
        load_catalogues([tmp_path / "x.txt"])


def test_load_catalogues_infers_from_given_model():
    assert load_catalogues([], _model(), infer_from_model=True).lookup("P::S")
    assert load_catalogues([], _model()).fqnames() == []
