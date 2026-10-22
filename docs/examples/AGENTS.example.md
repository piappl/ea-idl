# Modelling agent instructions (example)

You edit an Enterprise Architect model through the `eaedit` tools. You change the model only when you call `commit`
(or write a change package with `export_changes`). Copy this file to `AGENTS.md` and fill in your own conventions.
Your host may show the tools with a prefix (opencode: `eaedit_search`, `eaedit_commit`, ...); the names below
leave it out.

## Workflow

1. **Explore wide.** Before changing anything, read the model: `overview` for the package tree, `search` for existing
   classes and types, `describe` for one thing in detail, `usages` to see where a class or type is used. Find the
   base classes and types a change should reuse instead of creating new ones. Lists are paged: follow `page=K`.
2. **Choose where the change belongs.** Decide which existing packages take the new elements, or which new packages
   you create. Say your choice to the user before editing when it is not obvious.
3. **Open a focused session.** `open_session(focus=[...])` with the packages you chose. Edit only inside the focus.
4. **Edit.** `operations` lists what you can do; call `edit(op, args)` once per change. Name things by qualified name
   (`Model::Package::Element`) or GUID. Read a warning or error, fix the cause, and continue. `undo` takes back the
   last edit; `discard` drops the whole session.
5. **Show it on a diagram** when the change has structure worth seeing: `create_diagram`, `place`, `layout`. Read a
   diagram with `diagram` (text form), not `diagram_svg`.
6. **Preview.** `preview(diagrams=true, idl=true)` shows what changed per package, new integrity issues and the IDL
   diff. Check it against the request.
7. **Finish.** Small change the user approved: `commit`. Larger change for review by other people: `export_changes`
   with a short name, then give the user the package directory and its `report.md`. Never commit what the user has
   not agreed to.

If a tool reports that the model changed on disk, tell the user. Do not retry blindly: `open_session(resume=true)`
replays your edits onto the new model, or `discard`.

## A reference model

When you adapt something from another model (for example a package the user moved over with EA's XMI
export/import), open the source beside the target instead of asking for a restart:
`open_model(path="...", name="source", read_only=true)`. Read it with `model="source"` (`describe`, `search`,
`diagram`, `idl`) and edit the target as usual; tools without `model=` work on the default model. `models` lists what
is open.

## Your modelling conventions

Replace this section with the rules of your model. Two neutral examples of the kind of rule that belongs here:

- Every new class gets the stereotype `<your stereotype>` and a `notes` text of one sentence saying what it is for.
- Types of attributes are taken from the package `<your types package>`; search it before creating a type.
