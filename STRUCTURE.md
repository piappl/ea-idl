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
├── cli.py              - Command-line interface (run, change, diagram, packages)
├── load.py             - Database loading & parsing (ModelParser class)
├── model.py            - Pydantic data models (ModelClass, ModelPackage, etc.)
├── generate.py         - IDL generation orchestration
├── config.py           - Configuration schema (YAML/JSON)
├── transforms.py       - Model transformations & filtering
├── sorting.py          - Topological sorting (dependency resolution)
├── utils.py            - Utility functions
├── validation/         - Validation framework
│   ├── base.py        - Validator decorator & reserved names
│   ├── struct.py      - Class-level validations
│   ├── attribute.py   - Attribute-level validations
│   └── package.py     - Package-level validations
└── templates/          - Jinja2 templates for IDL output
    ├── idl.jinja2     - Main template
    └── idl/           - Sub-templates (struct, enum, union, etc.)
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
- `convert_map_stereotype()`: Detects map patterns
- `filter_stereotypes()`: Removes classes/attributes by stereotype
- `filter_empty_unions()`: Removes/simplifies empty unions
- `find_unused_classes()`: Identifies unreferenced classes
- `filter_unused_classes()`: Removes unused classes
- Topological sorting for dependency resolution

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

## Key Files to Know
- `src/eaidl/load.py` - Database reading and model construction
- `src/eaidl/model.py` - Data model definitions
- `src/eaidl/transforms.py` - Model manipulation and filtering
- `src/eaidl/templates/idl/gen_struct.jinja2` - Struct output template
- `src/eaidl/validation/attribute.py` - Attribute-level validation
- `tests/data/nafv4.qea` - Test database file
