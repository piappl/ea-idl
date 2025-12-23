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
- `src/eaidl/utils.py` - Shared utilities (find_class, flatten_packages, etc.)
- `tests/conftest.py` - Shared test fixtures and factories

### Critical Feature: Abstract Class Flattening
**Location**: `transforms.py::flatten_abstract_classes()`

IDL doesn't support abstract classes. The tool automatically flattens them by copying attributes from abstract parents into concrete children. This is a core transformation - be careful when modifying!

**Configuration**: `flatten_abstract_classes: bool = True` (default)

### Shared Utilities

**Tree Search** (`src/eaidl/utils.py`):
- `find_class(packages, condition)` - Generic search with condition function
- `find_class_by_id(packages, object_id)` - Find class by ID
- `flatten_packages(packages)` - Flatten package hierarchy to list

Example:
```python
from eaidl.utils import find_class, find_class_by_id

# Find class by condition
cls = find_class(packages, lambda c: c.name == "Message")

# Find class by ID
cls = find_class_by_id(packages, 123)
```

**Model Helpers** (`src/eaidl/model.py`):

Use these properties/methods instead of manual checks:
```python
# Get fully qualified name
namespace = cls.full_name  # "root::data::Message"

# Check stereotypes
if cls.has_stereotype("interface"):
    ...

# Type checking
if cls.is_enum_type(config):
    ...
if cls.is_struct_type(config):
    ...
```

## Testing

Test database: `tests/data/nafv4.qea` (SQLite EA database used by most tests)

### Running Tests
```bash
# Run specific test file
uv run pytest tests/test_transforms.py -v

# Run specific test function
uv run pytest tests/test_load.py::test_specific_function -v

# Check coverage
uv run pytest --cov=src/eaidl --cov-report=term-missing
```

### Writing Tests

Use shared fixtures from `tests/conftest.py` instead of creating objects manually:

```python
def test_my_feature(struct_class, create_attribute, create_package):
    """Use factory fixtures to create test objects."""
    # Create a struct with attributes
    cls = struct_class(
        name="MyStruct",
        attributes=[
            create_attribute(name="field1", type="string"),
            create_attribute(name="field2", type="int"),
        ]
    )

    # Create a package
    pkg = create_package(name="test_pkg", classes=[cls])
```

**Available fixtures:**
- `test_config` - Pre-configured Configuration object
- `struct_class()` - Factory for creating struct classes
- `enum_class()` - Factory for creating enum classes
- `typedef_class()` - Factory for creating typedef classes
- `union_class()` - Factory for creating union classes
- `create_package()` - Factory for creating packages
- `create_attribute()` - Factory for creating attributes

## Common Tasks for AI Assistants

### Adding a New Validator
1. Add to `src/eaidl/validation/{struct,attribute,package}.py`
2. Use `@validator` decorator (configured via `validators_fail`, `validators_error`, or `validators_warn` in config)
3. Write function with signature: `validate_xyz(config: Configuration, cls: ModelClass)` for struct validators, or `validate_xyz(config: Configuration, attribute: ModelAttribute, cls: ModelClass)` for attribute validators
4. Add test to `tests/test_validators.py`

**Important**: The `@validator` decorator wraps your function and changes it to accept `**kwargs`, so when calling validators in tests, use keyword arguments:

```python
# Example struct validator
@validator
def my_struct_validator(config: Configuration, cls: ModelClass):
    if some_condition:
        raise ValueError("Validation failed")

# Call in tests with keyword arguments
v.struct.my_struct_validator(config, cls=my_class)

# Example attribute validator
@validator
def my_attr_validator(config: Configuration, attribute: ModelAttribute, cls: ModelClass):
    if attribute.name == "forbidden":
        raise ValueError("Bad name")

# Call in tests with keyword arguments
v.attribute.my_attr_validator(config, attribute=my_attr, cls=my_class)
```

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
2. Use the `@setup_command` decorator to handle common setup (logging, config loading, version)
3. Use Click decorators for command definition
4. Add to `[project.scripts]` in pyproject.toml if new entry point

Example:
```python
from eaidl.load import ModelParser

@click.command()
@click.option("--config", default="config.yaml", help="Configuration file.")
@click.option("--debug", default=False, is_flag=True, help="Enable debug.")
@click.option("--version", is_flag=True, help="Show version.")
@setup_command
def my_command(config_obj, debug):
    """My new command - config_obj is already loaded."""
    parser = ModelParser(config_obj)
    # ... your logic here
```

Existing commands: run, change, diagram, packages

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
