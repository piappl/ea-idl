# eaedit-mcp

An [MCP](https://modelcontextprotocol.io) server that lets an agent explore and edit one Enterprise Architect `.qea`
model through [eaedit](./EAEDIT.md). It is generic: it knows no modelling conventions and no workflow. Those belong in
the agent's own instructions (see [docs/examples/AGENTS.example.md](./docs/examples/AGENTS.example.md)).

The server speaks stdio and works on one model file, with at most one editing session at a time. The agent sees
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
eaedit-mcp MODEL.qea [options]      # also: eaedit mcp MODEL.qea [options]
```

An agent host starts this as a subprocess. For opencode in a container, see
[docs/examples/opencode.json](./docs/examples/opencode.json). That file is opencode's configuration format, not
ours: it may change, so check opencode's documentation. Paths in it are placeholders.

| Option | Environment variable | Meaning |
|--------|----------------------|---------|
| `MODEL` | `EAEDIT_MCP_MODEL` | The `.qea` file. |
| `-c`, `--catalogue` (repeatable) | `EAEDIT_MCP_CATALOGUES` | MDG XML, YAML or `.qea` stereotype catalogue. |
| `--idl-config` (repeatable) | `EAEDIT_MCP_IDL_CONFIGS` | An eaidl config; enables IDL diffs, one per config. |
| `--author` | `EAEDIT_MCP_AUTHOR` | Author written on new items. |
| `--timezone` | `EAEDIT_MCP_TIMEZONE` | IANA timezone for timestamps. |
| `--focus` (repeatable) | `EAEDIT_MCP_FOCUS` | Default focus of a session. |
| `--policy` | `EAEDIT_MCP_POLICY` | Default focus policy: `package`, `connected` (default), `advisory`, `off`. |
| `--out` | `EAEDIT_MCP_OUT` | Output directory, default `eaedit-out` next to the model. |

An option given on the command line wins over its environment variable. In the environment, list values are separated
by the OS path separator (`:` on Linux), except `EAEDIT_MCP_FOCUS`, which uses `;`.

## Tools

Every reply is plain text. A failure is a reply starting with `error:` that says what to do next.

Explore (whole model, no session needed; with a session open they read its working copy, so staged edits show):

- `overview`: the package tree to a depth, with element counts.
- `search`: packages, elements, attributes, connectors and diagrams by name (substring or `/regex/`), kind,
  stereotype and package subtree.
- `describe`: one thing in compact detail.
- `usages`: where an element is used (attribute types, connectors, diagrams).
- `stereotype`: a stereotype's definition from the catalogues.

Session:

- `open_session`: start editing with a focus (the packages the change belongs in) and a policy.
- `session_status`: focus, policy, operations so far, warnings, whether the model changed underneath.
- `operations`: the edit operations with their parameters. `edit(op, args)` runs one.
- `undo`: take back the last edit. `discard`: drop the session.
- `preview`: what would change per package, warnings and new integrity issues; optionally changed diagrams as text
  and the IDL diff.
- `commit`: write the model and return the change report.
- `export_changes`: write a change package, leaving the model alone.
- `apply_changes`: replay a change package onto the model in a new session and preview it.

Diagrams:

- `diagram`: compact text of a diagram, staged edits included (what an agent should normally read).
- `diagram_svg`, `import_svg`: the full eaedit SVG, several thousand tokens even for a medium diagram, and staging
  an edited SVG back.

Checks: `check` (integrity issues the session adds, or the model's errors) and `idl_diff`.

Nothing is written to the model except by `commit` and by the commit that follows `apply_changes`.

## Change package

`export_changes(name)` writes the directory `<out>/<name>/`:

- `changes.yaml`: the eaedit change file (replayable).
- `report.md`: the change report in Markdown, per package, with links to the diagrams. It reads well pasted into a
  document.
- `diagrams/*.svg`: new and changed diagrams.
- `idl.diff`: with one `--idl-config`; with several, `idl-<config name>.diff` per config.
- `check.txt`: new integrity issues and catalogue warnings.

A name that exists is refused unless `overwrite=true`. `commit` also saves its report as
`<out>/reports/<timestamp>.md`.

`apply_changes(path)` takes the package directory (relative paths are under the output directory) or a change file.
It is all or nothing: if one operation fails, no session is left open and the error names the operation. The package
can be applied to a newer copy of the model; then `preview` and `commit`. Outside the server,
`eaedit apply MODEL.qea changes.yaml` does the same.

## When the model changes underneath

EA, a git checkout or the server's own commit may change the file while the agent works. Over shared folders
(VM or container mounts) SQLite locking is not reliable, so the server compares the file's hash instead:

- Explore tools reload their snapshot when the file changed.
- An open session reports the change as stale in `session_status` and in every edit reply. `commit` refuses.
  `open_session(resume=true)` replays the session's edits onto the new model (and stops with a message naming the
  first operation that no longer applies), or `discard`.
- Close the model in EA, or at least do not save in EA, while the agent commits.

## Working change file and resume

Every edit saves the whole operation log to `<out>/working.yaml`, so a crash or restart loses nothing. While it holds
operations, `open_session` without `resume=true` refuses: use `resume=true` to continue, or `discard` to drop it.
`session_status` shows a saved session left by a restart. `commit` and `discard` remove the file.

## IDL diff

With `--idl-config`, `preview(idl=true)`, `idl_diff`, `commit` reports and change packages show a unified diff of
the IDL eaidl generates before and after the staged changes. Each config gets its own diff. The config's database URL
is replaced by the server; its `root_packages` apply. eaidl only generates under those roots, so when changed
packages lie outside every root the diff says `changes outside the IDL roots: ...`: an empty diff then does not mean
the change has no effect. An eaidl error is shown as text in place of the diff.

## Review and safety

There are no guards beyond the focus policy and eacore's integrity check on commit. Safety comes from review: look at
the changes in EA, or read the change package, and revert the model file in git if something is wrong.
