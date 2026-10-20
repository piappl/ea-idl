# eaedit

Scoped editing of Enterprise Architect `.qea`/`.qeax` repositories outside EA, built on [eacore](./EACORE.md).
Every edit is a named operation that writes the rows EA itself would write. Stereotypes come from
catalogues (MDG technologies, YAML, or what the model already uses), so a new element gets its stereotype
and its tagged values, and a new connector is checked against the profile's rules.

## Quick start

```python
from eaedit import Session

# The focus package must already exist when the session opens, so focus the root and create Demo inside it.
s = Session.open("model.qea", focus=["Model"], policy="connected", catalogues=["docs/examples/eaedit-catalogue.yaml"])
s.create_package(parent="Model", name="Demo")
s.create_element(package="Model::Demo", name="Engine", stereotype="Example::Block")
s.create_element(package="Model::Demo", name="Controller", stereotype="Example::Block")
s.set_tag(target="Model::Demo::Engine", name="owner", value="Propulsion team")
s.connect(source="Model::Demo::Controller", target="Model::Demo::Engine", type="Association")
print(s.preview().report)   # what would change, new integrity issues, warnings
s.commit()                  # one transaction; nothing is written before this
```

Operations return an `OpResult` (`guid`, `warnings`). `s.undo()` reverts the last operation.

```bash
uv run eaedit preview model.qea changes.yaml -c profile.xml --focus Model::Demo   # model is not written
uv run eaedit apply   model.qea changes.yaml -c profile.xml --focus Model::Demo   # replay and commit
uv run eaedit catalogue build profile.xml model.qea -o catalogue.yaml
uv run eaedit catalogue show catalogue.yaml [Example::Block]
```

`-c/--catalogue` and `--focus` can be repeated. A `--focus` package must already exist when the session opens. `--policy` (default `connected`) and `--author` are described below.

## Sessions, focus and policies

A session works on an in-memory copy of the repository. The file changes only on `commit()`.
The focus is a list of packages (qualified name or GUID); it includes their sub-packages. The policy says what
happens when an operation touches something outside the focus. With no focus nothing is restricted.

| Policy | Outside the focus |
|--------|-------------------|
| `package` | Refused (`ScopeError`). A connector counts as inside only if both ends are. |
| `connected` (default) | Refused, except a connector with at least one end inside the focus. |
| `advisory` | Allowed, with a `scope` warning for everything `package` would refuse, including crossing connectors. |
| `off` | Allowed silently. |

Deleting an element or package cascades like EA does, including the element's details (requirements, scenarios,
files, constraints, ...) and those of its attributes, operations and connectors. Rows that point at a deleted row are reset to EA's "unset"
value and reported as `reference-cleared`. Clearing a reference in a row outside the focus counts as touching
that package, so under `package` and `connected` it raises `ScopeError`.

A focus root itself belongs to its parent package's contents: under `package` and `connected`, renaming, moving,
deleting or otherwise changing the focus package's own rows raises `ScopeError` (`advisory` warns). Focus its
parent to change it. Its sub-packages and contents are inside the focus as usual.

A refused operation is rolled back completely. `commit()` re-checks scope over the whole change.

**Timestamps.** EA stores CreatedDate and ModifiedDate as local time with no zone, in the timezone of the Windows
machine running EA. eaedit writes the local time of the machine it runs on, so in a container on UTC its dates
would be hours off from EA's. Pass `Session.open(..., timezone="Europe/Warsaw")`, or set `TZ=Europe/Warsaw` in the
environment, to write the same local time as EA. Replaying a change file reuses the timestamps recorded in the file
and ignores the clock.

## Identifiers

Anywhere an operation takes an element, package, attribute or connector, give either:

- a GUID, with braces: `{1A2B...}`;
- a qualified name: `Model::core::Message` (element), `Model::core::Message.size` (attribute).

Connectors have no reliable name, so address them by GUID (`find_connectors` lists them). An ambiguous name
raises `AmbiguousNameError` listing the candidate GUIDs.

## Operations

| Area | Operations |
|------|------------|
| Packages | `create_package`, `update_package`, `move_package`, `delete_package(recursive=)` |
| Elements | `create_element`, `update_element`, `move_element`, `delete_element` |
| Stereotypes, tags | `add_stereotype`, `remove_stereotype`, `set_tag`, `delete_tag` |
| Attributes | `add_attribute`, `update_attribute`, `move_attribute`, `delete_attribute`, `set_classifier` |
| Connectors | `connect`, `update_connector`, `reconnect`, `delete_connector` |
| Queries (not logged) | `get`, `list`, `tree`, `search`, `find_connectors` |

Notes:

- New elements and packages get EA-like defaults; the Package `t_object` row is created with its `t_package`.
  `TPos` is left NULL, as EA does.
- `create_element` takes the base type from the stereotype's catalogue entry; pass `type=` if it applies to several.
- `update_*` take column-style fields (`s.update_element(el=..., alias="x")`).
- Session methods also take positional arguments in the operation's parameter order (`s.delete_element("X")`,
  `s.create_element("Model::Demo", "Engine")`); the log records them by name.
- `move_element` moves nested elements with their owner. Moving a nested element on its own unnests it (ParentID
  reset, `unnested` warning), since its owner stays in the old package. Diagrams owned by moved elements move too.
- Adding a stereotype also adds the tags it defines (own and inherited) that the target lacks, with catalogue defaults.
  A profile-less stereotype the model has never used is registered in `t_stereotypes` and referred to by GUID, as
  EA does; this repository-wide row never counts against the focus. A stereotyped connector gets the label EA
  shows on it (`«S»`; `«abstraction»` above it on an Abstraction).
  Removing a stereotype keeps its tags (`stereotype-removed-tags-kept`).
- `connect` with a stereotype checks both ends against the profile's connector rules and warns, never refuses.

## Catalogues

A catalogue lists stereotypes: base types they apply to, tags (type, values, default), inheritance and
connector end constraints. Sources, most authoritative first:

1. **YAML** (including the IDL catalogue written by the `eaidl catalogue` command);
2. **MDG technology XML**;
3. **inferred** from a `.qea` (also from the model being edited, unless `infer=False`).

For each stereotype the highest-precedence source wins; within a level, the order given. Bare names resolve if
unambiguous, otherwise write `Profile::Name`.

A stereotype inherits the tags of every parent its MDG lists (`generalizes` and `baseStereotypes`), including
parents from other profiles. NAFv4-Core builds on EA's own BPMN 2.0 and SysML 1.4 profiles, so to add the same
tags as EA, also load EA's `BPMN 2.0 Technology.xml` (in EA's `MDGTechnologies` folder) and
`docs/examples/sysml14-catalogue.yaml` (EA has no SysML file to read). A parent no catalogue defines gives a
`missing-base` warning.

When a stereotype is applied, each new tag gets its Notes as EA writes them: `Values: a,b` for an enumeration or
boolean, then `Default: x` when the tag has a default.

Stereotypes a model uses without a profile (no `FQName` in EA's stereotype list) are inferred under the profile
`(unknown)`. A bare name found both there and in a named profile means the named one. Applying an `(unknown)`
stereotype writes it as EA does: by name, plus `GUID=` of its `t_stereotypes` row when one applies to the target's
base type. The `(unknown)` profile name is never written to the model.

```yaml
profile: Example
source: {kind: yaml, file: profile.yaml}
stereotypes:
  - name: Block
    applies_to: [Class]
    abstract: false
    generalizes: []
    tags:
      - {name: kind, type: enumeration, values: [hardware, software], default: software}
    constraints:                    # connector stereotypes: allowed ends
      - {role: client, target: Example::Block}
```

A file may hold one catalogue (a mapping) or several (a list). `eaedit catalogue build` merges any mix of sources
into one YAML file (one catalogue per profile); `eaedit catalogue show` lists a catalogue or prints one stereotype
with its inherited tags. A different command, `eaidl catalogue -o idl.yaml` (the eaidl CLI, not eaedit), writes the stereotypes eaidl itself reads.

**MDG errata.** Vendor MDG files sometimes contain mistakes that break their own rules. The parser applies a small
table of known textual fixes before parsing and records them in the catalogue's `source.errata`. Example: the
NAFv4 files spell the realization role `realizingMeassage`, which would reject a valid ResourceExchange to
ResourceMessage realization.

## Diagrams

Diagram operations write only diagram rows (`t_diagram`, `t_diagramobjects`, `t_diagramlinks`, a diagram's own
`diagram properties` row), notes and their note links, and on sequence messages `DiagramID`, `SeqNo` and `PDATA5`.
They never change model content. A diagram belongs to its owning package (or element), so scope rules apply to it.
Mint-once identifiers (GUIDs, and the DUID of each diagram object) come from the session, so change files replay
byte for byte.

| Area | Operations |
|------|------------|
| Diagrams | `create_diagram(owner, name, type)`, `update_diagram`, `delete_diagram` |
| Objects | `place(diagram, element, rect=None)`, `set_bounds`, `set_stacking`, `remove_from_diagram` |
| Connectors | `show_connector`, `hide_connector` |
| Notes | `add_note(diagram, text, rect=None)`, `set_note_text`, `link_note(note, target)` |
| Sequence messages | `show_message(diagram, connector, order=None, offset=None)`, `set_message_order(diagram, connectors)` |
| Layout | `layout(diagram, spec)`; `plan_layout(session, diagram, spec)` computes the same positions without staging |

- `type` is a UML type (`Class`, `Sequence`, ...) or an MDG view by name. The P2, P6, L7 and P7 views, and plain
  `Sequence` and `Custom` (written with the defaults read from the hand-made p6 row and from the hand-made Custom rows
  P2, L7 and P7), do not warn. Every other UML type (`Class`, `Activity`, `Package`, ...) and every other view warns
  `unverified-default`.
- `update_diagram(diagram, **fields)` takes `name`, `notes`, `page_width` (`cx`), `page_height` (`cy`) and
  `orientation` (`P` portrait or `L` landscape).
- A diagram is found by `package::name`, also when an element owns it, so `create_diagram` and `update_diagram(name=)`
  refuse a name another diagram of the same package has (the error names that diagram's GUID).
- `place`, `set_bounds`, `set_stacking` and `remove_from_diagram` return the diagram object's DUID (`""` for an object
  without one); the other operations return the GUID of the diagram, note or connector they act on.
- Elements go on a diagram wherever you place them; `place` without `rect` finds a free spot. A Part is kept inside its
  owner's rectangle (`moved-inside-owner`). When both ends of a connector are on the diagram its link row is written,
  as the GUI does. A note on a connector is stored as EA does (the note refers to the connector in `PDATA4`, `NType`
  1); `NType` 1 comes from the single hand-made sample, so it warns `unverified-default`. A note on an element gets a
  `NoteLink` from the element to the note. Linking it again returns the existing link (`already-linked`).
- A sequence message is shown on one diagram: `show_message` refuses a message another diagram shows (the error names
  it). An explicit `order` already taken on the diagram moves that message and the later ones down one, so the
  diagram's numbers stay unique.
- Deleting an element or connector removes its diagram rows. A note shown nowhere else is deleted with its last
  object: by `delete_element`, by `remove_from_diagram` and by `delete_diagram` (and by an SVG import that drops it).
- A dangling diagram object (its element is gone) is carried through untouched by every operation, layout and
  import.

**`Rect`** is `(left, top, right, bottom)` in SVG orientation: `y` grows downwards, all values are non-negative,
`left < right`, `top < bottom`. The database stores `RectTop`/`RectBottom` negated; eaedit converts. Any 4-sequence is
accepted (a change file stores a list).

### Layout specs

`layout` takes a dict with a `pattern`, naming elements by qualified name or GUID, and optionally `page`
(`[width, height]`, default the diagram's `cx`/`cy`). Elements already on the diagram keep their size; others get one
that fits their name and attributes. Objects the layout is not given stay put and the layout goes below them. The same
spec always gives the same positions.

| Pattern | Keys |
|---------|------|
| `layers` | `rows` (list of lists of elements), `direction` (`down` or `right`), `gap` |
| `hub` | `center`, and `above`, `below`, `left`, `right` (lists of elements), `gap` |
| `contain` | `owner`, `children` (default its Parts), `padding` |
| `suggest` | `elements` (default everything on the diagram), `focus` (centred in its layer), `gap`; layers follow connector direction, notes go right of their element |

When the content does not fit the page, `layout` warns `page-overflow`, with a suggested split into several
diagrams. Elements shown twice on a diagram are skipped (`layout-skipped`).

### Preview

`session.preview()` has `diagrams`: for each diagram the session created or changed, a `RenderedDiagram` (`guid`,
`name`, `svg`, `png`) of how it will look after commit. `png` is always None there: `Session.preview` never asks for
one. It is rendered from a temporary copy of the model with the staged changes applied; the model is not touched.
Pass `render=False` to skip it. The same renderer is available directly as
`eaedit.diagrams.render.render_working(session, diagrams=None, png=False)`; `png=True` fills `png` when `cairosvg` is
installed.

```bash
uv run eaedit preview model.qea changes.yaml --out previews/      # also writes previews/<diagram name>.svg
uv run eaedit diagram export model.qea Model::pkg::Overview -o overview.svg
uv run eaedit diagram import model.qea overview.svg [--owner Model::pkg] [--apply]   # previews unless --apply
```

`diagram import` takes `--focus`, `--policy`, `-c` and `--author` like `preview`. Both render diagrams only with
`--out`.

### eaedit SVG

An exported SVG is an ordinary picture with `data-ea-*` attributes added. Import reads only those attributes;
colours, text, fonts and everything else are presentation and ignored. Export, then import with no edit, stages
nothing. An agent can edit the exported file, or write one from scratch with these attributes.

On the `<svg>` element: `data-ea-diagram` (the diagram's GUID; leave it out to create a new diagram), `data-ea-name`,
`data-ea-type` (a new diagram needs both, and `import --owner PACKAGE`). Changing the name renames the diagram;
changing the type of an existing diagram is not done (warning `type-kept`).

On any element (`<g>`) for an object on the diagram:

| Attribute | Meaning |
|-----------|---------|
| `data-ea-guid` | GUID of the element or note. Required, except on a new note and a dangling object. |
| `data-ea-duid` | The diagram object's DUID: tells apart an element shown twice. Optional. |
| `data-ea-rect` | `left,top,right,bottom` (see `Rect`). Required. |
| `data-ea-z` | Stacking order (`Sequence`), a non-negative integer; applied with `set_stacking`. Optional. |
| `data-ea-kind` | `element`, `note` or `readonly`. |
| `data-ea-text` | A note's text. |
| `data-ea-id` | Only on a new note (no GUID): any label unique in the file, so note links can name it. |

On a connector, note link or message:

| Attribute | Meaning |
|-----------|---------|
| `data-ea-guid` | GUID of the connector (required, except on a new note link). |
| `data-ea-kind` | `notelink` or `message`; none for an ordinary connector. |
| `data-ea-hidden` | `1` to hide the connector's link on this diagram, `0` to show it. |
| `data-ea-from`, `data-ea-to` | A note link's two ends (element, note or connector GUIDs, or a new note's `data-ea-id`). Required on a new note link. |
| `data-ea-seq`, `data-ea-offset` | A message's order and vertical offset. |

Rules:

- Import applies the difference between the file and the diagram: an element with a group and no object is placed, one
  whose rectangle differs is moved, an object whose group is missing is removed from the diagram. A connector whose
  group is missing is left unchanged; use `data-ea-hidden="1"` to hide it.
- Removing a note's group deletes the note if it is on no other diagram.
- A file that breaks a rule is refused with a message naming the group, and nothing is staged: not XML or root not
  `<svg>`; an object without `data-ea-rect` or `data-ea-guid` (a group with a `data-ea-guid` of an element but no
  `data-ea-kind` and no rect counts as one); an unknown GUID or `data-ea-kind`; a bad rectangle, a negative
  `data-ea-z`, a `data-ea-hidden` other than 0 or 1; `data-ea-id` or `data-ea-duid` used twice; a connector whose ends
  are not both shown; a note link whose ends are not both shown or that has no note at an end; a Part outside its
  owner's rectangle when the file changed the Part's or the owner's rectangle (a Part already outside, e.g. placed
  before its owner or left behind by `set_bounds` on the owner, is carried as it is).
- `data-ea-kind="readonly"` marks objects eaedit has no operation for (interaction fragments, boundaries, text), and
  dangling objects, whose element is gone: those have no `data-ea-guid` and are named by `data-ea-duid`. They are
  kept where they are; moving or dropping one only warns `readonly-kept`.
- A new note's `data-ea-z` is applied like any other object's, so a file written from scratch, imported, then
  imported again naming what it created stages nothing.
- A Part is checked against its owner's new rectangle, so when you move an owner, move its Parts in the same file.

### Limitations

| Limitation | How it will be lifted |
|---|---|
| Views other than P2, P6, L7 and P7, and UML diagram types other than `Sequence` and `Custom` (such as `Class`), work but warn `unverified-default`. | Hand-made samples of each view turn their defaults into verified ones. |
| eaedit cannot create bend points or set a connector's route style or label positions. Existing routes, bend points and label positions are kept. | Operations (and SVG rules) for waypoints, route style, label offsets. |
| Objects eaedit has no operation for (interaction fragments, boundaries, swimlanes, hyperlinks, text, images, ...) are carried through unchanged; the SVG marks them `readonly`. | One operation set (and SVG rule) per object kind, as needed. |
| Per-object appearance (colours, fonts, line widths), feature visibility and diagram-wide settings (`StyleEx`, `PDATA` switches) are written with EA's defaults and otherwise preserved, not editable. | Appearance and visibility operations mapping to those style keys. |
| Matrix, Kanban and other special diagram modes are not supported. | Only if needed. |
| Changing an existing diagram's type (EA's "Change Type") is not supported; import warns `type-kept`. | An `update_diagram` type change mapping to EA's rows. |

See [docs/examples/eaedit-diagram.yaml](./docs/examples/eaedit-diagram.yaml), a change file on `tests/data/empty.qea`
that creates two classes, a Class diagram, a layout and a note.

## Warnings

Operations succeed with warnings when the catalogue or defaults are doubtful; errors are for things that cannot
be done. Warnings appear in `OpResult.warnings`, `session.warnings` (until `commit()`) and the CLI output.

| Code | Meaning |
|------|---------|
| `unknown-stereotype` | Not in any catalogue; the name is stored as given. |
| `ambiguous-stereotype` | Bare name matches several profiles; stored without a profile. |
| `abstract-stereotype` | The stereotype is abstract. |
| `missing-base` | The stereotype inherits from one no loaded catalogue defines (often one of EA's built-in profiles); EA would add its tags, eaedit cannot. |
| `wrong-base-type` | The stereotype does not apply to the target's base type. |
| `unknown-tag` | `set_tag` named a tag none of the target's stereotypes defines. |
| `stereotype-removed-tags-kept` | A stereotype was removed; its tag rows stay. |
| `connector-end` | An end does not satisfy the stereotype's connector constraint. |
| `diagram-link-dropped` | `reconnect` dropped a diagram link: the new end is not on that diagram or has no diagram object identifier. |
| `unnested` | `move_element` moved a nested element away from its owner; it is no longer nested. |
| `reference-cleared` | A delete reset a reference in a surviving row. |
| `unverified-kind` | The type's storage was not checked against EA-made data. |
| `unverified-default` | Defaults for a new row are a best guess, not checked against EA-made data. |
| `moved-inside-owner` | A Part's rectangle was moved inside its owner's. |
| `already-on-diagram` | `place` named an element the diagram already shows. |
| `already-linked` | `link_note` named a target the note is already linked to; the existing link is returned. |
| `page-overflow` | A layout does not fit the page; the message suggests a split. |
| `layout-skipped` | An element shown twice on the diagram was not moved by a layout. |
| `readonly-kept` | Import left a read-only diagram object as it is. |
| `type-kept` | Import did not change an existing diagram's type. |
| `scope` | Outside the focus under `advisory`. |

## Change files

`save(session, path)` writes the session's operation log; `replay(session, path, author=None)` re-runs it:

```python
from eaedit.changefile import save, replay
save(s, "changes.yaml")
replay(Session.open("other.qea"), "changes.yaml")
```

The file is YAML (`eaedit: 1`, `author`, then `ops` with `op`, `at`, `args`, `created`). Each operation stores the
timestamp it ran at and the GUIDs it created, so replaying onto the same starting model gives identical rows.
Arguments are logged as plain values (tuples and sets as lists, paths as text, enums by value); an operation called
with anything else is refused before it runs. Replay
records the change file's author unless you pass `author=` (`--author` on the command line). A replay failure names the operation number. See
[docs/examples/eaedit-example.yaml](./docs/examples/eaedit-example.yaml).

## Safety

- `commit()` writes only changed rows, in one transaction, and refuses if the file changed since it was opened
  or another program (EA) holds it. Close the model in EA first.
- It also refuses (`CommitRefusedError`, CLI exit 1) when the edit introduces new integrity errors (checked with
  `eacore check`). Problems already in the model are ignored.
- Under `package`/`connected`, a scope violation at commit also refuses.
- Work on a copy while trying things out; `eaedit preview` never writes.

## Acceptance checklist in EA

Automated tests cannot prove EA accepts the result. Check once by hand:

1. Copy `tests/data/empty.qea`.
2. Run the example change file:
   `uv run eaedit apply copy.qea docs/examples/eaedit-example.yaml -c docs/examples/eaedit-catalogue.yaml`
3. Open the file in EA.
4. Run Project > Integrity Check with all checks enabled; expect no errors.
5. Confirm that `Engine` and `Controller` show the `Block` stereotype with their catalogue tags (`owner`, `kind`) in the
   Properties window.
6. Confirm that the connector between them appears in the Relationships window.

## Package boundaries

`eaedit` depends on `eacore`. It does not import `eaidl`, except `eaedit.diagrams.render`, which renders diagrams
with eaidl's native diagram extractor and SVG renderer; `eaidl` does not import `eaedit`.
