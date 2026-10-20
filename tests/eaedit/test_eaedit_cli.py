import re
import sqlite3

import yaml
from click.testing import CliRunner

from eacore.records import Ref
from eacore.catalogue import Catalogue, Source, StereotypeDef
from eaedit import Session
from eaedit.cli import cli
from eaedit.diagrams.svg import export_svg, import_svg

MESSAGE = "{3522A830-8853-4c52-9908-40871435BB3B}"  # Model::core::message


def _changes(path, ops):
    path.write_text(yaml.safe_dump({"eaedit": 1, "source": "nafv4.qea", "author": "tester", "ops": ops}))
    return path


def _op(op, /, **args):
    return {"op": op, "at": "2026-01-02 03:04:05", "args": args}


def test_cli_preview_and_apply(nafv4_path, qea_copy, tmp_path, mini_mdg_path):
    model = qea_copy(nafv4_path)
    changes = _changes(
        tmp_path / "changes.yaml",
        [
            _op("create_element", package="Model::core::message", name="Gadget", stereotype="MINI::Thing"),
            _op("set_tag", target="Model::core::message::Gadget", name="kind", value="b"),
        ],
    )
    runner = CliRunner()
    before = model.read_bytes()
    common = [str(model), str(changes), "-c", str(mini_mdg_path), "--focus", MESSAGE, "--policy", "package"]

    result = runner.invoke(cli, ["preview", *common])
    assert result.exit_code == 0, result.output
    assert "Gadget" in result.output
    assert model.read_bytes() == before

    result = runner.invoke(cli, ["apply", *common])
    assert result.exit_code == 0, result.output
    assert model.read_bytes() != before
    assert Session.open(model).get("Model::core::message::Gadget")["tags"]["kind"] == "b"

    bad = _changes(tmp_path / "bad.yaml", [_op("no_such_op", name="x")])
    result = runner.invoke(cli, ["apply", str(model), str(bad)])
    assert result.exit_code == 1
    lines = result.output.strip().splitlines()
    assert len(lines) == 1 and lines[0].lower().startswith("error:") and "no_such_op" in lines[0]


def test_cli_scope_violation_is_one_line(nafv4_path, qea_copy, tmp_path):
    model = qea_copy(nafv4_path)
    changes = _changes(tmp_path / "c.yaml", [_op("create_element", package="Model::core::data", name="Out")])
    result = CliRunner().invoke(cli, ["preview", str(model), str(changes), "--focus", MESSAGE, "--policy", "package"])
    assert result.exit_code == 1
    assert len(result.output.strip().splitlines()) == 1 and "outside the focus" in result.output


def test_cli_wrong_value_type_is_one_line(nafv4_path, qea_copy, tmp_path):
    model = qea_copy(nafv4_path)
    attr = "Model::core::message::Message.header"
    changes = _changes(tmp_path / "c.yaml", [_op("move_attribute", attr=attr, position="first")])
    result = CliRunner().invoke(cli, ["preview", str(model), str(changes)])
    assert result.exit_code == 1, result.output
    lines = result.output.strip().splitlines()
    assert len(lines) == 1 and lines[0].startswith("Error:") and "move_attribute" in lines[0]


def test_cli_author_option(nafv4_path, qea_copy, tmp_path):
    model = qea_copy(nafv4_path)
    changes = _changes(tmp_path / "c.yaml", [_op("create_element", package="Model::core::message", name="Mine")])
    result = CliRunner().invoke(cli, ["apply", str(model), str(changes), "--author", "reviewer"])
    assert result.exit_code == 0, result.output
    assert Session.open(model).get("Model::core::message::Mine")["author"] == "reviewer"
    result = CliRunner().invoke(cli, ["apply", str(model), str(changes)])
    assert result.exit_code == 0, result.output
    authors = {Session.open(model).get(row["guid"])["author"] for row in Session.open(model).search("Mine")}
    assert authors == {"reviewer", "tester"}  # without --author: the change file's


def test_cli_catalogue_build_and_show(mini_mdg_path, tmp_path):
    runner = CliRunner()
    out = tmp_path / "mini.yaml"
    result = runner.invoke(cli, ["catalogue", "build", str(mini_mdg_path), "-o", str(out)])
    assert result.exit_code == 0, result.output
    cat = Catalogue.load_yaml(out)
    assert cat.profile == "MINI" and {s.name for s in cat.stereotypes} >= {"Base", "Thing", "Link"}

    result = runner.invoke(cli, ["catalogue", "show", str(out)])
    assert result.exit_code == 0, result.output
    assert "MINI::Thing" in result.output and "MINI::Link" in result.output

    result = runner.invoke(cli, ["catalogue", "show", str(out), "Thing"])
    assert result.exit_code == 0, result.output
    assert "MINI::Thing" in result.output
    assert "kind" in result.output and "owner" in result.output  # own and inherited tags
    assert "Class" in result.output

    result = runner.invoke(cli, ["catalogue", "show", str(out), "Nope"])
    assert result.exit_code == 1 and len(result.output.strip().splitlines()) == 1


def test_cli_catalogue_build_several_profiles_writes_a_list(mini_mdg_path, tmp_path):
    other = tmp_path / "other.yaml"
    Catalogue(profile="OTHER", source=Source(kind="yaml"), stereotypes=[StereotypeDef(name="Widget")]).save_yaml(other)
    # a second MINI source: merged into the one MINI entry, the MDG's own definitions first
    extra = tmp_path / "extra.yaml"
    Catalogue(profile="MINI", source=Source(kind="yaml"), stereotypes=[StereotypeDef(name="Extra")]).save_yaml(extra)
    out = tmp_path / "all.yaml"
    result = CliRunner().invoke(cli, ["catalogue", "build", str(mini_mdg_path), str(other), str(extra), "-o", str(out)])
    assert result.exit_code == 0, result.output
    raw = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert isinstance(raw, list) and sorted(c["profile"] for c in raw) == ["MINI", "OTHER"]
    mini = next(c for c in raw if c["profile"] == "MINI")
    assert {s["name"] for s in mini["stereotypes"]} >= {"Thing", "Extra"}

    result = CliRunner().invoke(cli, ["catalogue", "show", str(out)])
    assert result.exit_code == 0, result.output
    assert "OTHER::Widget" in result.output and "MINI::Extra" in result.output and "MINI::Thing" in result.output


L7 = "{0BA44FD3-F22C-4f9a-AC35-3BDB736B3C80}"


def test_preview_renders_changed_diagrams(nafv4_path, qea_copy):
    session = Session.open(qea_copy(nafv4_path), policy="off")
    assert session.preview().diagrams == {}
    session.create_diagram("Model::core::message", "Fresh", "Class")
    rendered = session.preview().diagrams
    assert [d.name for d in rendered.values()] == ["Fresh"]
    assert "<svg" in next(iter(rendered.values())).svg
    assert session.preview(render=False).diagrams == {}


def test_cli_preview_writes_diagram_svgs(nafv4_path, qea_copy, tmp_path):
    model = qea_copy(nafv4_path)
    changes = _changes(
        tmp_path / "changes.yaml", [_op("create_diagram", owner="Model::core::message", name="Fresh", type="Class")]
    )
    out = tmp_path / "out"
    result = CliRunner().invoke(cli, ["preview", str(model), str(changes), "--policy", "off", "--out", str(out)])
    assert result.exit_code == 0, result.output
    assert "<svg" in (out / "Fresh.svg").read_text(encoding="utf-8")


def test_cli_renders_only_with_out(nafv4_path, qea_copy, tmp_path, monkeypatch):
    import eaedit.diagrams.render as render

    model = qea_copy(nafv4_path)
    changes = _changes(
        tmp_path / "changes.yaml", [_op("create_diagram", owner="Model::core::message", name="Fresh", type="Class")]
    )
    svg = tmp_path / "l7.svg"
    runner = CliRunner()
    assert runner.invoke(cli, ["diagram", "export", str(model), L7, "-o", str(svg)]).exit_code == 0
    svg.write_text(re.sub(r'data-ea-name="[^"]*"', 'data-ea-name="R"', svg.read_text(encoding="utf-8"), count=1))

    def refuse(*args, **kwargs):
        raise AssertionError("rendered without --out")

    monkeypatch.setattr(render, "render_working", refuse)
    result = runner.invoke(cli, ["preview", str(model), str(changes), "--policy", "off"])
    assert result.exit_code == 0, result.output
    result = runner.invoke(cli, ["diagram", "import", str(model), str(svg), "--policy", "off"])
    assert result.exit_code == 0, result.output


def test_cli_diagram_export_import(nafv4_path, qea_copy, tmp_path):
    model = qea_copy(nafv4_path)
    svg = tmp_path / "l7.svg"
    runner = CliRunner()
    result = runner.invoke(cli, ["diagram", "export", str(model), L7, "-o", str(svg)])
    assert result.exit_code == 0, result.output
    assert 'data-ea-guid="' in svg.read_text(encoding="utf-8")

    result = runner.invoke(cli, ["diagram", "import", str(model), str(svg), "--policy", "off"])
    assert result.exit_code == 0, result.output
    assert "no changes" in result.output.lower()

    edited = re.sub(r'data-ea-name="[^"]*"', 'data-ea-name="Renamed"', svg.read_text(encoding="utf-8"), count=1)
    svg.write_text(edited, encoding="utf-8")
    before = model.read_bytes()
    result = runner.invoke(cli, ["diagram", "import", str(model), str(svg), "--policy", "off"])
    assert result.exit_code == 0 and model.read_bytes() == before
    result = runner.invoke(cli, ["diagram", "import", str(model), str(svg), "--policy", "off", "--apply"])
    assert result.exit_code == 0, result.output
    assert Session.open(model).working.get("t_diagram", L7).values["attr_name"] == "Renamed"


def test_preview_renders_after_removals_only(nafv4_path, qea_copy):
    session = Session.open(qea_copy(nafv4_path), policy="off")
    session.remove_from_diagram(L7, "Model::core::message::Message")
    assert list(session.preview().diagrams) == [L7]


def test_changed_diagrams_include_new_connector_between_shown_elements(nafv4_path, qea_copy):
    session = Session.open(qea_copy(nafv4_path), policy="off")
    # Model::core::message::Message and the element generalizing it, both on L7.
    session.connect(
        "{308FD88F-3514-4a20-942B-5CF2F35B042F}", "{9F3D867F-2B36-4ab7-9F95-7EB442443042}", type="Dependency"
    )
    assert not [c for c in session.changes().inserts if c.record.table == "t_diagramlinks"]
    assert L7 in session.changed_diagrams()


def test_preview_does_not_render_deleted_diagram(nafv4_path, qea_copy):
    session = Session.open(qea_copy(nafv4_path), policy="off")
    session.delete_diagram(L7)
    assert session.preview().diagrams == {}


def test_preview_renders_diagram_of_changed_note(nafv4_path, qea_copy):
    session = Session.open(qea_copy(nafv4_path), policy="off")
    note = session.add_note(L7, "first").guid
    session.commit()
    session.set_note_text(note, "second")
    assert list(session.preview().diagrams) == [L7]


def test_dangling_diagram_object_carried_through(nafv4_path, qea_copy):
    model = qea_copy(nafv4_path)
    with sqlite3.connect(model) as conn:
        # An L7 object whose element is gone: the loader keeps the raw Object_ID.
        conn.execute(
            "UPDATE t_diagramobjects SET Object_ID = 999999 WHERE rowid = (SELECT min(o.rowid) FROM t_diagramobjects o"
            " JOIN t_diagram d ON d.Diagram_ID = o.Diagram_ID WHERE d.ea_guid = ?)",
            (L7,),
        )
    session = Session.open(model, policy="off")
    this = Ref("t_diagram", L7)
    dangling = [
        o
        for o in session.working.records("t_diagramobjects")
        if o.values["attr_diagram_id"] == this and not isinstance(o.values["attr_object_id"], Ref)
    ]
    assert len(dangling) == 1
    session.set_note_text(session.add_note(L7, "x").guid, "y")
    assert L7 in session.preview().diagrams
    svg = export_svg(session, L7)
    # Exported as a read-only object (no GUID to name it by), and the unedited file stages nothing.
    assert f'data-ea-duid="{dangling[0].key[1]}"' in svg
    before = len(session.log)
    import_svg(session, svg)
    assert len(session.log) == before
    # Removed from the file: kept, with a warning.
    results = import_svg(session, re.sub(rf'<g[^>]*data-ea-duid="{dangling[0].key[1]}"[^>]*/>', "", svg))
    assert len(session.log) == before
    assert any(w.code == "readonly-kept" for r in results for w in r.warnings)
    session.layout(L7, {"pattern": "suggest"})
    assert session.working.get("t_diagramobjects", dangling[0].key) == dangling[0]
