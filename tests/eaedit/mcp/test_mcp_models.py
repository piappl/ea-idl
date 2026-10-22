import shutil
from pathlib import Path

import pytest

from eaedit.errors import EaeditError
from eaedit.mcp.models import Models
from eaedit.mcp.workspace import Config, Workspace


@pytest.fixture
def models(qea_copy, nafv4_path, tmp_path):
    return Models.of(Workspace(Config(qea_copy(nafv4_path), out_dir=tmp_path / "out")))


def test_open_second_model_names_and_out_dir(models, qea_copy, nafv4_path, tmp_path):
    other = qea_copy(nafv4_path, "other.qea")
    assert models.open(other) == "other"
    assert models.names() == ["copy", "other"] and models.default == "copy"
    assert models.get("other").config.out_dir == tmp_path / "eaedit-out-other"
    assert models.get(None) is models.get("copy")


def test_relative_paths_resolve_against_model_folders(models, nafv4_path, tmp_path, mini_mdg_path):
    sub = tmp_path / "b"
    sub.mkdir()
    shutil.copyfile(nafv4_path, sub / "b.qea")
    shutil.copyfile(mini_mdg_path, sub / "rules.xml")
    models.open("b/b.qea", catalogues=["rules.xml"], idl_configs=["idl.yaml"])
    config = models.get("b").config
    assert config.model == sub / "b.qea"
    assert config.catalogues == [sub / "rules.xml"] and config.idl_configs == [sub / "idl.yaml"]


def test_nothing_inherited_but_author_and_timezone(qea_copy, nafv4_path):
    models = Models(author="me", timezone="Europe/Warsaw")
    models.add(Config(qea_copy(nafv4_path), catalogues=[Path("x.xml")], focus=["Model::core"], author="me"))
    models.open(qea_copy(nafv4_path, "other.qea"))
    c = models.get("other").config
    assert (c.catalogues, c.focus, c.idl_configs, c.policy) == ([], [], [], "connected")
    assert (c.author, c.timezone) == ("me", "Europe/Warsaw")


def test_name_and_out_collisions_refused(models, qea_copy, nafv4_path, tmp_path):
    other = qea_copy(nafv4_path, "other.qea")
    with pytest.raises(EaeditError, match="name"):
        models.open(other, name="copy")
    with pytest.raises(EaeditError, match="out"):
        models.open(other, out=str(tmp_path / "out"))
    assert models.open(other, out=str(tmp_path / "out"), read_only=True) == "other"  # read-only skips the check


def test_same_file_twice_refused(models, tmp_path):
    for spelling in ("./copy.qea", str(tmp_path / "copy.qea")):
        with pytest.raises(EaeditError, match="already open"):
            models.open(spelling, name="again")


def test_bad_policy_refused(models, qea_copy, nafv4_path):
    with pytest.raises(EaeditError, match="policy"):
        models.open(qea_copy(nafv4_path, "other.qea"), policy="nope")
    assert models.names() == ["copy"]


def test_open_failure_registers_nothing(models, qea_copy, nafv4_path, tmp_path):
    bad = tmp_path / "bad.qea"
    bad.write_text("not a database")
    with pytest.raises(Exception):
        models.open(bad)
    with pytest.raises(Exception):
        models.open("copy2.qea")  # missing file
    with pytest.raises(Exception):
        models.open(qea_copy(nafv4_path, "other.qea"), catalogues=["missing.xml"])
    assert models.names() == ["copy"]


def test_unknown_name_lists_open_models(models):
    with pytest.raises(EaeditError, match=r"open models: copy.*did you mean copy"):
        models.get("copy.qea")


def test_reopen_reuses_remembered_out_dir(models, qea_copy, nafv4_path, tmp_path):
    other = qea_copy(nafv4_path, "other.qea")
    models.open(other, out=str(tmp_path / "custom"))
    models.close("other")
    models.open(other, name="renamed")
    assert models.get("renamed").config.out_dir == tmp_path / "custom"
    models.close("copy")
    models.open(tmp_path / "copy.qea")
    assert models.get("copy").config.out_dir == tmp_path / "out"


def test_open_default_moves_the_default(models, qea_copy, nafv4_path):
    models.open(qea_copy(nafv4_path, "other.qea"), default=True)
    assert models.default == "other"


def test_close_default_and_counts(models, qea_copy, nafv4_path):
    ws = models.get(None)
    ws.open_session()
    ws.run("create_element", {"package": "Model::core::message", "name": "T"})
    assert models.close("copy") == 1
    assert models.default is None
    with pytest.raises(EaeditError, match="no model is open"):
        models.get(None)
    models.open(qea_copy(nafv4_path, "other.qea"))
    assert models.default == "other"  # first opened when there is no default


def test_no_default_names_the_open_models(models, qea_copy, nafv4_path):
    models.open(qea_copy(nafv4_path, "other.qea"))
    models.close("copy")
    with pytest.raises(EaeditError, match="no default model; pass model= one of: other"):
        models.get(None)
