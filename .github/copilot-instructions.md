# EA-IDL Copilot Instructions

EA-IDL converts Sparx Enterprise Architect database models (.qea SQLite or PostgreSQL) to IDL format.

## Development Commands

```bash
uv run pytest                                            # run test suite
uv run pytest tests/test_transforms.py -v               # run specific test
uv run pytest --cov=src/eaidl                           # with coverage
uv run eaidl run --config config/sqlite.yaml            # generate IDL
uv run eaidl docs --config config/sqlite.yaml --output ./docs  # HTML docs
uv run pre-commit run --all-files                        # lint + format check
```

Test database: `tests/data/nafv4.qea`

## Architecture & Data Flow

```
QEA (.qea)
  → SQLAlchemy automap (load.py)
  → ModelParser.load() → List[ModelPackage]
  → Validators (validation/struct|attribute|package.py)
  → Transforms (transforms.py: flatten_abstract, filter_empty_unions, etc.)
  → Jinja2 templates (templates/idl/)
  → IDL output
```

**Diagram sub-pipeline** (for `eaidl docs`):
```
ModelDiagram (in ModelPackage.diagrams)
  → EADiagramBuilder.build()
  → ClassDiagramDescription | SequenceDiagramDescription
  → MermaidRenderer | PlantUMLRenderer
  → text (Mermaid) | SVG (PlantUML)
```

**Native diagram export pipeline** (for `eaidl export-diagrams`):
```
QEA → NativeDiagramExtractor (native_diagram_extractor.py)
  → decode objectstyle / geometry / path strings
  → NativeDiagram (native_diagram_model.py) — positions, styles, waypoints, labels
  → YAML / JSON (portable AST for downstream renderers: SVG, Excalidraw, DrawIO…)
```

These two pipelines are independent.  The native pipeline reads every object that
appears on the canvas regardless of `config.root_packages`.

## Key Files

| File | Purpose |
|------|---------|
| `src/eaidl/load.py` | SQLAlchemy reflection, `ModelParser` class, all DB queries |
| `src/eaidl/model.py` | Pydantic model classes (`ModelPackage`, `ModelClass`, `ModelAttribute`, `ModelDiagram`, …) |
| `src/eaidl/config.py` | Config schema (Pydantic) |
| `src/eaidl/transforms.py` | Model transformations (`flatten_abstract_classes`, `filter_empty_unions`, …) |
| `src/eaidl/validation/` | Validator framework |
| `src/eaidl/ea_diagram_builder.py` | Converts `ModelDiagram` → renderer-agnostic descriptions |
| `src/eaidl/diagram_model.py` | `ClassDiagramDescription`, `SequenceDiagramDescription` data classes |
| `src/eaidl/renderers/` | `MermaidRenderer`, `PlantUMLRenderer` |
| `src/eaidl/native_diagram_model.py` | `NativeDiagram` Pydantic model — fully-decoded EA layout AST |
| `src/eaidl/native_diagram_extractor.py` | Reads DB → decodes `objectstyle` / `geometry` / `path` → `NativeDiagram` |
| `src/eaidl/templates/` | Jinja2 templates — **do not auto-format** (whitespace-sensitive) |

## Tree Utilities (prefer over custom recursion)

```python
from eaidl.tree_utils import find_class, find_class_by_id, traverse_packages

cls = find_class(packages, lambda c: c.name == "Message")
traverse_packages(packages, class_visitor=my_function)
```

## Validator Pattern

All validators use `@validator` decorator and **must accept `**kwargs`**:

```python
from eaidl.validation.base import validator
from eaidl.config import Configuration
from eaidl.model import ModelClass

@validator
def my_validator(config: Configuration, cls: ModelClass):
    if cls.name.startswith("_"):
        raise ValueError("Names cannot start with underscore")
```

Validators are enabled per-config entry (`validators_fail` / `validators_error` / `validators_warn` / `validators_inform`).
In tests always use keyword arguments: `v.struct.my_validator(config, cls=my_class)`.

## Adding Things

- **Validator** → `src/eaidl/validation/{struct,attribute,package}.py` + test in `tests/test_validators.py`
- **Transformation** → `src/eaidl/transforms.py`, call from `generate.py`
- **CLI command** → `src/eaidl/cli.py`, use `@setup_command` decorator
- **Config option** → `src/eaidl/config.py` (Pydantic model)

## EA Database Notes

- QEA files are SQLite. Main tables: `t_package`, `t_object`, `t_attribute`, `t_connector`, `t_xref`, `t_diagram`, `t_diagramobjects`, `t_diagramlinks`
- `ModelParser` uses SQLAlchemy `automap_base()` with column reflection; columns normalized to lowercase via `attr_<name>` key prefix
- Abstract classes: `t_object.Abstract = '1'` → `ModelClass.is_abstract`; flattened by `flatten_abstract_classes()` before IDL output
- `stereotype` field drives IDL type mapping (struct/enum/union/typedef/map) via `config.stereotypes`

Read CLAUDE.md.
