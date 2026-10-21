import pytest

from eacore.backends.sql import file_hash, load_file
from eacore.diff import diff
from eacore.tablemap import EA_TABLEMAP
from eaedit.errors import EaeditError
from eaedit.mcp.package import apply_changes, commit_with_report, export_changes
from eaedit.mcp.workspace import Config, Workspace

CORE = "Model::core"
MSG = "Model::core::message"


def _workspace(qea_copy, nafv4_path, tmp_path, name="copy.qea", **kw):
    path = qea_copy(nafv4_path, name)
    return path, Workspace(Config(path, focus=[CORE], out_dir=tmp_path / f"out-{name}", **kw))


def _edit(ws):
    ws.open_session()
    ws.run("create_element", {"package": MSG, "name": "PkgThing"})
    ws.run("create_diagram", {"owner": MSG, "name": "Pkg/Diagram"})


def _same(a, b):
    changes = diff(load_file(a), load_file(b)).without_columns(EA_TABLEMAP.volatile)
    assert changes.is_empty()


def test_export_writes_package_without_touching_model(qea_copy, nafv4_path, tmp_path):
    path, ws = _workspace(qea_copy, nafv4_path, tmp_path)
    _edit(ws)
    before = file_hash(path)
    target = export_changes(ws, "my change/1")
    assert target.name == "my_change_1"
    assert file_hash(path) == before
    for name in ("changes.yaml", "report.md", "check.txt"):
        assert (target / name).is_file()
    assert (target / "diagrams" / "Pkg_Diagram.svg").read_text().lstrip().startswith(("<svg", "<?xml"))
    assert "diagrams/Pkg_Diagram.svg" in (target / "report.md").read_text()
    assert "PkgThing" in (target / "report.md").read_text()
    assert ws.session is not None
    with pytest.raises(EaeditError):
        export_changes(ws, "my change/1")
    export_changes(ws, "my change/1", overwrite=True)


def test_export_without_changes_and_check_text(qea_copy, nafv4_path, tmp_path):
    _, ws = _workspace(qea_copy, nafv4_path, tmp_path)
    ws.open_session()
    target = export_changes(ws, "empty")
    assert (target / "check.txt").read_text() == "no new issues\n"
    assert not (target / "diagrams").exists()
    assert not list(target.glob("idl*.diff"))


def test_export_replays_to_same_rows_as_direct_commit(qea_copy, nafv4_path, tmp_path):
    direct, ws1 = _workspace(qea_copy, nafv4_path, tmp_path, "direct.qea")
    _edit(ws1)
    package = export_changes(ws1, "pkg")
    ws1.commit()

    via, ws2 = _workspace(qea_copy, nafv4_path, tmp_path, "via.qea")
    result = apply_changes(ws2, package)
    assert (result.resumed, result.total) == (2, 2)
    assert ws2.working_file.is_file()
    ws2.commit()
    _same(direct, via)

    # a plain .yaml path works too
    again, ws3 = _workspace(qea_copy, nafv4_path, tmp_path, "again.qea")
    apply_changes(ws3, package / "changes.yaml")
    ws3.commit()
    _same(direct, again)


def test_apply_refuses_open_session_and_bad_path(qea_copy, nafv4_path, tmp_path):
    _, ws = _workspace(qea_copy, nafv4_path, tmp_path)
    ws.open_session()
    with pytest.raises(EaeditError):
        apply_changes(ws, tmp_path / "nowhere")
    with pytest.raises(EaeditError):
        apply_changes(ws, tmp_path)
    ws.discard()
    with pytest.raises(EaeditError):
        apply_changes(ws, tmp_path / "nowhere")
    assert ws.session is None


def test_commit_with_report_writes_report(qea_copy, nafv4_path, tmp_path):
    path, ws = _workspace(qea_copy, nafv4_path, tmp_path)
    _edit(ws)
    report = commit_with_report(ws)
    assert "PkgThing" in report
    files = list((ws.config.out_dir / "reports").glob("*.md"))
    assert len(files) == 1 and files[0].read_text() == report
    assert ":" not in files[0].name
    assert ws.session is None


def _idl_config(path):
    path.write_text(
        'database_url: "sqlite:///unused.qea"\n'
        'root_packages: ["{753A4DFC-7876-4b00-BB5A-6274AD3817C3}"]\n'
        'template: "idl_just_defs.jinja2"\n'
        'filter_stereotypes: ["lobw"]\n',
        encoding="utf-8",
    )
    return path


def test_export_idl_diff_files(qea_copy, nafv4_path, tmp_path):
    one = _idl_config(tmp_path / "one.yaml")
    two = _idl_config(tmp_path / "two.yaml")
    _, ws = _workspace(qea_copy, nafv4_path, tmp_path, "a.qea", idl_configs=[one])
    ws.open_session()
    ws.run("add_attribute", {"el": f"{MSG}::Message", "name": "zazolcMember", "type": "int"})
    target = export_changes(ws, "p")
    assert "zazolcMember" in (target / "idl.diff").read_text()
    assert "zazolcMember" in (target / "report.md").read_text()

    _, ws = _workspace(qea_copy, nafv4_path, tmp_path, "b.qea", idl_configs=[one, two])
    ws.open_session()
    target = export_changes(ws, "p")
    assert (target / "idl-one.diff").is_file() and (target / "idl-two.diff").is_file()
    assert "see idl-one.diff" in (target / "report.md").read_text()
