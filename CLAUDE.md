# CLAUDE.md - AI Assistant Context

## Project

EA-IDL converts Enterprise Architect database models to IDL format. Standalone CLI tool, runs in CI pipelines.

## Documentation

- **[README.md](./README.md)** - Quick start, installation, usage
- **[STRUCTURE.md](./STRUCTURE.md)** - Architecture, data flow, modules
- **[MODEL.md](./MODEL.md)** - EA modeling conventions, stereotypes, naming
- **[CONTRIBUTING.md](./CONTRIBUTING.md)** - Development workflow, standards, common tasks
- **[scripts/README.md](./scripts/README.md)** - EA diagram export (COM API, Wine setup)

## Quick Reference

### Commands

```bash
uv run pytest                                # Run tests
uv run eaidl run --config config/sqlite.yaml # Generate IDL
uv run eaidl docs --config config/sqlite.yaml --output ./docs  # Generate HTML docs
```

### Key Files

- `src/eaidl/load.py` - Database loading (ModelParser class)
- `src/eaidl/transforms.py` - Transformations (abstract class flattening)
- `src/eaidl/validation/` - Validation framework
- `src/eaidl/html_export.py` - HTML documentation generator
- `tests/data/nafv4.qea` - Test database

### Critical Features

**Abstract Class Flattening** (`transforms.py::flatten_abstract_classes()`)
- IDL doesn't support abstract classes
- Copies attributes from abstract parents to concrete children
- Core transformation - test thoroughly when modifying

**Validators** - Use `@validator` decorator, wraps to accept `**kwargs`
```python
# In tests, use keyword arguments:
v.struct.my_validator(config, cls=my_class)  # ✅ Correct
v.struct.my_validator(config, my_class)       # ❌ Wrong
```

**Templates** - `src/eaidl/templates/` are whitespace-sensitive, excluded from formatting

### Utilities

**Tree Search** (`utils.py`)
```python
from eaidl.utils import find_class, find_class_by_id
cls = find_class(packages, lambda c: c.name == "Message")
cls = find_class_by_id(packages, 123)
```

**Model Helpers** (`model.py`)
```python
namespace = cls.full_name  # "root::data::Message"
if cls.has_stereotype("interface"): ...
if cls.is_enum_type(config): ...
```

### Spellchecking

Implemented in `validation/spellcheck.py`. Enabled by default, warnings only.

```yaml
spellcheck:
  enabled: true
  check_notes: true
  check_identifiers: true
  custom_words: [seq, lobw, hibw, nafv4]
```

## Tech Stack

- SQLAlchemy 2.0+ (ORM with automap)
- Pydantic (validation)
- Jinja2 (templating)
- Click (CLI)
- Ruff (linting/formatting)
- Python 3.12+ (target: 3.13)
