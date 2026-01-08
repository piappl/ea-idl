# CLAUDE.md - AI Assistant Quick Reference

EA-IDL converts Enterprise Architect database models to IDL format. Standalone CLI tool.

## Documentation Index

| File | Purpose |
|------|---------|
| [README.md](./README.md) | Installation, commands, usage |
| [STRUCTURE.md](./STRUCTURE.md) | Architecture, modules, abstract class flattening |
| [MODEL.md](./MODEL.md) | EA modeling conventions, stereotypes |
| [CONTRIBUTING.md](./CONTRIBUTING.md) | Development workflow, validators, testing |
| [scripts/README.md](./scripts/README.md) | Diagram export scripts |

## Essential Info for AI Assistants

**Test database:** `tests/data/nafv4.qea`

**Tree utilities** (use these instead of custom recursion):
```python
from eaidl.tree_utils import find_class, find_class_by_id, traverse_packages
cls = find_class(packages, lambda c: c.name == "Message")
traverse_packages(packages, class_visitor=my_function)
```

**Validators** require `**kwargs` (see [CONTRIBUTING.md](./CONTRIBUTING.md)):
```python
v.struct.my_validator(config, cls=my_class)  # ✅ Correct
```

**Templates** (`src/eaidl/templates/`) are whitespace-sensitive - don't auto-format

**Tech:** SQLAlchemy 2.0+, Pydantic, Jinja2, Click, Ruff, Python 3.12+

**Development:** Use `uv` for all commands (`uv run pytest`, `uv run pre-commit`, `uv run eaidl`, etc.)
