"""The MCP server: tools over the workspace, explore, diagram, report and package modules. Every reply is text.

Annotations are evaluated (no ``from __future__ import annotations``): the SDK reads them to build tool schemas.
Tools run one at a time (a lock), in the SDK's worker thread, so the event loop keeps answering while one works.
"""

import difflib
import functools
import inspect
import json
import os
import re
import sys
import threading
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

import click
from pydantic import ValidationError
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import CallToolResult, TextContent

from eacore.backends.sql import ConcurrentModificationError, NotAnEaRepositoryError, RepositoryLockedError
from eacore.catalogue import AmbiguousStereotype
from eacore.integrity import check as integrity_check
from eaedit import resolve
from eaedit.defaults import FIELDS
from eaedit.diagrams import svg as svg_io
from eaedit.errors import AmbiguousNameError, CommitRefusedError, EaeditError, NotFoundError
from eaedit.mcp import diagram_text, explore, package
from eaedit.mcp import idl as idl_gen
from eaedit.mcp import workspace as workspace_module
from eaedit.mcp.report import change_report, change_summary
from eaedit.mcp.words import agent_words
from eaedit.mcp.models import Models
from eaedit.mcp.workspace import Config, Workspace
from eaedit.ops import OPERATIONS, load_all
from eaedit.scope import POLICIES

INSTRUCTIONS = (
    "Edits one Enterprise Architect model. Explore first (overview, search, describe, usages, stereotype); things "
    "are named by qualified name (Model::Package::Element, Element.attribute) or GUID. Then open_session with a "
    "focus (the packages you mean to change), call edit once per change (operations lists them), check the result "
    "with preview, and finish with commit (writes the model) or export_changes (writes a change package for review "
    "and leaves the model alone). undo takes back the last edit, discard the whole session."
)

#: Appended to the description of every tool that takes ``model``.
MODEL_DOC = "`model` names an open model (models lists them); without it, the default model."

#: Field names an operation with ``**fields`` accepts, by the table it edits.
_FIELD_TABLES = {
    "create_element": ("t_object",),
    "update_element": ("t_object",),
    "update_package": ("t_package", "t_object"),
    "update_attribute": ("t_attribute",),
    "connect": ("t_connector",),
    "update_connector": ("t_connector",),
    "update_diagram": ("t_diagram",),
}

_EXPECTED = (
    EaeditError,
    AmbiguousStereotype,
    RepositoryLockedError,
    ConcurrentModificationError,
    NotAnEaRepositoryError,
    OSError,
)

STALE = f"note: commit will refuse, {workspace_module.STALE}"
#: Lines per page of a paged reply.
PAGE_SIZE = 40
#: Lines per page of generated IDL.
IDL_PAGE_SIZE = 200


class _Reply(Exception):
    """A finished error text (already starting with ``error:``)."""


def _line(exc: BaseException) -> str:
    text = str(exc).splitlines()[0] if str(exc) else type(exc).__name__
    return text + "".join(f" ({note})" for note in getattr(exc, "__notes__", []))


def error_text(exc: BaseException) -> str:
    """What the agent reads for a failed tool call: one ``error:`` line (more for refused commits), no trace."""
    if isinstance(exc, _Reply):
        return str(exc)
    if isinstance(exc, CommitRefusedError):
        issues = [f"  {i.severity} {i.rule}: {i.message}" for i in exc.issues]
        return "\n".join([f"error: {_line(exc)}; fix these, then commit again:", *issues])
    if isinstance(exc, NotFoundError):
        return f"error: {_line(exc)}; search finds names and GUIDs"
    if isinstance(exc, NotAnEaRepositoryError):
        return f"error: {_line(exc)}: not an Enterprise Architect repository"
    if isinstance(exc, _EXPECTED):
        return f"error: {_line(exc)}"
    return f"error: {type(exc).__name__}: {_line(exc)}"


def _text(text: str, is_error: bool = False) -> CallToolResult:
    return CallToolResult(content=[TextContent(type="text", text=text)], is_error=is_error)


class _Server(MCPServer):
    """MCPServer whose own refusals (unknown tool, arguments that fail the schema) read like the tools' errors."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.tool_functions: dict[str, Callable[..., str]] = {}

    async def call_tool(self, name: str, arguments: dict[str, Any], context: Any = None) -> Any:
        fn = self.tool_functions.get(name)
        if fn is None:
            near = difflib.get_close_matches(name, self.tool_functions, n=3, cutoff=0.5)
            return _text(f"error: unknown tool {name!r}" + (f"; did you mean {', '.join(near)}?" if near else ""), True)
        try:
            return await super().call_tool(name, arguments, context)
        except ToolError as exc:
            if not isinstance(exc.__cause__, ValidationError):
                raise
            return _text(_argument_error(fn, exc.__cause__), is_error=True)


def _argument_error(fn: Callable[..., str], exc: ValidationError) -> str:
    """``error: <tool>: <param> is required|must be <type>; parameters: <tool>(<params>)``."""
    params = inspect.signature(fn).parameters
    problems: dict[str, str] = {}
    for err in exc.errors():
        param = str(err["loc"][0]) if err["loc"] else ""
        if param in problems:
            continue
        if err["type"] == "missing":
            problems[param] = f"{param} is required"
        elif param in params:
            problems[param] = f"{param} must be {inspect.formatannotation(params[param].annotation)}"
        else:
            problems[param] = f"{param}: {err['msg']}"
    shown = ", ".join(
        p.name if p.default is inspect.Parameter.empty else f"{p.name}={p.default!r}" for p in params.values()
    )
    return f"error: {fn.__name__}: {'; '.join(problems.values())}; parameters: {fn.__name__}({shown})"


def _register(server: _Server, lock: threading.Lock, words: Callable[[str, str | None], str]) -> Callable:
    """Register ``fn`` (returning text) as a tool whose failures come back as ``error:`` text in agent words.
    Replies are model data and stay as the tool wrote them; tools put their warnings in agent words themselves."""

    def register(fn: Callable[..., str]) -> Callable[..., str]:
        @functools.wraps(fn)
        def tool(*args, **kwargs) -> CallToolResult:
            with lock:
                try:
                    return _text(fn(*args, **kwargs))
                except Exception as exc:
                    # A _Reply is finished text (it may list model names); eaedit and eacore messages get agent words.
                    text = error_text(exc)
                    model = kwargs.get("model")
                    return _text(text if isinstance(exc, _Reply) else words(text, model), is_error=True)

        # The SDK would validate a ``str`` return as structured output; a CallToolResult is passed through.
        tool.__signature__ = inspect.signature(fn).replace(return_annotation=CallToolResult)
        tool.__annotations__ = {**fn.__annotations__, "return": CallToolResult}
        description = inspect.cleandoc(fn.__doc__ or "")
        if "model" in inspect.signature(fn).parameters:
            description += "\n" + MODEL_DOC
        server.add_tool(tool, name=fn.__name__, description=description)
        server.tool_functions[fn.__name__] = fn
        return fn

    return register


# --- helpers --------------------------------------------------------------------------------------------------


def _signature(name: str, annotated: bool = False) -> str:
    """``name(param, param=default, **fields)`` without the session parameter."""
    parts = []
    for p in list(inspect.signature(OPERATIONS[name]).parameters.values())[1:]:
        # The ops modules postpone annotations, so each is its source text.
        text = f"**{p.name}" if p.kind is inspect.Parameter.VAR_KEYWORD else p.name
        if annotated and p.annotation is not inspect.Parameter.empty:
            text += f": {p.annotation}"
        if p.default is not inspect.Parameter.empty:
            text += f" = {p.default!r}" if annotated else f"={p.default!r}"
        parts.append(text)
    return name + "(" + ", ".join(parts) + ")"


def _fields(name: str) -> str | None:
    tables = _FIELD_TABLES.get(name)
    if not tables:
        return None
    return "fields: " + ", ".join(sorted({f for t in tables for f in FIELDS.get(t, {})}))


def _unknown_op(name: str) -> _Reply:
    near = difflib.get_close_matches(name, OPERATIONS, n=3, cutoff=0.5)
    hint = f"did you mean {', '.join(near)}?" if near else "operations lists them"
    return _Reply(f"error: unknown operation {name!r}; {hint}")


def _issue_line(rs, issue, words: Callable[[str], str]) -> str:
    where = ""
    if issue.ref is not None:
        try:
            where = f" [{resolve.qualified_name(rs, issue.ref)}]"
        except Exception:  # some rows (diagram objects, links) have no qualified name
            where = ""
    return f"{issue.severity} {issue.rule}: {words(issue.message)}{where}"


def _idl_texts(workspace: Workspace, session) -> list[str]:
    configs = workspace.config.idl_configs
    if not configs:
        return ["IDL diff: no eaidl config (start the server with --idl-config)"]
    return [f"IDL diff ({path.name}):\n{idl_gen.idl_diff(session, path).text()}" for path in configs]


_NO_IDL_CONFIG = "error: no eaidl config: pass config=PATH or start the server with --idl-config"


def _idl_configs(workspace: Workspace, config: str | None, overrides: dict[str, Any] | str | None) -> list:
    """(file name, eaidl Configuration) per config: ``config`` (relative to the model's folder) or the server's own,
    each with ``overrides`` set over it."""
    if isinstance(overrides, str):
        try:
            overrides = json.loads(overrides) if overrides.strip() else None
        except json.JSONDecodeError as exc:
            raise _Reply(f"error: overrides is not a JSON object ({exc})") from None
    if overrides is not None and not isinstance(overrides, dict):
        raise _Reply("error: overrides must be a JSON object of eaidl options")
    if config:
        path = Path(config)
        paths = [path if path.is_absolute() else Path(workspace.config.model).parent / path]
    else:
        paths = list(workspace.config.idl_configs)
    if not paths:
        raise _Reply(_NO_IDL_CONFIG)
    loaded = []
    for path in paths:
        if not path.is_file():
            raise _Reply(f"error: no eaidl config file {path}")
        try:
            loaded.append((path.name, idl_gen.load(path, overrides)))
        except ValueError as exc:
            raise _Reply(f"error: {path.name}: {exc}") from None
    return loaded


_MORE = re.compile(r"^… (\d+) more \(page=(\d+)\)$")


def _diagram_part(session, guid: str) -> str:
    """A changed diagram's first page; its own ``… N more`` line names the diagram tool, as the preview is paged."""
    lines = diagram_text.diagram_text(session, guid).split("\n")
    more = _MORE.match(lines[-1])
    if more:
        lines[-1] = f"… {more.group(1)} more (diagram(id={guid}, page={more.group(2)}))"
    return "\n".join(lines)


def _paged(text: str, page: int, stale: bool) -> str:
    """One page of a report (lines are model data: never clipped), the stale note after it."""
    paged = explore.page_lines(text.split("\n"), page, PAGE_SIZE, clip=False)
    return paged + "\n\n" + STALE if stale else paged


def focus_lines(preview) -> list[str]:
    """What the preview touches outside the focus: allowed by the policy, or accepted only by advisory/off."""
    allowed = [name for name in preview.outside_focus if name not in preview.refused_outside]
    lines = []
    if allowed:
        lines.append(f"outside the focus, allowed under {preview.judged_by}: " + ", ".join(allowed))
    if preview.refused_outside:
        lines.append(
            f"outside the focus, would be refused under {preview.judged_by}: " + ", ".join(preview.refused_outside)
        )
    return lines


def _preview_text(workspace: Workspace, diagrams: bool = False, idl: bool = False, page: int = 1) -> str:
    session = workspace.require_session()
    parts = [change_report(session, title="Preview").rstrip("\n")]
    parts += focus_lines(session.preview(render=False))
    if diagrams:
        changed = session.changed_diagrams()
        parts += [_diagram_part(session, guid) for guid in changed] or ["no diagrams changed"]
    if idl:
        parts += _idl_texts(workspace, session)
    return _paged("\n\n".join(parts), page, workspace.stale())


# --- the server -----------------------------------------------------------------------------------------------


def build_server(models: Models | Workspace) -> MCPServer:
    load_all()
    server = _Server("eaedit", instructions=INSTRUCTIONS)
    if isinstance(models, Workspace):
        models = Models.of(models)

    def ws(model: str | None) -> Workspace:
        return models.get(model)

    def view(model: str | None):
        """The open session's working copy (staged changes visible), else the model file as it is."""
        workspace = ws(model)
        return workspace.session or workspace.snapshot()

    def words(text: str, model: str | None = None) -> str:
        if "t_" not in text and "attr_" not in text:
            return text
        try:
            session = view(model)
        except Exception:  # no such model, or it cannot be read: the message stays as it is
            return text
        return agent_words(text, session.working, session.original)

    tool = _register(server, threading.Lock(), words)
    #: The last commit's report per model, so commit(page=K) can page it after the session is gone.
    committed: dict[Path, str] = {}

    # --- explore ---

    @tool
    def overview(package: str | None = None, depth: int = 2, page: int = 1, model: str | None = None) -> str:
        """The package tree, `depth` levels deep, with element counts per package and kind. `package` (qualified
        name or GUID) starts the tree there instead of at the model root. Like every explore tool it reads the
        open session's working copy (so staged edits show) or, with no session, the model file as it is now.
        Long replies end with a `… N more (page=K)` line: call again with that page. Example:
        overview(package="Model::Logical", depth=3)"""
        return explore.overview(view(model), package, depth, page)

    @tool
    def search(
        text: str = "",
        kind: str | None = None,
        stereotype: str | None = None,
        package: str | None = None,
        field: str = "name",
        page: int = 1,
        model: str | None = None,
    ) -> str:
        """Find packages, elements, attributes, connectors and diagrams: `text` is a case-insensitive substring, or
        a regular expression written as `/regex/` ("" matches everything). `field` says where to look: "name"
        (default), "notes", "tags" (tag names and values) or "any". `kind` is one of package, element, attribute,
        connector, diagram; `stereotype` keeps only things with that stereotype; `package` keeps only things inside
        that package's subtree. One line per match: kind, qualified name, stereotypes, type, GUID, and for a match
        outside the name what matched (`notes: "…"` or `tag name = value`). Paged (`page`).
        Example: search(text="timestamp", field="notes", kind="element", package="Model::Logical")"""
        return explore.search(view(model), text, kind, stereotype, package, field, page)

    @tool
    def describe(id: str, page: int = 1, model: str | None = None) -> str:
        """One thing in compact detail, by qualified name or GUID (`id`): an element's stereotypes, tags,
        attributes with types, connectors and the diagrams showing it; a package's direct contents; a connector's
        ends; a diagram's objects (as the diagram tool). A name shared by several things lists them with their
        GUIDs: describe the one you mean by GUID. Paged (`page`). Example: describe(id="Model::Logical::Header")"""
        return explore.describe(view(model), id, page)

    @tool
    def usages(id: str, page: int = 1, model: str | None = None) -> str:
        """Where an element (qualified name or GUID) is used: attributes typed by it, connectors to and from it,
        diagrams showing it. Good for finding base classes and existing types before creating new ones. Paged
        (`page`). Example: usages(id="Model::Logical::Header")"""
        return explore.usages(view(model), id, page)

    @tool
    def stereotype(name: str, model: str | None = None) -> str:
        """A stereotype's definition from the loaded catalogues (or the model): what it applies to, its tags with
        types, values and defaults, what it generalizes, connector end rules. `name` may be qualified with its
        profile (`Profile::Name`) when two profiles define it. Example: stereotype(name="Block")"""
        return explore.stereotype_info(view(model), name)

    # --- session ---

    @tool
    def open_session(
        focus: list[str] | str | None = None, policy: str | None = None, resume: bool = False, model: str | None = None
    ) -> str:
        """Start editing. `focus` is the package (or list of packages) the changes belong in, by qualified name or
        GUID; the server's default focus when omitted. `policy` says how changes outside the focus are treated:
        "package" (refused outside the focus), "connected" (also allows connectors and diagram changes reaching
        out of it), "advisory" (allowed, with a warning) or "off". Every edit is saved to a working file at once;
        after a restart, `resume=true` replays it, and when the model changed on disk under an open session,
        `resume=true` replays its edits onto the new model; a resumed session keeps its saved focus and policy unless
        new ones are given. Example: open_session(focus=["Model::Logical"])"""
        workspace = ws(model)
        result = workspace.open_session([focus] if isinstance(focus, str) else focus, policy, resume)
        session = workspace.require_session()
        names = [resolve.qualified_name(session.working, ref) for ref in session.scope.focus]
        return f"{result.message}; focus: {', '.join(names) or '(none)'}; policy: {session.scope.policy}"

    @tool
    def session_status(model: str | None = None) -> str:
        """Whether a session is open, and if so its focus, policy, the operations so far and the warnings they
        raised; also whether the model file changed underneath it. Example: session_status()"""
        workspace = ws(model)
        session = workspace.session
        if session is None:
            saved = workspace.working_file
            if saved.is_file():
                try:
                    count = len(workspace.saved_ops())
                except EaeditError as exc:
                    return f"no session open; {words(_line(exc), model)}"
                if count:
                    return f"no session open; a saved one with {count} operations exists: open_session(resume=true) or discard()"
            return "no session open"
        names = [resolve.qualified_name(session.working, ref) for ref in session.scope.focus]
        lines = [f"session open; focus: {', '.join(names) or '(none)'}; policy: {session.scope.policy}"]
        ops = [op.name for op in session.log]
        lines.append(f"{len(ops)} operations" + (": " + ", ".join(ops) if ops else ""))
        lines += [f"warning {words(str(w), model)}" for w in session.warnings]
        if workspace.stale():
            lines.append(STALE)
        return "\n".join(lines)

    @tool
    def operations(name: str | None = None) -> str:
        """Without `name`, every edit operation on one line with its parameters; with `name`, that operation's
        full signature, the fields it takes (for `**fields`) and its description. Pass the parameters to edit as
        a JSON object. Example: operations(name="add_attribute")"""
        if name is None:
            return "\n".join(_signature(op) for op in sorted(OPERATIONS))
        if name not in OPERATIONS:
            raise _unknown_op(name)
        lines = [_signature(name, annotated=True)]
        fields = _fields(name)
        if fields:
            lines.append(fields)
        doc = inspect.getdoc(OPERATIONS[name])
        if doc:
            lines.append(doc)
        return "\n".join(lines)

    @tool
    def edit(op: str, args: dict[str, Any] | str, model: str | None = None) -> str:
        """Run one edit operation (`op`, see operations) on the open session with `args` as a JSON object of its
        parameters. Things are named by qualified name or GUID. Replies `ok <GUID>` of what it created or changed,
        then any warnings; a failed edit changes nothing and replies `error: ...`. Example:
        edit(op="add_attribute", args={"el": "Model::Logical::Header", "name": "size", "type": "long"})"""
        workspace = ws(model)
        if op not in OPERATIONS:
            raise _unknown_op(op)
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError as exc:
                raise _Reply(f"error: args is not a JSON object ({exc})") from None
        if not isinstance(args, dict):
            raise _Reply("error: args must be a JSON object of the operation's parameters")
        session = workspace.require_session()
        try:
            result = workspace.run(op, args)
        except AmbiguousNameError as exc:
            listing = explore.describe(session, exc.name).splitlines()
            candidates = listing[1:] if listing and listing[0].startswith("ambiguous:") else []
            raise _Reply("\n".join([f"error: {exc.name!r} is ambiguous; name one by GUID:", *candidates])) from None
        except (TypeError, ValueError, KeyError) as exc:
            if isinstance(exc, EaeditError):
                raise
            raise _Reply(f"error: {op}: {words(_line(exc), model)}; parameters: {_signature(op)}") from None
        lines = [f"ok {result.guid}" if result.guid else "ok"]
        lines += [f"warning {words(str(w), model)}" for w in result.warnings]
        if workspace.stale():
            lines.append(STALE)
        return "\n".join(lines)

    @tool
    def undo(model: str | None = None) -> str:
        """Take back the last edit of the open session. Example: undo()"""
        workspace = ws(model)
        text = f"undid {workspace.undo()}"
        return text + "\n" + STALE if workspace.stale() else text

    @tool
    def discard(model: str | None = None) -> str:
        """Drop the open session and all its edits (also a saved session left by a restart); the model file is not
        touched. Example: discard()"""
        workspace = ws(model)
        had = workspace.session is not None or workspace.working_file.is_file()
        workspace.discard()
        return "session discarded" if had else "no session to discard"

    @tool
    def preview(diagrams: bool = False, idl: bool = False, page: int = 1, model: str | None = None) -> str:
        """What the open session would change, per package (added, changed, removed), with warnings and new
        integrity issues. `diagrams=true` adds the text form of each changed diagram (its first page; the
        `… N more` line names the diagram call for the rest); `idl=true` adds the IDL diff (when the server has an
        eaidl config). Paged (`page`). Example: preview(diagrams=true)"""
        workspace = ws(model)
        return _preview_text(workspace, diagrams, idl, page)

    @tool
    def commit(page: int = 1, model: str | None = None) -> str:
        """Write the open session's edits to the model file and close the session. Refused (with the reasons) when
        it would add integrity errors, leave the focus, or when the file changed since the session opened. Replies
        with the change report, which is also saved in the output directory. The report is paged: `page` above 1
        shows that page of the last commit's report and commits nothing. Example: commit()"""
        workspace = ws(model)
        if page > 1:
            if workspace.config.model not in committed:
                raise _Reply("error: no commit report yet; commit() first")
            return _paged(committed[workspace.config.model], page, False)
        report = package.commit_with_report(workspace)
        committed[workspace.config.model] = report.rstrip("\n")
        return _paged(committed[workspace.config.model], 1, False)

    @tool
    def export_changes(name: str, overwrite: bool = False, model: str | None = None) -> str:
        """Write the open session's edits as a change package (change file, report, changed diagrams, IDL diff,
        check results) to the directory `name` under the output directory, without touching the model; the session
        stays open. `overwrite=true` replaces an existing package of that name. Replies with the directory and one
        line per changed package (preview shows the details). Example: export_changes(name="add-header-size")"""
        workspace = ws(model)
        target = package.export_changes(workspace, name, overwrite)
        return "\n".join([f"wrote {target}", *change_summary(workspace.require_session())])

    @tool
    def apply_changes(path: str, model: str | None = None) -> str:
        """Replay a change package (its directory, or a change file) onto the model in a new session and preview
        it; then commit or discard. A relative `path` is under the output directory, as export_changes names it.
        All or nothing: if one operation fails, no session is left open. Example: apply_changes(path="add-header-size")"""
        workspace = ws(model)
        source = Path(path)
        if not source.is_absolute():
            source = workspace.config.out_dir / source
        result = package.apply_changes(workspace, source)
        return f"{result.message}\n\n{_preview_text(workspace)}"

    # --- diagrams ---

    @tool
    def diagram(id: str, page: int = 1, model: str | None = None) -> str:
        """A diagram (qualified name or GUID) as compact text, staged edits included: one line per object (name,
        GUID, kind, rectangle left,top,right,bottom, stacking), per shown connector and per note. Change it with
        edit operations (place, set_bounds, layout, ...). Paged (`page`). Example: diagram(id="Model::Logical::Overview")"""
        return diagram_text.diagram_text(view(model), id, page)

    @tool
    def diagram_svg(id: str, model: str | None = None) -> str:
        """A diagram (qualified name or GUID) as eaedit SVG: the full drawing, several thousand tokens even for a
        medium diagram. Edit it and hand it back with import_svg, or prefer the diagram tool to read.
        Example: diagram_svg(id="Model::Logical::Overview")"""
        return svg_io.export_svg(view(model), id)

    @tool
    def import_svg(svg: str, owner: str | None = None, model: str | None = None) -> str:
        """Stage the differences between an eaedit SVG (`svg`, as diagram_svg returns it, edited) and its
        diagram in the open session. An SVG without a diagram GUID creates a new diagram in `owner` (a package or
        element). A file that breaks the rules is refused before anything is staged. Example:
        import_svg(svg="<svg ...>...</svg>")"""
        workspace = ws(model)
        session = workspace.require_session()
        start = len(session.log)
        results = svg_io.import_svg(session, svg, owner)
        workspace.save()
        lines = [f"ok: {len(session.log) - start} operations"]
        lines += [f"ok {r.guid}" for r in results if r.guid]
        lines += [f"warning {words(str(w), model)}" for r in results for w in r.warnings]
        if workspace.stale():
            lines.append(STALE)
        return "\n".join(lines)

    # --- checks ---

    @tool
    def check(page: int = 1, model: str | None = None) -> str:
        """Integrity check: in a session, the issues its edits would add; without one, the model's errors. Paged
        (`page`). Example: check()"""
        workspace = ws(model)
        session = workspace.session
        if session is not None:
            issues = session.preview(render=False).new_issues
            empty = "no new integrity issues"
        else:
            session = workspace.snapshot()
            issues = [i for i in integrity_check(session.working) if i.severity == "error"]
            empty = "no integrity errors in the model"
        if not issues:
            return empty
        return explore.page_lines(
            [_issue_line(session.working, i, lambda text: words(text, model)) for i in issues], page, PAGE_SIZE
        )

    @tool
    def idl_diff(
        config: str | None = None, overrides: dict[str, Any] | str | None = None, model: str | None = None
    ) -> str:
        """The IDL the open session's edits would change, as a unified diff per eaidl config; it also names changed
        packages outside the IDL roots, so an empty diff is not mistaken for no effect. `config` is an eaidl config
        file (relative to the model's folder); without it, the configs the server was started with. `overrides` is a
        JSON object of eaidl options set over the config for this call only.
        Example: idl_diff(config="idl.yaml", overrides={"root_packages": ["Messages"]})"""
        workspace = ws(model)
        session = workspace.require_session()
        return "\n\n".join(
            f"IDL diff ({name}):\n{idl_gen.idl_diff(session, loaded).text()}"
            for name, loaded in _idl_configs(workspace, config, overrides)
        )

    @tool
    def idl(
        config: str | None = None,
        overrides: dict[str, Any] | str | None = None,
        page: int = 1,
        model: str | None = None,
    ) -> str:
        """The IDL eaidl generates, from the open session's working copy (staged edits included) or, with no session,
        from the model. `config` and `overrides` as for idl_diff. Paged (`page`).
        Example: idl(config="idl.yaml", overrides={"template": "idl.jinja2"})"""
        workspace = ws(model)
        session = workspace.session or workspace.snapshot()
        parts = []
        for name, loaded in _idl_configs(workspace, config, overrides):
            try:
                text = idl_gen.idl_text(session, loaded)
            except Exception as exc:  # eaidl raises whatever it likes on a model it cannot generate from
                raise _Reply(f"error: {name}: eaidl failed: {type(exc).__name__}: {idl_gen.error_text(exc)}") from None
            parts.append(f"IDL ({name}):\n{text.rstrip(chr(10))}")
        paged = explore.page_lines("\n\n".join(parts).split("\n"), page, IDL_PAGE_SIZE, clip=False)
        return paged + "\n\n" + STALE if workspace.session is not None and workspace.stale() else paged

    return server


# --- command line ---------------------------------------------------------------------------------------------

ENV = "EAEDIT_MCP_"
#: Option -> (environment variable suffix, separator for a list, or None for a single value).
_ENV = {
    "model": ("MODEL", None),
    "catalogues": ("CATALOGUES", os.pathsep),
    "idl_configs": ("IDL_CONFIGS", os.pathsep),
    "author": ("AUTHOR", None),
    "timezone": ("TIMEZONE", None),
    "focus": ("FOCUS", ";"),
    "policy": ("POLICY", None),
    "out_dir": ("OUT", None),
}


def _env(name: str) -> str:
    return f"(env {ENV}{_ENV[name][0]})"


@click.command(
    "eaedit-mcp",
    help=f"Serve MODEL (an EA .qea file, or {ENV}MODEL) to an agent as an MCP server over stdio. List options "
    f"repeat on the command line; in the environment paths are separated by {os.pathsep!r} and packages by ';'.",
)
@click.argument("model", required=False)
@click.option(
    "-c", "--catalogue", "catalogues", multiple=True, help=f"MDG XML, YAML or .qea catalogue {_env('catalogues')}."
)
@click.option(
    "--idl-config", "idl_configs", multiple=True, help=f"eaidl config, enables IDL diffs {_env('idl_configs')}."
)
@click.option("--author", help=f"Author of new items {_env('author')}.")
@click.option("--timezone", help=f"IANA timezone for timestamps {_env('timezone')}.")
@click.option("--focus", multiple=True, help=f"Default session focus package {_env('focus')}.")
@click.option("--policy", help=f"Default focus policy: {', '.join(POLICIES)} {_env('policy')}.")
@click.option("--out", "out_dir", help=f"Output directory [default: <model dir>/eaedit-out] {_env('out_dir')}.")
def _command(**values: Any) -> dict:
    return values


def parse_config(argv: Sequence[str], env: Mapping[str, str]) -> Config:
    """The configuration from the command line, falling back to ``EAEDIT_MCP_*`` in ``env`` for options not given."""
    ctx = _command.make_context("eaedit-mcp", list(argv))
    values = dict(ctx.params)
    for name, (suffix, separator) in _ENV.items():
        given = values.get(name)
        if given not in (None, ()) or ENV + suffix not in env:
            continue
        raw = env[ENV + suffix]
        values[name] = [part for part in raw.split(separator) if part] if separator else raw
    if not values["model"]:
        raise click.UsageError(f"give MODEL (or set {ENV}MODEL)", ctx)
    model = Path(values["model"])
    if not model.is_file():
        raise click.BadParameter(f"{model} is not a file", ctx, param_hint="MODEL")
    policy = values["policy"] or "connected"
    if policy not in POLICIES:
        raise click.BadParameter(f"{policy!r} is not one of {', '.join(POLICIES)}", ctx, param_hint="--policy")
    return Config(
        model,
        catalogues=[Path(p) for p in values["catalogues"]],
        idl_configs=[Path(p) for p in values["idl_configs"]],
        author=values["author"],
        timezone=values["timezone"],
        focus=list(values["focus"]),
        policy=policy,
        out_dir=Path(values["out_dir"]) if values["out_dir"] else None,
    )


def main(argv: Sequence[str] | None = None) -> None:
    """``eaedit-mcp``: parse the options and serve the model over stdio until the client disconnects."""
    try:
        config = parse_config(sys.argv[1:] if argv is None else argv, os.environ)
    except click.exceptions.Exit as exc:  # --help
        sys.exit(exc.exit_code)
    except click.ClickException as exc:
        exc.show()
        sys.exit(exc.exit_code)
    build_server(Workspace(config)).run("stdio")
