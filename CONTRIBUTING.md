# Contributing to EA-IDL

## Development Setup

```bash
# Sync dependencies including dev tools
uv sync --extra dev

# Install pre-commit hooks
uv run pre-commit install
```

## Code Quality

### Standards

- **Linter/Formatter**: Ruff (config in `pyproject.toml`)
- **Line length**: 120 chars
- **Python version**: 3.12+ (target: 3.13)
- **Exclusions**: `src/eaidl/templates/` (whitespace-sensitive Jinja2 - do not format)

### Before Committing

```bash
uv run pre-commit run --all-files  # Runs ruff, YAML validation, etc.
uv run pytest                      # Run full test suite
```

## Documentation Standards

### Principles

1. **Be brief** - every word must add value
2. **Avoid repetition** - link instead of duplicating
3. **Code over comments** - write self-explanatory code
4. **Comments only when needed** - explain WHY, not WHAT

### Code Documentation

**Docstrings**: Use only for public APIs and complex algorithms. Keep them short.

```python
# ✅ Good - concise, explains non-obvious behavior
def topological_sort(classes: List[ModelClass]) -> List[ModelClass]:
    """Sort classes by dependencies using Tarjan's SCC algorithm."""
    ...

# ❌ Bad - states the obvious
def get_name(self) -> str:
    """Returns the name of the class."""
    return self.name

# ✅ Better - no docstring needed
def get_name(self) -> str:
    return self.name
```

**Inline comments**: Only for non-obvious logic.

```python
# ✅ Good - explains why
# EA uses 1-based indexing, convert to 0-based
index = ea_index - 1

# ❌ Bad - states the obvious
# Subtract 1 from ea_index
index = ea_index - 1
```

**Type hints**: Always use them - they document better than docstrings.

### Project Documentation

- **README.md** - Quick start, installation, basic usage
- **STRUCTURE.md** - Architecture, data flow, module organization
- **MODEL.md** - EA modeling conventions, stereotypes, naming rules
- **CONTRIBUTING.md** (this file) - Development workflow, standards
- **CLAUDE.md** - AI assistant reference (links only, no duplication)

## Testing

Test database: `tests/data/nafv4.qea`

```bash
# Run all tests
uv run pytest

# Run with coverage
uv run pytest --cov=src/eaidl --cov-report=term-missing

# Run specific test
uv run pytest tests/test_transforms.py::test_flatten_abstract -v
```

**Coverage target**: 85%+

## Common Tasks

### Adding a Validator

1. Add function to `src/eaidl/validation/{struct,attribute,package}.py`
2. Use `@validator` decorator
3. Configure severity in config YAML: `validators_fail`, `validators_error`, or `validators_warn`
4. Add test to `tests/test_validators.py`

```python
from eaidl.validation.base import validator

@validator
def my_validator(config: Configuration, cls: ModelClass):
    if cls.name.startswith("_"):
        raise ValueError("Names cannot start with underscore")
```

**Note**: Decorator wraps function to accept `**kwargs`. In tests, use keyword arguments:

```python
v.struct.my_validator(config, cls=my_class)  # Not: v.struct.my_validator(config, my_class)
```

### Adding a Transformation

1. Add function to `src/eaidl/transforms.py`
2. Call from `generate.py` pipeline
3. Add config option to `config.py` if needed
4. Add test to `tests/test_transforms.py`

### Modifying IDL Templates

Templates in `src/eaidl/templates/idl/` are whitespace-sensitive. Do NOT auto-format.

1. Edit template (careful with whitespace)
2. Test with `uv run pytest tests/test_templates.py tests/test_generate.py`

### Adding CLI Command

1. Add command function to `src/eaidl/cli.py`
2. Use `@setup_command` decorator for common setup (logging, config, version)
3. Update `[project.scripts]` in `pyproject.toml` if needed

## Important Notes

### Template Whitespace

Templates in `src/eaidl/templates/` are excluded from:
- Ruff formatting
- Pre-commit hooks
- Trailing whitespace removal

Do NOT auto-format these files.

## Common Pitfalls

1. **Running tests** - Pre-commit hooks run automatically, but always `uv run pytest` before pushing
2. **Template modifications** - Templates are whitespace-sensitive. Test thoroughly.
3. **Validator severity** - Use `validators_warn` for non-critical checks, `validators_fail` only for breaking issues
4. **Abstract class handling** - Test with `tests/test_transforms.py` when modifying inheritance logic
