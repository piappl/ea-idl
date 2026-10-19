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

## Warnings

Operations succeed with warnings when the catalogue or defaults are doubtful; errors are for things that cannot
be done. Warnings appear in `OpResult.warnings`, `session.warnings` (until `commit()`) and the CLI output.

| Code | Meaning |
|------|---------|
| `unknown-stereotype` | Not in any catalogue; the name is stored as given. |
| `ambiguous-stereotype` | Bare name matches several profiles; stored without a profile. |
| `abstract-stereotype` | The stereotype is abstract. |
| `wrong-base-type` | The stereotype does not apply to the target's base type. |
| `unknown-tag` | `set_tag` named a tag none of the target's stereotypes defines. |
| `stereotype-removed-tags-kept` | A stereotype was removed; its tag rows stay. |
| `connector-end` | An end does not satisfy the stereotype's connector constraint. |
| `diagram-link-dropped` | `reconnect` dropped a diagram link: the new end is not on that diagram or has no diagram object identifier. |
| `unnested` | `move_element` moved a nested element away from its owner; it is no longer nested. |
| `reference-cleared` | A delete reset a reference in a surviving row. |
| `unverified-kind` | The type's storage was not checked against EA-made data. |
| `unverified-default` | Defaults for a new row are a best guess, not checked against EA-made data. |
| `scope` | Outside the focus under `advisory`. |

## Change files

`save(session, path)` writes the session's operation log; `replay(session, path, author=None)` re-runs it:

```python
from eaedit.changefile import save, replay
save(s, "changes.yaml")
replay(Session.open("other.qea"), "changes.yaml")
```

The file is YAML (`eaedit: 1`, `author`, then `ops` with `op`, `at`, `args`, `created`). Each operation stores the
timestamp it ran at and the GUIDs it created, so replaying onto the same starting model gives identical rows. Replay
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

`eaedit` depends on `eacore`. It does not import `eaidl`, and `eaidl` does not import it.
