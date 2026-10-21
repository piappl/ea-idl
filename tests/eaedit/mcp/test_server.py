import asyncio
import os
import re
from pathlib import Path

import pytest

pytest.importorskip("mcp")

from mcp.client import Client  # noqa: E402

from eaedit.mcp.server import build_server, main, parse_config  # noqa: E402
from eaedit.mcp.workspace import Config, Workspace  # noqa: E402

CORE = "Model::core"
MSG = "Model::core::message"
TOOLS = {
    "overview",
    "search",
    "describe",
    "usages",
    "stereotype",
    "open_session",
    "session_status",
    "operations",
    "edit",
    "undo",
    "discard",
    "preview",
    "commit",
    "export_changes",
    "apply_changes",
    "diagram",
    "diagram_svg",
    "import_svg",
    "check",
    "idl_diff",
}


def _workspace(qea_copy, nafv4_path, tmp_path, **kw):
    path = qea_copy(nafv4_path)
    return Workspace(Config(path, out_dir=tmp_path / "out", **kw))


def _run(workspace, calls):
    """Call the tools in order through the in-memory client; return (is_error, text) per call."""

    async def go():
        out = []
        async with Client(build_server(workspace)) as client:
            for name, args in calls:
                result = await client.call_tool(name, args)
                out.append((result.is_error, "\n".join(c.text for c in result.content)))
        return out

    return asyncio.run(go())


def test_tool_names_and_docs(qea_copy, nafv4_path, tmp_path):
    async def go():
        async with Client(build_server(_workspace(qea_copy, nafv4_path, tmp_path))) as client:
            return (await client.list_tools()).tools

    tools = asyncio.run(go())
    assert {t.name for t in tools} == TOOLS
    assert all(t.description and "Example:" in t.description for t in tools)


def test_end_to_end(qea_copy, nafv4_path, tmp_path):
    ws = _workspace(qea_copy, nafv4_path, tmp_path)
    results = _run(
        ws,
        [
            ("search", {"text": "MessageHeader", "kind": "element"}),
            ("open_session", {"focus": [CORE]}),
            ("edit", {"op": "create_element", "args": {"package": MSG, "name": "Thing"}}),
            ("edit", {"op": "add_attribute", "args": {"el": f"{MSG}::Thing", "name": "size", "type": "long"}}),
            ("session_status", {}),
            ("describe", {"id": f"{MSG}::Thing"}),
            ("preview", {"diagrams": True}),
            ("commit", {}),
            ("describe", {"id": f"{MSG}::Thing"}),
            ("session_status", {}),
        ],
    )
    assert not any(err for err, _ in results), results
    search, opened, created, added, status, staged, preview, commit, described, closed = (t for _, t in results)
    assert f"{MSG}::MessageHeader" in search
    assert "session opened" in opened and CORE in opened
    assert re.fullmatch(r"ok \{[0-9A-F-]+\}", created.splitlines()[0])
    assert added.startswith("ok {")
    assert "2 operations" in status and "create_element" in status
    assert "size" in staged  # explore tools read the session's working copy
    assert "Thing" in preview and "size" in preview
    assert "Thing" in commit
    assert "size" in described and "long" in described
    assert "no session" in closed
    assert ws.session is None


def test_edit_errors(qea_copy, nafv4_path, tmp_path):
    ws = _workspace(qea_copy, nafv4_path, tmp_path)
    (before, before_text), (_, _), (unknown, unknown_text), (bad, bad_text), (json_err, json_text) = _run(
        ws,
        [
            ("edit", {"op": "create_element", "args": {"package": MSG, "name": "X"}}),
            ("open_session", {"focus": CORE}),
            ("edit", {"op": "create_elemnt", "args": {}}),
            ("edit", {"op": "add_attribute", "args": {"element": "x", "name": "a"}}),
            ("edit", {"op": "create_element", "args": "{not json"}),
        ],
    )
    assert before and before_text.startswith("error:") and "open_session" in before_text
    assert unknown and unknown_text.startswith("error:") and "create_element" in unknown_text
    assert bad and bad_text.startswith("error:") and "el" in bad_text and "Traceback" not in bad_text
    assert json_err and json_text.startswith("error:")


def test_edit_takes_args_as_json_text(qea_copy, nafv4_path, tmp_path):
    ws = _workspace(qea_copy, nafv4_path, tmp_path)
    results = _run(
        ws,
        [
            ("open_session", {"focus": [CORE]}),
            ("edit", {"op": "create_element", "args": '{"package": "%s", "name": "J"}' % MSG}),
            ("undo", {}),
            ("discard", {}),
        ],
    )
    assert [err for err, _ in results] == [False] * 4
    assert results[1][1].startswith("ok {")
    assert "create_element" in results[2][1]


def test_describe_ambiguity_lists_candidates(qea_copy, nafv4_path, tmp_path):
    ws = _workspace(qea_copy, nafv4_path, tmp_path)
    ws.open_session(focus=[MSG])
    ws.run("create_package", {"parent": MSG, "name": "Dup"})
    ws.run("create_element", {"package": MSG, "name": "Dup"})
    ws.commit()
    ((err, text),) = _run(ws, [("describe", {"id": f"{MSG}::Dup"})])
    lines = text.splitlines()
    assert not err and lines[0] == f"ambiguous: {MSG}::Dup"
    assert len(lines) == 3 and all(re.search(r"\{[0-9A-Fa-f-]+\}$", x) for x in lines[1:])


def test_explore_errors_and_operations(qea_copy, nafv4_path, tmp_path):
    ws = _workspace(qea_copy, nafv4_path, tmp_path)
    (nf, nf_text), (_, ops), (_, one), (unk, unk_text), (_, stereo), (_, ov) = _run(
        ws,
        [
            ("describe", {"id": "Model::nope"}),
            ("operations", {}),
            ("operations", {"name": "add_attribute"}),
            ("operations", {"name": "add_atribute"}),
            ("stereotype", {"name": "idlStruct"}),
            ("overview", {"depth": 1}),
        ],
    )
    assert nf and nf_text.startswith("error:") and "search" in nf_text
    assert "create_element(" in ops and "add_attribute(" in ops and "session" not in ops.split("(", 1)[1][:10]
    assert one.startswith("add_attribute(el")
    assert unk and "add_attribute" in unk_text
    assert "idlStruct" in stereo
    assert ov.startswith("Model")


def test_checks_and_diagrams(qea_copy, nafv4_path, tmp_path):
    ws = _workspace(qea_copy, nafv4_path, tmp_path)
    results = _run(
        ws,
        [
            ("check", {}),
            ("idl_diff", {}),
            ("search", {"kind": "diagram"}),
        ],
    )
    (_, check), (idl_err, idl_text), (_, diagrams) = results
    assert check.startswith("no integrity errors") or "error" in check
    assert idl_err and "open_session" in idl_text
    guid = re.search(r"\{[0-9A-Fa-f-]+\}$", diagrams.splitlines()[0]).group(0)
    (_, text), (_, svg), (_, _), (imp_err, imported), (_, check2) = _run(
        ws,
        [
            ("diagram", {"id": guid}),
            ("diagram_svg", {"id": guid}),
            ("open_session", {}),
            ("import_svg", {"svg": "<svg></svg>"}),
            ("check", {}),
        ],
    )
    assert text.startswith("diagram ")
    assert "<svg" in svg
    assert imp_err and imported.startswith("error:")
    assert check2 == "no new integrity issues"


def test_idl_diff_and_preview(qea_copy, nafv4_path, tmp_path):
    config = tmp_path / "idl.yaml"
    config.write_text(
        'database_url: "sqlite:///unused.qea"\n'
        'root_packages: ["{753A4DFC-7876-4b00-BB5A-6274AD3817C3}"]\n'
        'template: "idl_just_defs.jinja2"\n'
        'filter_stereotypes: ["lobw"]\n',
        encoding="utf-8",
    )
    ws = _workspace(qea_copy, nafv4_path, tmp_path, idl_configs=[config], focus=[CORE])
    edit = {"el": f"{MSG}::Message", "name": "zazolcMember", "type": "int"}
    results = _run(
        ws,
        [
            ("open_session", {}),
            ("edit", {"op": "add_attribute", "args": edit}),
            ("idl_diff", {}),
            ("preview", {"idl": True}),
        ],
    )
    assert not any(err for err, _ in results), results
    (_, _), (_, _), (_, diff), (_, preview) = results
    assert diff.startswith("IDL diff (idl.yaml):") and "+" in diff and "zazolcMember" in diff
    assert "IDL diff (idl.yaml):" in preview and preview.count("zazolcMember") >= 2


def test_export_and_apply(qea_copy, nafv4_path, tmp_path):
    ws = _workspace(qea_copy, nafv4_path, tmp_path, focus=[CORE])
    results = _run(
        ws,
        [
            ("open_session", {}),
            ("edit", {"op": "create_element", "args": {"package": MSG, "name": "Pkg"}}),
            ("export_changes", {"name": "cp1"}),
            ("export_changes", {"name": "cp1"}),
            ("discard", {}),
            ("apply_changes", {"path": "cp1"}),
            ("session_status", {}),
        ],
    )
    (_, _), (_, _), (_, exported), (again, again_text), (_, _), (apply_err, applied), (_, status) = results
    assert str(tmp_path / "out" / "cp1") in exported and "Pkg" in exported
    assert again and again_text.startswith("error:") and "overwrite" in again_text
    assert not apply_err and "replayed 1 of 1" in applied and "Pkg" in applied
    assert "1 operations" in status


def test_unexpected_exception_is_one_line(qea_copy, nafv4_path, tmp_path, monkeypatch):
    from eaedit.mcp import explore

    def boom(*args, **kwargs):
        raise RuntimeError("kaput")

    monkeypatch.setattr(explore, "overview", boom)
    ((err, text),) = _run(_workspace(qea_copy, nafv4_path, tmp_path), [("overview", {})])
    assert err and text == "error: RuntimeError: kaput"


def test_main_help(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "EAEDIT_MCP_MODEL" in out and "--idl-config" in out


def test_parse_config(tmp_path):
    model = tmp_path / "m.qea"
    model.write_bytes(b"")
    argv = [str(model), "-c", "a.xml", "-c", "b.yaml", "--idl-config", "i.yaml", "--author", "me"]
    argv += ["--timezone", "Europe/Warsaw", "--focus", "Model::a", "--focus", "Model::b", "--policy", "package"]
    argv += ["--out", str(tmp_path / "o")]
    config = parse_config(argv, {})
    assert config == Config(
        model,
        catalogues=[Path("a.xml"), Path("b.yaml")],
        idl_configs=[Path("i.yaml")],
        author="me",
        timezone="Europe/Warsaw",
        focus=["Model::a", "Model::b"],
        policy="package",
        out_dir=tmp_path / "o",
    )


def test_parse_config_from_env(tmp_path):
    model = tmp_path / "m.qea"
    model.write_bytes(b"")
    env = {
        "EAEDIT_MCP_MODEL": str(model),
        "EAEDIT_MCP_CATALOGUES": os.pathsep.join(["a.xml", "b.yaml"]),
        "EAEDIT_MCP_IDL_CONFIGS": "i.yaml",
        "EAEDIT_MCP_AUTHOR": "env",
        "EAEDIT_MCP_FOCUS": "Model::a;Model::b",
        "EAEDIT_MCP_POLICY": "off",
        "EAEDIT_MCP_OUT": str(tmp_path / "o"),
    }
    config = parse_config([], env)
    assert config.model == model
    assert config.catalogues == [Path("a.xml"), Path("b.yaml")]
    assert config.idl_configs == [Path("i.yaml")]
    assert (config.author, config.timezone, config.policy) == ("env", None, "off")
    assert config.focus == ["Model::a", "Model::b"]
    assert config.out_dir == tmp_path / "o"
    # the command line wins over the environment
    assert parse_config(["--author", "cli"], env).author == "cli"


def test_parse_config_errors(tmp_path):
    import click

    with pytest.raises(click.UsageError):
        parse_config([], {})
    with pytest.raises(click.BadParameter):
        parse_config([str(tmp_path / "missing.qea")], {})
    model = tmp_path / "m.qea"
    model.write_bytes(b"")
    with pytest.raises(click.BadParameter):
        parse_config([str(model), "--policy", "nope"], {})


def test_eaedit_mcp_passes_through():
    from click.testing import CliRunner

    from eaedit.cli import cli

    result = CliRunner().invoke(cli, ["mcp", "--help"])
    assert result.exit_code == 0 and "EAEDIT_MCP_MODEL" in result.output
    result = CliRunner().invoke(cli, ["mcp"])
    assert result.exit_code == 2 and "MODEL" in result.output
