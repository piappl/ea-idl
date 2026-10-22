# eaedit-mcp

An [MCP](https://modelcontextprotocol.io) server that lets an agent explore and edit one Enterprise Architect `.qea`
model through [eaedit](./EAEDIT.md). It is generic: it knows no modelling conventions and no workflow. Those belong in
the agent's own instructions (see [docs/examples/AGENTS.example.md](./docs/examples/AGENTS.example.md)).

The server speaks stdio. It can have several model files open at once (see Models below), each with its own
catalogues, eaidl configs and at most one editing session. The agent sees
qualified names (`Model::Package::Element`, `Element.attribute`) and GUIDs only. Lists are paged: a reply ends with
`… N more (page=K)`, and the agent calls again with that page.

## Install

```bash
uv sync --extra mcp          # in a checkout
pip install "eaidl[mcp]"     # from a package index
```

The MCP SDK is an optional extra, so eaidl and eaedit work without it.

## Run

```bash
eaedit-mcp MODEL.qea [options]      # also: eaedit mcp ...   or   python -m eaedit.mcp ...
```

`python -m eaedit.mcp` needs only the interpreter, so it also works where console-script launchers do not (for
example a virtual environment copied into a container).

An agent host starts this as a subprocess and talks to it over stdio. For opencode running in the same container as
the model, see [docs/examples/opencode.json](./docs/examples/opencode.json): an entry under `mcp` with
`"type": "local"` and the command as a list (opencode also accepts `environment` for the `EAEDIT_MCP_*` variables,
`cwd`, and `timeout` in milliseconds for listing tools, default 5000; the server lists its tools in about a second).
opencode shows the tools with the server name as a prefix (`eaedit_search`, `eaedit_open_session`, ...), and its
`tools` / `agent.<name>.tools` settings can enable them for one agent only. The file follows opencode's
configuration format, not ours; check [opencode's MCP documentation](https://opencode.ai/docs/mcp-servers/) if it
changes. Paths in it are placeholders.

| Option | Environment variable | Meaning |
|--------|----------------------|---------|
| `MODEL` | `EAEDIT_MCP_MODEL` | The `.qea` file, the default model. Optional: without it the server starts with no model and the agent opens them with `open_model`. |
| `-c`, `--catalogue` (repeatable) | `EAEDIT_MCP_CATALOGUES` | MDG XML, YAML or `.qea` stereotype catalogue. |
| `--idl-config` (repeatable) | `EAEDIT_MCP_IDL_CONFIGS` | An eaidl config: the default for `idl` and `idl_diff`, and the configs `preview(idl=true)`, commit reports and change packages use. Optional. |
| `--author` | `EAEDIT_MCP_AUTHOR` | Author written on new items. |
| `--timezone` | `EAEDIT_MCP_TIMEZONE` | IANA timezone for timestamps. |
| `--focus` (repeatable) | `EAEDIT_MCP_FOCUS` | Default focus of a session. |
| `--policy` | `EAEDIT_MCP_POLICY` | Default focus policy, how changes outside the focus are treated: `package` (refused outside the focus), `connected` (default; also allows connectors and diagram changes reaching out of it), `advisory` (allowed, with a warning) or `off`. |
| `--out` | `EAEDIT_MCP_OUT` | Output directory, default `eaedit-out` next to the model. |
| `--read-only` | `EAEDIT_MCP_READ_ONLY` | Refuse every edit of `MODEL` (in the environment: `1`, `true` or `yes`). |

These options describe the startup model; without `MODEL`, all but `--author` and `--timezone` are refused (they
apply to every model opened). An option given on the command line wins over its environment variable. In the environment, list values are separated
by the OS path separator (`:` on Linux), except `EAEDIT_MCP_FOCUS`, which uses `;`.

## Tools

Every reply is plain text. A failure is a reply starting with `error:` that says what to do next.

Models:

- `open_model`: open another `.qea` beside the ones already open, with its own catalogues, eaidl configs, default
  focus and policy, output directory and `name` (default: the file name without extension). `read_only=true` refuses
  every edit (`open_session`, `edit`, `undo`, `discard`, `commit`, `export_changes`, `apply_changes`, `import_svg`),
  for a model you only consult. A relative model path is under the default model's folder; relative catalogue and
  config paths are under the opened model's folder. The output directory defaults to `eaedit-out-<file name>` next
  to the model, or to the one the file had when it was last open in this run. Only the author and timezone carry
  over from the server's options.
- `close_model`: close a model. Its working file stays, so opening it again and `open_session(resume=true)` brings
  staged edits back.
- `models`: the open models, which one is the default, and each one's session.

Every other tool except `operations` takes `model=` (a name from `models`); without it the call goes to the default
model: the one given on the command line, else the first one opened (`open_model(default=true)` moves it). Closing
the default leaves none until another model is opened, and calls without `model=` say which names to pass.

Explore (whole model, no session needed; with a session open they read its working copy, so staged edits show):

- `overview`: the package tree to a depth, with element counts.
- `search`: packages, elements, attributes, connectors and diagrams by name, notes, tags or any of them
  (`field`; substring or `/regex/`), kind, stereotype and package subtree; a match outside the name shows what
  matched.
- `describe`: one thing in compact detail.
- `usages`: where an element is used (attribute types, connectors, diagrams).
- `stereotype`: a stereotype's definition from the catalogues.

Session:

- `open_session`: start editing with a focus (the packages the change belongs in) and a policy.
- `session_status`: focus, policy, operations so far, warnings, whether the model changed underneath.
- `operations`: the edit operations with their parameters. `edit(op, args)` runs one.
- `undo`: take back the last edit. `discard`: drop the session.
- `preview`: what would change per package, warnings and new integrity issues; optionally changed diagrams as text
  (each diagram's first page; its `… N more` line names the `diagram(id=..., page=2)` call for the rest) and the IDL
  diff. Paged like the lists. Packages touched outside the focus are listed in two lines: "allowed under
  connected" (accepted by the policy, e.g. a connector reaching out of the focus) and "would be refused under
  connected" (staged only because the policy is advisory or off); with policy package both say package.
- `commit`: write the model and return the change report, paged: `commit(page=2)` shows the next page of the last
  commit's report and commits nothing.
- `export_changes`: write a change package, leaving the model alone. The reply names the directory and gives one line
  per changed package with counts; `preview` shows the details.
- `apply_changes`: replay a change package onto the model in a new session and preview it.

Diagrams:

- `diagram`: compact text of a diagram, staged edits included (what an agent should normally read).
- `diagram_svg`, `import_svg`: the full eaedit SVG, several thousand tokens even for a medium diagram, and staging
  an edited SVG back.

Checks: `check` (integrity issues the session adds, or the model's errors), `idl_diff` and `idl` (see IDL below).

Nothing is written to the model except by `commit` and by the commit that follows `apply_changes`.

## Change package

`export_changes(name)` writes the directory `<out>/<name>/`:

- `changes.yaml`: the eaedit change file (replayable).
- `report.md`: the change report in Markdown, per package, with links to the diagrams. It reads well pasted into a
  document.
- `diagrams/*.svg`: new and changed diagrams.
- `idl.diff`: with one `--idl-config`; with several, `idl-<config name>.diff` per config.
- `check.txt`: new integrity issues and catalogue warnings.

A name that exists is refused unless `overwrite=true`, and so are the names of the server's own files
(`working.yaml`, `working.rejected.yaml`, `reports`) and names starting with `.`. `commit` also saves its report as
`<out>/reports/<timestamp>.md`.

`apply_changes(path)` takes the package directory (relative paths are under the output directory) or a change file.
It is all or nothing: if one operation fails, no session is left open and the error names the operation. New rows
carry the change file's author, as with `eaedit apply`. The package can be applied to a newer copy of the model; then
`preview` and `commit`. Outside the server,
`eaedit apply MODEL.qea changes.yaml` does the same.

## When the model changes underneath

EA, a git checkout or the server's own commit may change the file while the agent works. Over shared folders
(VM or container mounts) SQLite locking is not reliable, so the server compares the file's hash instead:

- Explore tools reload their snapshot when the file changed.
- An open session reports the change as stale in `session_status` and in every edit reply (`edit`, `undo`,
  `import_svg`) and in `preview`. `commit` refuses. `open_session(resume=true)` replays the session's edits onto the
  new model, keeping its focus and policy (see below), or `discard`.
- Close the model in EA, or at least do not save in EA, while the agent commits.

## Working change file and resume

Every edit saves the whole operation log to `<out>/working.yaml`, with the session's focus and policy, so a crash or
restart loses nothing. While it holds operations, `open_session` without `resume=true` refuses: use `resume=true` to
continue, or `discard` to drop it. `session_status` shows a saved session left by a restart, or says the file is
unreadable and should be discarded. `commit` and `discard` remove the file.

`open_session(resume=true)` resumes when there is something to resume: a saved working file (after a restart), or an
open session that is stale (the model changed on disk). With neither it opens a fresh session; with an open session
that is not stale it refuses. The resumed session keeps the saved focus and policy unless `open_session` is given new
ones.

A resume replays the operations in order. If one no longer applies, it stops there: the session keeps the operations
before it, the full original log is copied to `<out>/working.rejected.yaml`, and the reply names that file, the failing
operation with its arguments, and how many operations followed it.

## IDL

`idl` returns the IDL eaidl generates, from the open session's working copy (staged edits included) or, with no
session, from the model; paged. `idl_diff` returns a unified diff of the IDL before and after the staged changes.
Both take `config`, an eaidl config file (a relative path is under the model's folder), and `overrides`, a JSON
object of eaidl options set over that config's top-level options for this call only, for example
`idl(config="idl.yaml", overrides={"root_packages": ["Messages"], "template": "idl.jinja2"})`. Without `config`
they use the `--idl-config` files, one output per config; with neither, they reply with an error asking for `config`.
An unknown option or a value of the wrong type in `overrides` is an error naming it. So the server needs no restart
to generate with other options.

`preview(idl=true)`, `commit` reports and change packages show the diff for the `--idl-config` files only, each
config with its own diff. The config's database URL is replaced by the server; its `root_packages` apply. eaidl only generates under those roots, so when changed
packages lie outside every root the diff says `changes outside the IDL roots: ...`: an empty diff then does not mean
the change has no effect. An eaidl error is shown as text in place of the diff.

## Review and safety

There are no guards beyond the focus policy and eacore's integrity check on commit. Safety comes from review: look at
the changes in EA, or read the change package, and revert the model file in git if something is wrong.
