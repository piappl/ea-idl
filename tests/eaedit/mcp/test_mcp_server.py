import asyncio
import os
import re
from pathlib import Path

import pytest

pytest.importorskip("mcp")

from mcp.client import Client  # noqa: E402

from eaedit.mcp.server import _FIELD_TABLES, build_server, main, parse_config  # noqa: E402
from eaedit.mcp.workspace import Config, Workspace  # noqa: E402

CORE = "Model::core"
MSG = "Model::core::message"
L7 = "Model::L7"
#: What the agent must never read: table names, column keys, raw key tuples.
LEAK = re.compile(r"\bt_[a-z]+|attr_|\(t_|, [0-9A-Fa-f]{8}\)")
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
    assert check == "no integrity errors in the model"
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


def test_sdk_argument_errors_and_unknown_tool(qea_copy, nafv4_path, tmp_path):
    ws = _workspace(qea_copy, nafv4_path, tmp_path)
    (m_err, missing), (t_err, typed), (u_err, unknown) = _run(
        ws, [("describe", {}), ("overview", {"depth": "deep"}), ("descrbe", {"id": "x"})]
    )
    assert m_err and missing == "error: describe: id is required; parameters: describe(id, page=1)"
    assert t_err and typed.startswith("error: overview: depth must be int; parameters: overview(")
    assert u_err and unknown.startswith("error: unknown tool 'descrbe'; did you mean describe")


def test_every_fields_operation_lists_its_fields(qea_copy, nafv4_path, tmp_path):
    import inspect

    from eaedit.ops import OPERATIONS, load_all

    load_all()
    with_fields = {
        name
        for name, fn in OPERATIONS.items()
        if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in inspect.signature(fn).parameters.values())
    }
    assert with_fields <= set(_FIELD_TABLES)
    ((_, text),) = _run(_workspace(qea_copy, nafv4_path, tmp_path), [("operations", {"name": "connect"})])
    assert "fields: " in text and "source_role" in text


def test_messages_use_agent_words(qea_copy, nafv4_path, tmp_path):
    ws = _workspace(qea_copy, nafv4_path, tmp_path)
    results = _run(
        ws,
        [
            ("open_session", {"focus": MSG, "policy": "package"}),
            ("edit", {"op": "create_element", "args": {"package": L7, "name": "Out"}}),
            ("edit", {"op": "delete_element", "args": {"el": f"{L7}::Message"}}),
            ("edit", {"op": "update_element", "args": {"el": f"{MSG}::Message", "bogus": 1}}),
            ("discard", {}),
            ("open_session", {"focus": MSG, "policy": "advisory"}),
            ("edit", {"op": "create_element", "args": {"package": L7, "name": "Out"}}),
            ("session_status", {}),
            ("preview", {}),
        ],
    )
    texts = [t for _, t in results]
    scope_error, diagram_error, field_error = texts[1:4]
    warned, status, preview = texts[6:9]
    assert scope_error.startswith("error: insert element") and f"owned by {L7}" in scope_error
    assert "on diagram" in diagram_error
    assert "unknown field 'bogus' for element" in field_error
    assert "warning scope: insert element" in warned and "warning scope" in status and "outside the focus" in preview
    for text in texts:
        assert not LEAK.search(text), text


def test_integrity_messages_use_agent_words(qea_copy, nafv4_path, tmp_path):
    from eacore.records import Record, Ref

    ws = _workspace(qea_copy, nafv4_path, tmp_path)
    ws.open_session(focus=[CORE], policy="off")
    ws.run("create_element", {"package": MSG, "name": "Broken"})
    session = ws.session
    record = session.working.resolve(session.find(f"{MSG}::Broken", kinds=("element",)))
    values = dict(record.values, attr_classifier=Ref("t_object", "{00000000-0000-0000-0000-000000000000}"))
    session.working.remove(record.table, record.key)
    session.working.add(Record(record.table, record.key, values, record.rid))
    (_, check), (c_err, commit) = _run(ws, [("check", {}), ("commit", {})])
    assert check.startswith("error dangling-reference: classifier -> missing element")
    assert c_err and commit.startswith("error: commit refused") and "dangling-reference" in commit
    assert not LEAK.search(check) and not LEAK.search(commit), (check, commit)


def test_stale_session_resumes_onto_the_changed_file(qea_copy, nafv4_path, tmp_path):
    import shutil

    ws = _workspace(qea_copy, nafv4_path, tmp_path, focus=[CORE])
    other = qea_copy(nafv4_path, "other.qea")
    first = _run(
        ws, [("open_session", {}), ("edit", {"op": "create_element", "args": {"package": MSG, "name": "Mine"}})]
    )
    assert not any(err for err, _ in first)
    changed = Workspace(Config(other, focus=[CORE], out_dir=tmp_path / "o2"))
    changed.open_session()
    changed.run("create_element", {"package": MSG, "name": "Theirs"})
    changed.commit()
    shutil.copyfile(other, ws.config.model)
    hint = "the model changed on disk: open_session(resume=True) replays your edits onto it, or discard()"
    (_, status), (refused, refusal), (_, resumed), (ok_err, report), (_, found) = _run(
        ws,
        [
            ("session_status", {}),
            ("commit", {}),
            ("open_session", {"resume": True}),
            ("commit", {}),
            ("search", {"text": "Mine"}),
        ],
    )
    assert hint in status
    assert refused and hint in refusal
    assert "resumed 1 of 1" in resumed
    assert not ok_err and "Mine" in report
    assert f"{MSG}::Mine" in found and ws.snapshot().find(f"{MSG}::Theirs")


def test_model_names_that_look_like_tables_stay_as_they_are(qea_copy, nafv4_path, tmp_path):
    ws = _workspace(qea_copy, nafv4_path, tmp_path)
    pkg, el = f"{CORE}::attr_x", f"{CORE}::attr_x::t_object"
    note = "see t_package and attr_name"
    results = _run(
        ws,
        [
            ("open_session", {"focus": CORE, "policy": "off"}),
            ("edit", {"op": "create_package", "args": {"parent": CORE, "name": "attr_x"}}),
            ("edit", {"op": "create_element", "args": {"package": pkg, "name": "t_object", "notes": note}}),
            ("edit", {"op": "add_attribute", "args": {"el": el, "name": "attr_name", "type": "t_user"}}),
            ("edit", {"op": "create_diagram", "args": {"owner": pkg, "name": "t_diagram"}}),
            ("edit", {"op": "place", "args": {"diagram": f"{pkg}::t_diagram", "element": el}}),
            ("commit", {}),
            ("search", {"text": "t_object"}),
            ("describe", {"id": el}),
            ("diagram", {"id": f"{pkg}::t_diagram"}),
            ("describe", {"id": f"{pkg}::t_user"}),
        ],
    )
    assert not any(err for err, _ in results[:7]), results
    (_, found), (_, described), (_, drawn), (missing_err, missing) = results[7:]
    assert el in found
    assert el in described and note in described and "attr_name" in described and "t_user" in described
    assert el in drawn or "t_object" in drawn
    assert missing_err and f"'{pkg}::t_user'" in missing, missing
    ws.open_session(focus=[CORE], policy="off")
    ((edit_err, unknown),) = _run(ws, [("edit", {"op": "update_element", "args": {"el": "t_package", "name": "x"}})])
    assert edit_err and "'t_package'" in unknown, unknown
