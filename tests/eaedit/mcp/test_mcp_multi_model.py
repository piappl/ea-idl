import asyncio

import pytest

pytest.importorskip("mcp")

from mcp.client import Client  # noqa: E402

from eaedit.mcp.models import Models  # noqa: E402
from eaedit.mcp.server import build_server  # noqa: E402
from eaedit.mcp.workspace import Config, Workspace  # noqa: E402

MSG = "Model::core::message"


@pytest.fixture
def models(qea_copy, nafv4_path, tmp_path):
    return Models.of(Workspace(Config(qea_copy(nafv4_path), out_dir=tmp_path / "out")))


def _run(models, calls):
    """Call the tools in order on one server; return (is_error, text) per call."""

    async def go():
        out = []
        async with Client(build_server(models)) as client:
            for name, args in calls:
                result = await client.call_tool(name, args)
                out.append((result.is_error, "\n".join(c.text for c in result.content)))
        return out

    return asyncio.run(go())


def test_open_read_both_and_list(models, qea_copy, nafv4_path):
    other = qea_copy(nafv4_path, "other.qea")
    (e1, opened), (e2, ov_other), (e3, ov), (e4, listing) = _run(
        models,
        [("open_model", {"path": str(other), "read_only": True}), ("overview", {"model": "other"})]
        + [("overview", {}), ("models", {})],
    )
    assert not (e1 or e2 or e3 or e4)
    assert opened == f"opened other: {other}; read-only; catalogues: none"
    assert "core" in ov_other and "core" in ov
    lines = listing.splitlines()
    assert lines[0].startswith("copy (default): ") and lines[1].startswith("other read-only: ")
    assert lines[1].endswith("session: none")


def test_two_models_are_isolated(models, qea_copy, nafv4_path, tmp_path):
    other = qea_copy(nafv4_path, "other.qea")
    results = _run(
        models,
        [
            ("open_model", {"path": str(other)}),
            ("open_session", {"model": "other"}),
            ("edit", {"op": "create_element", "args": {"package": MSG, "name": "OnlyInB"}, "model": "other"}),
            ("search", {"text": "OnlyInB", "model": "other"}),
            ("search", {"text": "OnlyInB"}),
            ("session_status", {}),
            ("models", {}),
        ],
    )
    assert not any(err for err, _ in results), results
    assert "OnlyInB" in results[3][1] and "OnlyInB" not in results[4][1]
    assert results[5][1] == "no session open"
    assert "session: open, 1 operations" in results[6][1].splitlines()[1]
    assert (tmp_path / "eaedit-out-other" / "working.yaml").is_file()
    assert not (tmp_path / "out" / "working.yaml").exists()


def test_read_only_refusals_through_tools(models, qea_copy, nafv4_path):
    other = qea_copy(nafv4_path, "other.qea")
    refused = [
        ("open_session", {}),
        ("edit", {"op": "create_element", "args": {"package": MSG, "name": "X"}}),
        ("undo", {}),
        ("discard", {}),
        ("commit", {}),
        ("export_changes", {"name": "x"}),
        ("apply_changes", {"path": "x"}),
        ("import_svg", {"svg": "<svg/>"}),
    ]
    calls = [("open_model", {"path": str(other), "read_only": True})]
    calls += [(name, {**args, "model": "other"}) for name, args in refused]
    calls += [("check", {"model": "other"}), ("idl", {"model": "other"})]
    results = _run(models, calls)
    for (name, _), (err, text) in zip(refused, results[1:-2]):
        assert err and "read-only" in text, (name, text)
    (check_err, _), (_, idl) = results[-2:]
    assert not check_err and "read-only" not in idl


def test_closing_default_requires_model(models, qea_copy, nafv4_path):
    other = qea_copy(nafv4_path, "other.qea")
    results = _run(
        models,
        [("open_model", {"path": str(other)}), ("close_model", {"name": "copy"})]
        + [("overview", {}), ("overview", {"model": "other"}), ("models", {})],
    )
    assert results[1][1] == "closed copy; no default model now"
    assert results[2][0] and results[2][1].startswith("error: no default model; pass model= one of: other")
    assert not results[3][0]
    assert results[4][1].startswith("other: ")


def test_close_with_staged_edits_then_resume(models, qea_copy, nafv4_path, tmp_path):
    other = qea_copy(nafv4_path, "other.qea")
    results = _run(
        models,
        [
            ("open_model", {"path": str(other)}),
            ("open_session", {"model": "other"}),
            ("edit", {"op": "create_element", "args": {"package": MSG, "name": "Kept"}, "model": "other"}),
            ("close_model", {"name": "other"}),
            ("open_model", {"path": str(other)}),
            ("open_session", {"model": "other", "resume": True}),
        ],
    )
    working = tmp_path / "eaedit-out-other" / "working.yaml"
    assert results[3][1] == (
        f"closed other; 1 staged operations kept in {working}: open_model again, then open_session(resume=true)"
    )
    assert results[4][1].splitlines()[1] == (
        'a saved session with 1 operations exists: open_session(model="other", resume=true) or discard(model="other")'
    )
    assert results[5][1].startswith("resumed 1 of 1")


def test_open_model_failure_is_an_error(models, tmp_path):
    bad = tmp_path / "bad.qea"
    bad.write_text("not a database")
    (err, text), (_, listing) = _run(models, [("open_model", {"path": str(bad)}), ("models", {})])
    assert err and text.startswith("error:")
    assert len(listing.splitlines()) == 1


def test_idl_config_resolves_against_chosen_model(models, nafv4_path, tmp_path):
    import shutil

    folder = tmp_path / "b"
    folder.mkdir()
    shutil.copyfile(nafv4_path, folder / "other.qea")
    (folder / "idl.yaml").write_text(
        'root_packages: ["{753A4DFC-7876-4b00-BB5A-6274AD3817C3}"]\ntemplate: "idl_just_defs.jinja2"\n',
        encoding="utf-8",
    )
    results = _run(
        models,
        [
            ("open_model", {"path": "b/other.qea", "idl_configs": "idl.yaml"}),
            ("idl", {"config": "idl.yaml", "model": "other"}),
            ("idl", {"model": "other"}),
            ("idl", {"config": "idl.yaml"}),
        ],
    )
    assert not results[1][0] and results[1][1].startswith("IDL (idl.yaml):")
    assert not results[2][0] and results[2][1].startswith("IDL (idl.yaml):")
    assert results[3][0] and "no eaidl config file" in results[3][1]


def test_open_model_with_unreadable_working_file_still_opens(models, qea_copy, nafv4_path, tmp_path):
    other = qea_copy(nafv4_path, "other.qea")
    (tmp_path / "eaedit-out-other").mkdir()
    (tmp_path / "eaedit-out-other" / "working.yaml").write_text("ops: [unclosed", encoding="utf-8")
    (err, text), (_, listing) = _run(models, [("open_model", {"path": str(other)}), ("models", {})])
    assert not err and text.splitlines()[0].startswith("opened other: ")
    assert "unreadable" in text and 'discard(model="other")' in text
    assert "other" in listing
