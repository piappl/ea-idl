# eaidl

This is replacement for [idl4-enterprise-architect](https://github.com/rticommunity/idl4-enterprise-architect),
but not as plugin, but rather something that can be run as part of CI against database.
Similar in concepts in [pyMDG](https://github.com/Semprini/pyMDG), but we have some different [assumptions on model structure](./MODEL.md).

For detailed code structure documentation, see [STRUCTURE.md](./STRUCTURE.md).


## setup environment

### Using uv (recommended)

```sh
# Install uv if you haven't already
curl -LsSf https://astral.sh/uv/install.sh | sh

# Sync dependencies, all extras and dev tools (pytest, ruff, pre-commit)
uv sync

# Runtime only, no dev tools: uv sync --no-dev  (add --extra mcp for eaedit-mcp)

# Install pre-commit hooks
uv run pre-commit install

# Run tests
uv run pytest
```

### Alternative: Using pyenv

```sh
# This example uses pyenv
pyenv update
pyenv install 3.13
pyenv virtualenv 3.13 eaidl
pyenv activate eaidl

# Development mode install
pip install -e ".[enchant,mcp]"  # plus: pip install --group dev (pip >= 25.1)
# We use pre-commit hook
pre-commit install
pytest
```

## Quick Start

### Running Tests

```bash
uv run pytest                          # All tests
uv run pytest tests/test_diagram.py -v  # Specific test file
uv run pytest --cov=src/eaidl           # With coverage
```

### Running the Tool

There are sample configuration files provided in [config](./config/).

```sh
# Generate IDL from sample SQLite database:
uv run eaidl run --config config/sqlite.yaml

# Generate IDL from PostgreSQL (needs custom configuration):
uv run eaidl run --config config/postgres.yaml > res.idl

# Other commands available:
uv run eaidl diagram --config config/sqlite.yaml --output diagram.puml  # Generate PlantUML diagram
uv run eaidl packages --config config/sqlite.yaml                        # List packages
uv run eaidl docs --config config/sqlite.yaml --output ./_docs           # Generate HTML docs

# Export/import notes for review by non-EA users:
uv run eaidl export-notes --config config/sqlite.yaml --output notes.docx  # Export notes to DOCX
uv run eaidl import-notes --config config/sqlite.yaml --input notes.docx   # Import edited notes (dry-run)

# Export full model structure to YAML or Markdown:
uv run eaidl export-model --config config/sqlite.yaml --output model.yaml              # YAML (default)
uv run eaidl export-model --config config/sqlite.yaml --output model.md --format markdown  # Markdown
uv run eaidl export-model --config config/sqlite.yaml --output model.md --format markdown --diagrams-dir images  # with diagram images
```

## Export and Import Notes for External Review

Export model notes to DOCX for non-EA users to edit, then import changes back:

```sh
# Export all notes to DOCX (hierarchical: packages/classes/attributes)
uv run eaidl export-notes --config config/sqlite.yaml --output notes.docx

# Import changes (dry-run by default, use --no-dry-run to commit)
uv run eaidl import-notes --config config/sqlite.yaml --input notes.docx
uv run eaidl import-notes --config config/sqlite.yaml --input notes.docx --no-dry-run  # Live
```

The export includes metadata for validation. Import supports **partial updates** (checksum-matched) for parallel editing workflows. Use `--strict` to fail on mismatches, `--report` for JSON output.

## Export Full Model Structure

The `export-model` command exports the complete model (all packages, classes, attributes, and relations) to a portable YAML or Markdown file. Packages are listed flat with child packages referenced by GUID.

```sh
# Export to YAML (default)
uv run eaidl export-model --config config/sqlite.yaml --output model.yaml

# Export to Markdown
uv run eaidl export-model --config config/sqlite.yaml --output model.md --format markdown

# Export to Markdown with embedded diagram images
uv run eaidl export-model --config config/sqlite.yaml --output model.md --format markdown --diagrams-dir images
```

The `--diagrams-dir` option specifies a directory (relative to the output file) containing exported diagram images; when provided, Markdown output embeds them inline.

### using uvx

```sh
uvx --with sqlite --from git+https://github.com/piappl/ea-idl/ eaidl run --config config/sqlite.yaml
uvx --with psycopg2 --from git+https://github.com/piappl/ea-idl/ eaidl run --config config/postgres.yaml
```


## Generate Interactive HTML Documentation

The `docs` command generates a complete static website with interactive documentation from your EA model:

```sh
# Generate HTML documentation
uv run eaidl docs --config config/sqlite.yaml --output ./docs

# With debug logging
uv run eaidl docs --config config/sqlite.yaml --output ./docs --debug
```

By default the docs apply the same model transforms as the `run` command
(stereotype filtering, privatization, empty-union collapse, map conversion,
abstract-class flattening and unused-class pruning), so the documentation
mirrors the generated IDL. Use `--raw` to skip all transforms and document the
unprocessed loaded model:

```sh
# Document the raw model, no transforms applied
uv run eaidl docs --config config/sqlite.yaml --output ./docs --raw
```

> **Note:** Classes removed by transforms (e.g. via `filter_stereotypes`) get
> no class page and drop out of auto-generated class diagrams. EA-authored
> (hand-drawn) diagrams still render filtered classes as nodes, but their
> cross-reference links won't resolve since the class is no longer in the model.

## Regenerate docs

```sh
cd scripts
# export WINEPREFIX=~/.wine32
# export WINEARCH=win32
./export_diagrams.sh --model ${PWD}/../tests/data/nafv4.qea  --output /tmp
# rm -r ../docs/images/{data,message}
cp -r /tmp/Model/core/* ../docs/images
```

## Complete model-view documentation

An optional `documentation` section publishes diagrams independently of the
IDL `root_packages` and transforms. It applies only to HTML documentation;
`run` continues to use its existing type scope. For example:

```yaml
documentation:
  title: STANAG4817 documentation
  root_packages: ['{MODEL-PACKAGE-GUID}']
  sections:
    behaviour:
      title: State machines and lifecycles
      views: [P5]
    interactions:
      title: Message exchanges
      views: [P6]
    data:
      title: Data models
      views: [P7]
  exclude_diagrams: {} # Diagram GUID: non-empty reason
  fail_on_diagram_error: true
```

Each documentation root selects all diagrams in its package subtree. GUIDs
are recommended; package names must resolve uniquely. NAF viewpoint metadata
in EA's `StyleEx` determines the section, with matching ancestor package names
as a fallback. Unmapped diagrams appear under **Other model views** rather than
being dropped. A section can optionally specify `root_packages` to restrict its viewpoint
mapping to a subtree. This allows separate P7 sections for different AEPs.
Overlapping matches fail rather than duplicating diagrams. `documentation.title`
sets the home-page heading and navigation brand. Set
`documentation.apply_transforms: false` for a combined engineering reference;
the default remains `true` for documentation matching generated IDL.

The landing page links to a filterable `diagrams.html` catalogue. Diagram GUIDs
identify standalone HTML pages and downloadable SVGs under `diagrams/`, so
same-named diagrams remain distinct. Diagram names and notes enter the global
search index. This catalogue always uses the native SVG renderer; the existing
package diagrams still use `diagrams.renderer`, and autogenerated class
coverage remains available.

`diagram-coverage.json` records every scoped diagram as rendered, excluded or
failed. Rendering failures fail the build by default after writing the report.
Setting `fail_on_diagram_error: false` allows a partial catalogue with visible
failure entries. Explicit exclusions require reasons and must refer to scoped
diagrams. Native diagrams preserve context-only elements, while type links
resolve only to classes present in the generated documentation profile.

`documentation.package_groups` groups root packages in the sidebar without
changing model namespaces or output URLs. For example, `AEP-105: [base, catl]`
and `AEP-109: [aep109]` associate base types with their AEP. The sidebar links
to each configured model-view section, supports expandable package branches,
and can be hidden with the Menu button on desktop or shown on mobile.

`documentation.package_group_sections` maps each package-group title to
catalogue section keys, placing its diagram links alongside the type tree and
removing those entries from the shared model-view menu. For example:

```yaml
documentation:
  package_groups:
    AEP-105: [base, catl]
    AEP-109: [aep109]
  package_group_sections:
    AEP-105: [data105]
    AEP-109: [data109]
```

Set `diagrams.native_diagram_style.font_family: Carlito` to use the bundled
SIL Open Font License font in HTML and catalogue SVGs. This matches the
detailed renderer's text-width estimates. The default renderer font remains
unchanged for existing configurations. Fonts are distributed with the static
site; no external font service or local font installation is needed.

When a diagram catalogue is configured, package pages link to its canonical
GUID-based diagram pages instead of embedding the authored diagrams again.
Autogenerated type diagrams remain on package pages. The combined export
omits legacy per-package `diagram.html` copies.

`documentation.flatten_package_roots` lists root package names whose children
should appear directly under their AEP group. For example `[aep109]` puts
`common` and `interfaces` at the same menu depth as AEP-105 `base` and `catl`.
This changes navigation only; model namespaces and page URLs are preserved.
