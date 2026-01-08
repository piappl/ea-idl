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

# Sync dependencies including dev tools (pytest, ruff, pre-commit)
uv sync --extra dev

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
pip install -e "."
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

## Regenerate docs

```sh
cd scripts
./export_diagrams.sh --model /home/${USER}/git/4817/ea-idl/tests/data/nafv4.qea  --output /tmp
# rm -r ../docs/images/{data,message}
cp -r /tmp/Model/core/* ../docs/images
```
