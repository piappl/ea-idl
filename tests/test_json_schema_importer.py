"""Tests for JSON schema importer."""

import json
import shutil
from pathlib import Path

import pytest

from eaidl.config import Configuration
from eaidl.json_schema_importer import JsonSchemaImporter
from eaidl.load import ModelParser


@pytest.fixture
def temp_db(tmp_path):
    """Create a temporary copy of the empty database."""
    db_path = tmp_path / "test.qea"
    empty_db = Path("tests/data/empty.qea")
    if empty_db.exists():
        shutil.copy(empty_db, db_path)
    return db_path


@pytest.fixture
def config(temp_db):
    """Create configuration with temporary database."""
    return Configuration(
        database_url=f"sqlite:///{temp_db}",
        root_packages=["imported_schema"],
    )


def test_to_pascal_case():
    """Test PascalCase conversion."""
    importer = JsonSchemaImporter(Configuration(), "dummy.json", "test")

    assert importer._to_pascal_case("point") == "Point"
    assert importer._to_pascal_case("geometryLiteral") == "GeometryLiteral"
    assert importer._to_pascal_case("geometry_literal") == "GeometryLiteral"
    assert importer._to_pascal_case("multi_line_string") == "MultiLineString"
    assert importer._to_pascal_case("Point") == "Point"  # Already PascalCase


def test_resolve_ref():
    """Test $ref resolution."""
    importer = JsonSchemaImporter(Configuration(), "dummy.json", "test")

    assert importer._resolve_ref("#/$defs/point") == "Point"
    assert importer._resolve_ref("#/$defs/geometryLiteral") == "GeometryLiteral"
    assert importer._resolve_ref("#/$defs/multi_point") == "MultiPoint"


def test_type_mapping():
    """Test JSON schema to IDL type mapping."""
    importer = JsonSchemaImporter(Configuration(), "dummy.json", "test")

    assert importer._resolve_schema_type({"type": "string"}) == "string"
    assert importer._resolve_schema_type({"type": "number"}) == "double"
    assert importer._resolve_schema_type({"type": "integer"}) == "long"
    assert importer._resolve_schema_type({"type": "boolean"}) == "boolean"


def test_ref_type_resolution():
    """Test type resolution with $ref."""
    importer = JsonSchemaImporter(Configuration(), "dummy.json", "test")

    assert importer._resolve_schema_type({"$ref": "#/$defs/point"}) == "Point"
    assert importer._resolve_schema_type({"$ref": "#/$defs/lineString"}) == "LineString"


def test_parse_simple_schema(tmp_path):
    """Test parsing a simple JSON schema."""
    # Create a simple test schema
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$defs": {
            "point": {
                "type": "object",
                "properties": {
                    "x": {"type": "number"},
                    "y": {"type": "number"},
                },
                "required": ["x", "y"],
            }
        },
    }

    schema_file = tmp_path / "simple.json"
    with open(schema_file, "w") as f:
        json.dump(schema, f)

    importer = JsonSchemaImporter(Configuration(), str(schema_file), "test")
    package = importer.parse_schema()

    assert package.name == "test"
    # Classes are in the "types" child package
    types_pkg = package.packages[0]
    assert types_pkg.name == "types"
    assert len(types_pkg.classes) == 1

    point_cls = types_pkg.classes[0]
    assert point_cls.name == "Point"
    assert point_cls.is_struct
    assert len(point_cls.attributes) == 2

    # Check attributes
    attr_names = {attr.name for attr in point_cls.attributes}
    assert "x" in attr_names
    assert "y" in attr_names

    # Check types
    for attr in point_cls.attributes:
        assert attr.type == "double"
        assert not attr.is_optional  # Both are required


def test_parse_enum_schema(tmp_path):
    """Test parsing enum schema."""
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$defs": {
            "status": {
                "type": "string",
                "enum": ["active", "inactive", "pending"],
            }
        },
    }

    schema_file = tmp_path / "enum.json"
    with open(schema_file, "w") as f:
        json.dump(schema, f)

    importer = JsonSchemaImporter(Configuration(), str(schema_file), "test")
    package = importer.parse_schema()

    # Classes are in the "types" child package
    types_pkg = package.packages[0]
    assert len(types_pkg.classes) == 1

    enum_cls = types_pkg.classes[0]
    assert enum_cls.name == "StatusEnum"
    assert enum_cls.is_enum
    assert len(enum_cls.attributes) == 3

    # Check enum member names
    member_names = {attr.name for attr in enum_cls.attributes}
    assert "StatusEnum_ACTIVE" in member_names
    assert "StatusEnum_INACTIVE" in member_names
    assert "StatusEnum_PENDING" in member_names


def test_parse_array_schema(tmp_path):
    """Test parsing array schema."""
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$defs": {
            "pointList": {
                "type": "object",
                "properties": {
                    "points": {
                        "type": "array",
                        "items": {"$ref": "#/$defs/point"},
                        "minItems": 1,
                        "maxItems": 10,
                    }
                },
            },
            "point": {
                "type": "object",
                "properties": {"x": {"type": "number"}, "y": {"type": "number"}},
            },
        },
    }

    schema_file = tmp_path / "array.json"
    with open(schema_file, "w") as f:
        json.dump(schema, f)

    importer = JsonSchemaImporter(Configuration(), str(schema_file), "test")
    package = importer.parse_schema()

    # Classes are in the "types" child package
    types_pkg = package.packages[0]

    # Find PointList class
    point_list = next(cls for cls in types_pkg.classes if cls.name == "PointList")
    assert point_list is not None

    # Check array attribute
    points_attr = next(attr for attr in point_list.attributes if attr.name == "points")
    assert points_attr.is_collection
    assert points_attr.type == "Point"

    assert "ext::minItems" in points_attr.properties
    assert "ext::maxItems" in points_attr.properties
    assert points_attr.properties["ext::minItems"].value == 1
    assert points_attr.properties["ext::maxItems"].value == 10


def test_parse_nested_array_schema(tmp_path):
    """Test parsing nested array schema (array of arrays)."""
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$defs": {
            "matrix": {
                "type": "object",
                "properties": {"data": {"type": "array", "items": {"type": "array", "items": {"type": "number"}}}},
            }
        },
    }

    schema_file = tmp_path / "nested.json"
    with open(schema_file, "w") as f:
        json.dump(schema, f)

    importer = JsonSchemaImporter(Configuration(), str(schema_file), "test")
    package = importer.parse_schema()

    # Classes are in the "types" child package
    types_pkg = package.packages[0]

    # Find Matrix class
    matrix_cls = next(cls for cls in types_pkg.classes if cls.name == "Matrix")
    assert matrix_cls is not None

    # Check data attribute
    data_attr = next(attr for attr in matrix_cls.attributes if attr.name == "data")
    assert data_attr.is_collection

    # This should be a typedef name
    typedef_name = "MatrixDataItem"
    assert data_attr.type == typedef_name

    # Verify the typedef exists and is a sequence of double
    typedef_cls = next(cls for cls in types_pkg.classes if cls.name == typedef_name)
    assert typedef_cls.is_typedef
    assert "sequence<double>" in typedef_cls.parent_type


def test_cyclic_array_schema(tmp_path):
    """Test parsing cyclic array schema (Array<T> where T contains Array<T>)."""
    # Define a cyclic schema: Cycle -> Array<Cycle>
    # Note: direct Cycle -> Array<Cycle> is infinite structure in JSON if inline.
    # But using $ref makes it valid cyclic schema.
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$defs": {"cycle": {"type": "array", "items": {"$ref": "#/$defs/cycle"}}},
    }

    schema_file = tmp_path / "cyclic.json"
    with open(schema_file, "w") as f:
        json.dump(schema, f)

    importer = JsonSchemaImporter(Configuration(), str(schema_file), "test")
    # This should not hang/crash
    package = importer.parse_schema()

    # Classes are in the "types" child package
    types_pkg = package.packages[0]

    # Check if "Cycle" class exists (as a typedef)
    cycle_cls = next(cls for cls in types_pkg.classes if cls.name == "Cycle")
    assert cycle_cls.is_typedef

    # It should be a sequence of itself (or intermediate)
    # Since Cycle is an array, it becomes a typedef.
    # _resolve_type_with_intermediates("Cycle") -> items ($ref Cycle) -> "Cycle"
    # So Cycle = sequence<Cycle>.
    # This is valid IDL.
    assert "sequence<Cycle>" in cycle_cls.parent_type


def test_parse_oneof_schema(tmp_path):
    """Test parsing oneOf schema (union)."""
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$defs": {
            "value": {
                "oneOf": [
                    {"type": "string"},
                    {"type": "number"},
                ]
            }
        },
    }

    schema_file = tmp_path / "union.json"
    with open(schema_file, "w") as f:
        json.dump(schema, f)

    importer = JsonSchemaImporter(Configuration(), str(schema_file), "test")
    package = importer.parse_schema()

    # Classes are in the "types" child package
    types_pkg = package.packages[0]

    # Should create union class and discriminator enum
    assert len(types_pkg.classes) == 2

    # Find union and enum
    union_cls = next(cls for cls in types_pkg.classes if cls.name == "Value")
    enum_cls = next(cls for cls in types_pkg.classes if cls.name == "ValueTypeEnum")

    assert union_cls.is_union
    assert enum_cls.is_enum

    # Check union members
    assert len(union_cls.attributes) == 2

    # Check discriminator enum
    assert len(enum_cls.attributes) == 2


def test_optional_properties(tmp_path):
    """Test optional vs required properties."""
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$defs": {
            "person": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "age": {"type": "integer"},
                    "email": {"type": "string"},
                },
                "required": ["name"],
            }
        },
    }

    schema_file = tmp_path / "optional.json"
    with open(schema_file, "w") as f:
        json.dump(schema, f)

    importer = JsonSchemaImporter(Configuration(), str(schema_file), "test")
    package = importer.parse_schema()

    # Classes are in the "types" child package
    types_pkg = package.packages[0]

    person_cls = types_pkg.classes[0]

    # Check required property
    name_attr = next(attr for attr in person_cls.attributes if attr.name == "name")
    assert not name_attr.is_optional
    assert "optional" not in name_attr.stereotypes

    # Check optional properties
    age_attr = next(attr for attr in person_cls.attributes if attr.name == "age")
    assert age_attr.is_optional
    assert "optional" in age_attr.stereotypes

    email_attr = next(attr for attr in person_cls.attributes if attr.name == "email")
    assert email_attr.is_optional


def test_constraints_as_annotations(tmp_path):
    """Test JSON schema constraints map to IDL annotations."""
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$defs": {
            "measurement": {
                "type": "object",
                "properties": {
                    "value": {
                        "type": "number",
                        "minimum": 0,
                        "maximum": 100,
                    },
                    "name": {
                        "type": "string",
                        "pattern": "^[a-zA-Z]+$",
                    },
                },
            }
        },
    }

    schema_file = tmp_path / "constraints.json"
    with open(schema_file, "w") as f:
        json.dump(schema, f)

    importer = JsonSchemaImporter(Configuration(), str(schema_file), "test")
    package = importer.parse_schema()

    # Classes are in the "types" child package
    types_pkg = package.packages[0]

    measurement_cls = types_pkg.classes[0]

    # Check numeric constraints
    value_attr = next(attr for attr in measurement_cls.attributes if attr.name == "value")
    assert "min" in value_attr.properties
    assert "max" in value_attr.properties
    assert value_attr.properties["min"].value == 0
    assert value_attr.properties["max"].value == 100

    # Check pattern constraint
    name_attr = next(attr for attr in measurement_cls.attributes if attr.name == "name")
    assert "pattern" in name_attr.properties
    assert name_attr.properties["pattern"].value == "^[a-zA-Z]+$"


def test_database_import(config, tmp_path):
    """Test importing schema to database."""
    # Create simple schema
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$defs": {
            "point": {
                "type": "object",
                "properties": {
                    "x": {"type": "number"},
                    "y": {"type": "number"},
                },
            }
        },
    }

    schema_file = tmp_path / "db_test.json"
    with open(schema_file, "w") as f:
        json.dump(schema, f)

    # Import to database
    importer = JsonSchemaImporter(config, str(schema_file), "imported_schema")
    package = importer.parse_schema()
    importer.import_to_database(package)

    # Create new config that points to the imported package
    import_config = Configuration(
        database_url=config.database_url,
        root_packages=["imported_schema"],
    )

    # Verify by loading from database
    parser = ModelParser(import_config)
    loaded = parser.load()

    assert len(loaded) > 0

    # Find the imported package by name
    imported_pkg = next((pkg for pkg in loaded if pkg.name == "imported_schema"), None)
    assert imported_pkg is not None, f"Could not find 'imported_schema' package in {[pkg.name for pkg in loaded]}"

    # Checks for child package "types"
    types_pkg = next((pkg for pkg in imported_pkg.packages if pkg.name == "types"), None)
    assert types_pkg is not None
    assert len(types_pkg.classes) >= 1

    # Find Point class
    point_cls = next((cls for cls in types_pkg.classes if cls.name == "Point"), None)
    assert point_cls is not None
    assert point_cls.is_struct
    assert len(point_cls.attributes) == 2


def test_cql2_import(config):
    """Test importing actual CQL2 schema.

    This test verifies that complex schemas with circular references can be parsed correctly.
    Database import is skipped as it's slow and tested in test_database_import.
    """
    cql2_file = Path("tests/data/cql2.json")

    if not cql2_file.exists():
        pytest.skip("CQL2 test file not found")

    importer = JsonSchemaImporter(config, str(cql2_file), "cql2")
    package = importer.parse_schema()

    # Classes are in the "types" child package
    types_pkg = package.packages[0]

    # Should create many classes (cql2 has 50 definitions which create ~108 classes with unions/enums)
    assert len(types_pkg.classes) > 50, f"Expected > 50 classes, got {len(types_pkg.classes)}"

    # Verify some expected types exist
    class_names = {cls.name for cls in types_pkg.classes}

    # Check for some GeoJSON types that should be in cql2
    assert "Point" in class_names or "point" in {cls.name.lower() for cls in types_pkg.classes}

    # Verify circular reference handling worked (FunctionRef references itself via args array)
    assert "FunctionRef" in class_names, "FunctionRef should be created despite circular references"

    # Note: Database import test is in test_database_import - skipping here for speed
