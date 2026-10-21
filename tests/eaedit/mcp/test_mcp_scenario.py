"""A change proposal's worth of work, driven through the MCP client the way an agent would."""

import asyncio

import pytest

pytest.importorskip("mcp")

from mcp.client import Client  # noqa: E402

from eacore.backends.sql import file_hash, load_file  # noqa: E402
from eacore.diff import diff  # noqa: E402
from eacore.tablemap import EA_TABLEMAP  # noqa: E402
from eaedit.mcp.server import build_server  # noqa: E402
from eaedit.mcp.workspace import Config, Workspace  # noqa: E402

CORE = "Model::core"
MSG = "Model::core::message"
LOGICAL = f"{MSG}::Scenario"
PHYSICAL = f"{MSG}::ScenarioP"


def _workspace(path, tmp_path, **kw):
    return Workspace(Config(path, out_dir=tmp_path / f"out-{path.stem}", **kw))


def _call(workspace, calls):
    """Run (tool, args) calls in order on one in-memory client; return the reply texts, failing on any error."""

    async def go():
        out = []
        async with Client(build_server(workspace)) as client:
            for name, args in calls:
                result = await client.call_tool(name, args)
                text = "\n".join(c.text for c in result.content)
                assert not result.is_error, f"{name}: {text}"
                out.append(text)
        return out

    return asyncio.run(go())


def _edit(op, **args):
    return "edit", {"op": op, "args": args}


def _same(a, b):
    assert diff(load_file(a), load_file(b)).without_columns(EA_TABLEMAP.volatile).is_empty()


def test_change_proposal_scenario(qea_copy, nafv4_path, tmp_path):
    config = tmp_path / "idl.yaml"
    config.write_text(
        'database_url: "sqlite:///unused.qea"\n'
        'root_packages: ["{753A4DFC-7876-4b00-BB5A-6274AD3817C3}"]\n'
        'template: "idl_just_defs.jinja2"\n'
        'filter_stereotypes: ["lobw"]\n',
        encoding="utf-8",
    )
    agent_path = qea_copy(nafv4_path, "agent.qea")
    ws = _workspace(agent_path, tmp_path, focus=[CORE], idl_configs=[config])
    found_base, found_type, *_ = _call(
        ws,
        [
            ("search", {"text": "/^Message$/", "kind": "element", "package": CORE}),
            ("search", {"text": "Header", "kind": "element", "package": MSG}),
            ("open_session", {"focus": [MSG]}),
            _edit("create_element", package=MSG, name="Scenario", stereotype="idlStruct"),
            _edit("add_stereotype", target=LOGICAL, name="DataElement"),
            _edit("add_attribute", el=LOGICAL, name="size", type="int"),
            _edit("create_element", package=MSG, name="ScenarioP", stereotype="idlStruct"),
            _edit("add_stereotype", target=PHYSICAL, name="DataElement"),
            _edit("add_attribute", el=PHYSICAL, name="size", type="int"),
            _edit("add_attribute", el=PHYSICAL, name="label", type="string"),
            _edit("connect", source=PHYSICAL, target=f"{MSG}::Message", type="Generalization"),
            _edit("connect", source=PHYSICAL, target=LOGICAL, type="Abstraction"),
            _edit("create_diagram", owner=MSG, name="ScenarioView"),
            _edit("place", diagram=f"{MSG}::ScenarioView", element=LOGICAL),
            _edit("place", diagram=f"{MSG}::ScenarioView", element=PHYSICAL),
            _edit("layout", diagram=f"{MSG}::ScenarioView", spec={"pattern": "suggest"}),
        ],
    )
    assert f"{MSG}::Message" in found_base and f"{MSG}::AbstractMessageHeader" in found_type

    before = file_hash(agent_path)
    preview, status, exported = _call(
        ws,
        [("preview", {"diagrams": True, "idl": True}), ("session_status", {}), ("export_changes", {"name": "cp-demo"})],
    )
    assert "Scenario" in preview and "ScenarioP" in preview and "ScenarioView" in preview
    idl_part = preview.split("IDL diff", 1)[1]
    assert any(line.startswith("+") and "ScenarioP" in line for line in idl_part.splitlines()), idl_part
    assert "13 operations" in status
    assert file_hash(agent_path) == before
    package = tmp_path / "out-agent" / "cp-demo"
    assert (package / "changes.yaml").is_file() and (package / "report.md").is_file()
    assert list((package / "diagrams").glob("*.svg"))

    # a reviewer applies the package on a fresh copy and commits; the agent's own commit is the reference
    applied_path = qea_copy(nafv4_path, "applied.qea")
    applied, _ = _call(_workspace(applied_path, tmp_path), [("apply_changes", {"path": str(package)}), ("commit", {})])
    assert "replayed 13 of 13" in applied
    _call(ws, [("commit", {})])
    _same(agent_path, applied_path)
