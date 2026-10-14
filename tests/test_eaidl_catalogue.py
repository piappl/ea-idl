from click.testing import CliRunner

from eacore.catalogue import Catalogue
from eaidl.catalogue import idl_catalogue
from eaidl.cli import cli
from eaidl.config import Configuration


def _by_name(cat):
    return {s.name: s for s in cat.stereotypes}


def test_idl_catalogue_defaults():
    cat = idl_catalogue(Configuration())
    assert cat.profile == "IDL"
    assert cat.source.kind == "eaidl"
    by = _by_name(cat)
    for name in ("idlStruct", "idlUnion", "idlEnum", "idlMap", "idlTypedef"):
        assert by[name].applies_to == ["Class"]
    assert by["key"].applies_to == ["Attribute"]
    assert by["value"].applies_to == ["Attribute"]
    assert by["optional"].applies_to == ["Attribute"]
    assert by["union"].applies_to == ["Association"]
    assert by["values"].applies_to == ["Association"]
    # NAF stereotypes that eaidl requires, not ones it defines
    assert "DataElement" not in by
    assert "DataModel" not in by


def test_idl_catalogue_respects_config():
    cfg = Configuration()
    cfg.stereotypes.idl_struct = "Foo"
    by = _by_name(idl_catalogue(cfg))
    assert "Foo" in by
    assert "idlStruct" not in by


def test_idl_catalogue_merges_duplicates_and_lists():
    cfg = Configuration(filter_stereotypes=["lobw", "key"], keep_stereotypes=["lobw"])
    by = _by_name(idl_catalogue(cfg))
    assert by["lobw"].applies_to == []
    assert by["key"].applies_to == ["Attribute"]
    assert [s.name for s in idl_catalogue(cfg).stereotypes].count("lobw") == 1


def test_catalogue_command_writes_yaml(tmp_path):
    out = tmp_path / "out.yaml"
    result = CliRunner().invoke(cli, ["catalogue", "--config", "tests/data/config.yaml", "-o", str(out)])
    assert result.exit_code == 0, result.output
    assert Catalogue.load_yaml(out).profile == "IDL"
