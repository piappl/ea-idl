# CLAUDE.md - AI Assistant Context for EA-IDL Project

## Project Overview
EA-IDL is a Python tool that converts Enterprise Architect (EA) database models into IDL (Interface Definition Language) format.
It's a replacement for idl4-enterprise-architect but runs as a standalone CLI tool or CI pipeline component rather than an EA plugin.

**Architecture Details**: See [STRUCTURE.md](./STRUCTURE.md) for detailed code structure, data flow, and component documentation.

**Modeling Conventions**: See [MODEL.md](./MODEL.md) for EA stereotypes, naming conventions, and model structure rules.

## Quick Start for AI Assistants

### Running Tests
```bash
# Run all tests
uv run pytest

# Run specific test file
uv run pytest tests/test_diagram.py -v

# Run with verbose output
uv run pytest tests/ -v --tb=short
```

### Running the Tool
```bash
# Against SQLite test database
uv run eaidl --config config/sqlite.yaml

# With PostgreSQL
uv run eaidl --config config/postgres.yaml > output.idl

# CLI commands available
uv run eaidl_cli run      # Generate IDL (default)
uv run eaidl_cli diagram  # Generate PlantUML diagrams
uv run eaidl_cli packages # List packages
```

### Development Setup
```bash
# Sync dependencies including dev tools (pytest, ruff, pre-commit)
uv sync --extra dev

# Install pre-commit hooks
uv run pre-commit install
```

## Code Quality Standards

### Linting and Formatting
- **Tool**: Ruff (configured in pyproject.toml)
- **Line length**: 120 characters
- **Target**: Python 3.13
- **Exclusions**: `src/eaidl/templates` (whitespace-sensitive Jinja2)
- **Pre-commit hooks**:
  - Ruff linter with auto-fix
  - Ruff formatter
  - YAML validation
  - Trailing whitespace removal
  - End-of-file fixer

### Before Committing
Pre-commit hooks will automatically run, but you can manually check:
```bash
# Run all pre-commit hooks
uv run pre-commit run --all-files

# Run ruff linter
uv run ruff check --fix .

# Run ruff formatter
uv run ruff format .
```

## Key Concepts (see STRUCTURE.md for details)

### Most Important Files
- `src/eaidl/load.py` - Database loading & parsing (ModelParser class)
- `src/eaidl/transforms.py` - Model transformations (especially abstract class flattening)
- `src/eaidl/validation/` - Validation framework (decorator-based)
- `src/eaidl/templates/idl/` - Jinja2 templates (whitespace-sensitive!)

### Critical Feature: Abstract Class Flattening
**Location**: `transforms.py::flatten_abstract_classes()`

IDL doesn't support abstract classes. The tool automatically flattens them by copying attributes from abstract parents into concrete children. This is a core transformation - be careful when modifying!

**Configuration**: `flatten_abstract_classes: bool = True` (default)

## Testing

Test database: `tests/data/nafv4.qea` (SQLite EA database used by most tests)

```bash
# Run specific test file
uv run pytest tests/test_transforms.py -v

# Run specific test function
uv run pytest tests/test_load.py::test_specific_function -v
```

## Common Tasks for AI Assistants

### Adding a New Validator
1. Add to `src/eaidl/validation/{struct,attribute,package}.py`
2. Use `@validators_fail`, `@validators_error`, or `@validators_warn` decorator
3. Function signature: `validate_xyz(config, cls, attr=None)`
4. Add test to `tests/test_validators.py`

### Adding a New Transformation
1. Add function to `src/eaidl/transforms.py`
2. Update `generate.py` to call transformation in pipeline
3. Add configuration option to `config.py` if needed
4. Add test to `tests/test_transforms.py`

### Modifying Template Output
1. Templates in `src/eaidl/templates/idl/`
2. Main template: `idl.jinja2`
3. Sub-templates: `gen_struct.jinja2`, `gen_enum.jinja2`, etc.
4. Templates are whitespace-sensitive (excluded from linting)
5. Test changes with `tests/test_templates.py`

### Adding CLI Commands
1. Edit `src/eaidl/cli.py`
2. Use Click decorators
3. Existing commands: run, change, diagram, packages
4. Add to `[project.scripts]` in pyproject.toml if new entry point

## Configuration

Sample configs in `config/` directory:
- `config/sqlite.yaml` - SQLite test database
- `config/postgres.yaml` - PostgreSQL template

Key technologies:
- SQLAlchemy 2.0+ (ORM with automap reflection)
- Pydantic (data validation)
- Jinja2 (templating)
- Click (CLI)
- Ruff (linting/formatting)

## Important Notes

### Template Whitespace
Templates in `src/eaidl/templates/` are whitespace-sensitive and excluded from:
- Ruff formatting
- Pre-commit hooks
- Trailing whitespace removal

**Do not** auto-format these files.

### Python Version
- **Minimum**: Python 3.12
- **Target**: Python 3.13

## Common Pitfalls

1. **Forgetting to run tests before committing**
   - Pre-commit hooks will catch most issues
   - Always run `uv run pytest` for full validation

2. **Modifying templates without testing**
   - IDL output is not whitespace-sensitive
   - Test with `tests/test_templates.py` and `tests/test_generate.py`

3. **Adding validation without considering severity**
   - Use `validators_warn` for non-critical checks
   - Use `validators_fail` for breaking issues only

4. **Breaking abstract class flattening**
   - This is a core transformation (see STRUCTURE.md)
   - Changes require extensive testing with `tests/test_transforms.py`
