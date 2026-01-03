# EA-IDL Code Structure

## Overview
ea-idl is a tool that converts Enterprise Architect (EA) database models into IDL (Interface Definition Language) format. It reads EA database files (.qea SQLite or PostgreSQL) and generates IDL output with validation, transformation, and templating capabilities.

## Main Data Flow
```
EA Database (.qea)
  → SQLAlchemy ORM (automap reflection)
  → ModelParser.load()
  → Python Model Objects (ModelPackage, ModelClass, ModelAttribute)
  → Validators (struct, attribute, package)
  → Transforms (filters, maps, unused classes)
  → Jinja2 Templates
  → IDL Output
```

## Directory Structure
```
src/eaidl/
├── cli.py                      - Command-line interface (run, change, diagram, packages, docs)
├── load.py                     - Database loading & parsing (ModelParser class)
├── model.py                    - Pydantic data models (ModelClass, ModelPackage, etc.)
├── generate.py                 - IDL generation orchestration
├── config.py                   - Configuration schema (YAML/JSON)
├── transforms.py               - Model transformations & filtering
├── sorting.py                  - Topological sorting (dependency resolution)
├── recursion.py                - Cycle detection and forward declarations
├── utils.py                    - Utility functions
├── diagram.py                  - PlantUML diagram generation
├── html_export.py              - HTML documentation generator
├── html_utils.py               - HTML formatting utilities
├── mermaid_diagram.py          - Mermaid class diagram generator
├── mermaid_utils.py            - Mermaid syntax utilities
├── link_utils.py               - Link resolution for HTML cross-references
├── ea_diagram_converter.py     - EA diagram to Mermaid converter
├── json_schema_importer.py     - JSON Schema to EA model importer
├── change.py                   - Database modification utilities
├── validation/                 - Validation framework
│   ├── base.py                - Validator decorator & reserved names
│   ├── struct.py              - Class-level validations
│   ├── attribute.py           - Attribute-level validations
│   ├── package.py             - Package-level validations
│   └── spellcheck.py          - Spellchecking for notes and identifiers
└── templates/                  - Jinja2 templates
    ├── idl/                   - IDL output templates
    │   ├── idl.jinja2        - Main template
    │   └── gen_*.jinja2      - Sub-templates (struct, enum, union, etc.)
    └── html/                  - HTML documentation templates
        ├── base.jinja2       - Base layout with navigation
        ├── index.jinja2      - Landing page
        ├── package.jinja2    - Package detail page
        ├── class.jinja2      - Class detail page
        ├── diagram.jinja2    - Interactive diagram page
        └── assets/           - CSS/JS (Bootstrap, Mermaid, Fuse.js)
```

## Core Components

### 1. Database Layer (load.py)
- Uses SQLAlchemy with automap_base() for reflection-based ORM
- Supports both SQLite (.qea) and PostgreSQL databases
- Main EA tables: t_package, t_object, t_attribute, t_connector, t_xref
- Column names normalized to lowercase for cross-database compatibility

### 2. Data Models (model.py)
Key classes:
- **ModelPackage**: Represents IDL modules with nested packages
- **ModelClass**: Represents structs, enums, unions, typedefs, maps
  - Fields: name, object_id, is_abstract, attributes, stereotypes, generalization, etc.
- **ModelAttribute**: Represents class members/fields
- **ModelConnection**: Represents associations between classes
- **ModelAnnotation**: Represents IDL annotations (constraints, metadata)

### 3. Model Parser (load.py - ModelParser class)
Main method: `load()` returns List[ModelPackage]

Process:
1. Creates 'ext' package for annotations
2. Queries root packages by name or GUID
3. Recursively parses packages via package_parse()
4. For each package:
   - Parses child packages
   - Parses classes (class_parse method)
   - Parses attributes (attribute_parse method)
   - Handles connections (Association, Generalization)
5. Topologically sorts classes and packages
6. Processes special connectors (<<union>>, <<values>>)

### 4. Validation Framework (validation/)
Decorator-based validation with severity levels:
- `validators_fail`: Fail generation (default)
- `validators_error`: Log as error
- `validators_warn`: Log as warning

Usage: `validation.base.run("struct", config, cls=model_class)`

Common validators:
- Name validation (reserved words, naming conventions)
- Stereotype validation
- Connector/type validation
- Optional field validation
- Experimental feature flags

### 5. Transformations (transforms.py)
Key functions:
- `flatten_abstract_classes()`: Flattens abstract base classes by copying their attributes to concrete children
- `convert_map_stereotype()`: Detects map patterns
- `filter_stereotypes()`: Removes classes/attributes by stereotype
- `filter_empty_unions()`: Removes/simplifies empty unions
- `find_unused_classes()`: Identifies unreferenced classes
- `filter_unused_classes()`: Removes unused classes
- Topological sorting for dependency resolution

#### Abstract Class Handling
The `flatten_abstract_classes()` transformation implements automatic flattening of abstract base classes:

**Why?** IDL doesn't have a direct concept of abstract classes. Abstract classes are modeling constructs used to share common attributes across multiple concrete types.

**What it does:**
1. Identifies all abstract classes (where `is_abstract == True`)
2. For each concrete class inheriting from an abstract class:
   - Recursively collects attributes from the entire abstract parent chain
   - Copies those attributes into the concrete class
   - Removes the generalization link (parent won't exist in output)
   - Adds parent to `depends_on` for proper ordering
3. Removes all abstract classes from the model
4. Validates that no abstract classes are used as attribute types (error condition)
5. Detects attribute name conflicts between parent and child (error condition)

**Example:**
```python
# Input model:
AbstractMessageHeader (abstract)
  └─ timestamp: Time

MessageHeader (concrete)
  └ inherits from AbstractMessageHeader
  └─ message_type: MessageTypeEnum

# After flattening:
MessageHeader (concrete)
  ├─ timestamp: Time        (flattened from abstract parent)
  └─ message_type: MessageTypeEnum
```

**Configuration:**
- `flatten_abstract_classes: bool = True` (default, enabled)
- Set to `False` in config to disable flattening

### 6. Template System (templates/)
Jinja2-based templating:
- Main: idl.jinja2
- Sub-templates: gen_struct, gen_enum, gen_union, gen_typedef, etc.

Generates IDL with structure:
```idl
module core {
  @annotation myAnnotation { ... };

  module data {
    struct MyStruct { ... };
  };
};
```

### 7. Configuration (config.py)
Key settings:
- `database_url`: DB connection string
- `root_packages`: Packages to process
- `stereotypes`: EA stereotype to IDL type mappings
- `annotations`: EA properties to IDL annotation mappings
- `primitive_types`: Types that don't need resolution
- `enable_maps`, `filter_unused_classes`, etc.

## Important Database Schema Details

### EA Database - Abstract Classes
- Table: `t_object`
- Column: `Abstract` (TEXT)
- Values: '0' (not abstract) or '1' (abstract)
- Already mapped to `ModelClass.is_abstract` field (load.py:650)

### EA Database - Inheritance
- Table: `t_connector`
- Connector_Type: 'Generalization'
- Start_Object_ID → child class
- End_Object_ID → parent class
- Mapped to `ModelClass.generalization` (namespace list)

## CLI Commands
1. **eaidl run**: Generate IDL from database (default)
2. **eaidl change**: Modify EA database
3. **eaidl diagram**: Generate PlantUML diagrams
4. **eaidl packages**: List packages (text/JSON/CSV)
5. **eaidl docs**: Generate HTML documentation

## HTML Documentation Export

### Architecture
Static site generator creating multi-page HTML with Bootstrap 5 UI, Mermaid.js diagrams, and Fuse.js search.

### Key Modules

**html_export.py** - Main orchestration
- `export_html()` - Entry point
- `generate_index_page()` - Landing page with statistics
- `generate_package_pages()` - Package pages with class tables
- `generate_class_pages()` - Class detail pages
- `generate_search_index()` - JSON search index

**mermaid_diagram.py** - Auto-generated class diagrams
- `MermaidClassDiagramGenerator` - Generates diagram syntax
- Shows classes, attributes, relationships
- Adds click handlers for navigation

**ea_diagram_converter.py** - EA-authored diagrams
- Converts diagrams from `t_diagram`, `t_diagramobjects`, `t_diagramlinks`
- Supports class and sequence diagrams
- Preserves diagram author's intent (shows only objects on diagram)

**link_utils.py** - Cross-reference resolution
- `get_relative_path()` - Calculate relative paths between namespaces
- `generate_class_link()` - Generate class page links
- `resolve_type_reference()` - Resolve type to clickable link

### Templates

Location: `templates/html/`

- **base.jinja2** - Layout, navigation, search modal, common macros
- **index.jinja2** - Landing page
- **package.jinja2** - Package detail + class table
- **class.jinja2** - Class detail + attributes + relationships
- **diagram.jinja2** - Interactive diagram with Bootstrap tabs

Assets (Bootstrap 5, Mermaid 11, Fuse.js 7) in `templates/html/assets/`. Update via `scripts/download_assets.py`.

### Usage

```bash
eaidl docs --config config.yaml --output ./docs
```

See README.md for details.

## Key Files
- `src/eaidl/load.py` - Database reading and model construction
- `src/eaidl/model.py` - Data model definitions
- `src/eaidl/transforms.py` - Model manipulation and filtering
- `src/eaidl/validation/` - Validation framework
- `tests/data/nafv4.qea` - Test database file
