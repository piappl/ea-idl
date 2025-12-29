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
uv run eaidl run          # Generate IDL (default)
uv run eaidl diagram      # Generate PlantUML diagrams
uv run eaidl packages     # List packages
uv run eaidl docs         # Generate interactive HTML documentation
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
- `src/eaidl/templates/idl/` - Jinja2 templates for IDL output (whitespace-sensitive!)
- `src/eaidl/templates/html/` - Jinja2 templates for HTML documentation
- `src/eaidl/html_export.py` - HTML documentation generator
- `src/eaidl/mermaid_diagram.py` - Interactive Mermaid diagram generator
- `src/eaidl/link_utils.py` - Link resolution for HTML documentation

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

## HTML Documentation Export

### Architecture
- **Static site generator**: Creates multi-page HTML with Bootstrap 5 UI
- **Interactive diagrams**: Mermaid.js class diagrams with clickable links
- **Offline-first**: All assets (CSS, JS, fonts) bundled locally
- **Fuzzy search**: Client-side search using Fuse.js (~3KB)
- **Cross-references**: Every type reference is a clickable link

### Key Modules

**`html_export.py`**: Main orchestration
- `export_html()` - Entry point, creates directory structure
- `generate_index_page()` - Landing page with statistics
- `generate_package_pages()` - Package detail + diagram pages
- `generate_class_pages()` - Class/struct/enum detail pages
- `generate_search_index()` - JSON search index
- `copy_assets()` - Copies Bootstrap, Mermaid, Fuse.js

**`mermaid_diagram.py`**: Diagram generation
- `MermaidClassDiagramGenerator` - Generates Mermaid class diagram syntax
- Shows classes, attributes, relationships
- Adds click handlers for navigation
- Handles NAFv4 stereotypes (struct, enum, union, typedef)

**`link_utils.py`**: Link resolution
- `get_relative_path()` - Calculate relative paths between namespaces
- `generate_class_link()` - Generate link to class page
- `generate_package_link()` - Generate link to package page
- `resolve_type_reference()` - Resolve attribute type to link

### Templates

**Base Template** (`templates/html/base.jinja2`):
- Bootstrap 5 layout with sidebar navigation
- Package tree with active highlighting
- Search modal with Fuse.js integration
- Macros: `render_package_tree`, `render_breadcrumbs`, `render_notes`, `render_type_badge`
- **Important**: Macros must be defined BEFORE they're used in the template

**Page Templates**:
- `index.jinja2` - Landing page with model statistics
- `package.jinja2` - Package detail with class table
- `class.jinja2` - Class detail with attributes, relationships, metadata
- `diagram.jinja2` - Interactive Mermaid diagram page

### Assets

Assets are downloaded once via `scripts/download_assets.py` and committed to repo:
- `templates/html/assets/css/bootstrap.min.css` (Bootstrap 5.3.3)
- `templates/html/assets/js/bootstrap.bundle.min.js`
- `templates/html/assets/js/mermaid.min.js` (Mermaid 11)
- `templates/html/assets/js/fuse.min.js` (Fuse.js 7.0)

To update assets:
```bash
python scripts/download_assets.py
```

### CLI Integration

**Command**: `eaidl docs --config config.yaml --output ./_docs`

Options:
- `--config` - Configuration file (required)
- `--output` - Output directory (default: `./docs`)
- `--debug` - Enable debug logging
- `--no-diagrams` - Skip diagram generation (currently not implemented)

The command:
1. Loads EA model via ModelParser
2. Applies transformations (flatten abstract classes, etc.)
3. Calls `export_html()` to generate static site
4. Outputs to specified directory

### EA Diagrams in HTML Export

The HTML export includes both auto-generated class diagrams AND diagrams authored in Enterprise Architect.

**What are EA Diagrams?**
EA diagrams are hand-crafted views created by modelers in Enterprise Architect. They show focused perspectives of the model, often highlighting specific aspects or relationships that are important for understanding the system.

**Data Loading**: EA diagrams are loaded from three database tables:
- `t_diagram` - Diagram metadata (name, type, author, notes)
- `t_diagramobjects` - Object positions (which classes appear on the diagram)
- `t_diagramlinks` - Connector paths (which relationships are shown)

**Rendering**: EA diagrams are converted to Mermaid syntax for consistency with auto-generated diagrams. The converter:
- Only shows objects that appear on the EA diagram (preserves author's intent)
- Converts EA connector types to Mermaid relationship syntax
- Adds click handlers for navigation to class pages
- Handles common diagram types (Class, Custom, Sequence, etc.)

**Display**: Multiple diagrams shown as Bootstrap tabs on diagram page:
- Auto-generated diagram (if package has classes)
- EA diagrams (one tab per diagram)
- Each tab shows diagram metadata (author, notes, type)
- Lazy rendering (only renders active tab for performance)

**Files**:
- `src/eaidl/ea_diagram_converter.py` - Converts EA diagram data to Mermaid
- `src/eaidl/model.py` - Model classes: `ModelDiagram`, `ModelDiagramObject`, `ModelDiagramLink`
- `src/eaidl/load.py` - Database loading methods: `load_package_diagrams()`, `diagram_parse()`
- `src/eaidl/templates/html/diagram.jinja2` - Template with Bootstrap tabs
- `tests/test_diagram_loading.py` - Unit tests for diagram loading and conversion

**Error Handling**: Graceful degradation if conversion fails:
- Logs warning with diagram name and error
- Continues with other diagrams
- Does not break HTML export

### Testing HTML Export

```bash
# Generate docs from test database (includes EA diagrams)
uv run eaidl docs --config config/sqlite.yaml --output /tmp/test-docs

# Open in browser
open /tmp/test-docs/index.html  # macOS
xdg-open /tmp/test-docs/index.html  # Linux
```

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

### Configuring Spellchecking
**Location**: Spellchecking is implemented in `src/eaidl/validation/spellcheck.py` and integrated via validators.

#### Features
- **Enabled by default**: Spellchecks notes/documentation and identifiers
- **Warnings only**: Non-blocking by default (validators_warn)
- **Smart filtering**: Automatically skips technical terms, acronyms, and identifiers
- **Custom dictionary support**: Add project-specific terms

#### Configuration Options
In your YAML config or when creating Configuration:
```yaml
spellcheck:
  enabled: true                    # Enable/disable spellchecking
  check_notes: true                # Check package/class/attribute notes
  check_identifiers: true          # Check class/attribute/package names
  min_word_length: 3               # Minimum word length to check
  custom_words:                    # Project-specific terms to allow
    - seq
    - lobw
    - hibw
    - nafv4
    - myterm
  language: en                     # Language code (default: English)
```

#### Disabling Spellchecking
To disable spellchecking entirely:
```yaml
spellcheck:
  enabled: false
```

Or remove spellcheck validators from validators_warn list:
```yaml
validators_warn:
  - attribute.name_snake_convention
  - struct.notes
  # Remove these to disable spellcheck:
  # - attribute.notes_spelling
  # - attribute.name_spelling
  # - struct.notes_spelling
  # - struct.name_spelling
  # - package.notes_spelling
  # - package.name_spelling
```

#### Adding Custom Terms
Add project-specific terms to your YAML configuration:
```yaml
spellcheck:
  custom_words:
    - seq        # abbreviation for sequence
    - lobw       # low byte word
    - hibw       # high byte word
    - nafv4      # project name
    - myterm     # your custom term
```

Terms are case-insensitive and apply to both notes and identifiers.

#### Built-in Technical Terms
The spellchecker automatically allows:
- IDL keywords: struct, union, enum, typedef, module, etc.
- EA terms: stereotype, connector, cardinality, etc.
- Common abbreviations: uuid, guid, json, xml, http, sql, etc.
- All-caps acronyms (automatically detected)

#### Example Warning Output
```
WARNING: Spelling errors found (in core.message.DataMessage.test_seq:long):
  - 'seq' (suggestions: 'sec', 'sea', 'sew')
```

Add 'seq' to `spellcheck.custom_words` in your config if it's a valid abbreviation.

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
