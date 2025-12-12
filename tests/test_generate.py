import re
import tempfile
from pathlib import Path
from eaidl.generate import generate
from eaidl.load import ModelParser
from eaidl.utils import Configuration
from idl_parser.parser import IDLParser


def test_generate() -> None:
    path = Path(__file__).parent / "data" / "nafv4.qea"
    config = Configuration()
    config.database_url = f"sqlite+pysqlite:///{path.as_posix()}"
    config.root_packages = ["{753A4DFC-7876-4b00-BB5A-6274AD3817C3}"]
    config.filter_stereotypes = ["lobw"]
    config.output_linked_notes = True
    config.output_unlinked_notes = True
    parser = ModelParser(config)
    with (Path(__file__).parent / "data" / "nafv4.idl").open("w") as output:
        output.write(generate(config, parser.load()))


def test_generate_just_defs() -> None:
    path = Path(__file__).parent / "data" / "nafv4.qea"
    config = Configuration()
    config.database_url = f"sqlite+pysqlite:///{path.as_posix()}"
    config.root_packages = ["{753A4DFC-7876-4b00-BB5A-6274AD3817C3}"]
    config.template = "idl_just_defs.jinja2"
    config.filter_stereotypes = ["hibw"]
    config.output_linked_notes = True
    config.output_unlinked_notes = True
    parser = ModelParser(config)
    with (Path(__file__).parent / "data" / "nafv4_just_defs.idl").open("w") as output:
        output.write(generate(config, parser.load()))


def test_idl_templates_consistency() -> None:
    """Test that both IDL templates produce consistent attribute types for the same model."""
    path = Path(__file__).parent / "data" / "nafv4.qea"

    # Generate with standard idl template
    config1 = Configuration()
    config1.database_url = f"sqlite+pysqlite:///{path.as_posix()}"
    config1.root_packages = ["{753A4DFC-7876-4b00-BB5A-6274AD3817C3}"]
    config1.filter_stereotypes = ["hibw"]  # Use same filter for fair comparison
    parser1 = ModelParser(config1)
    idl_output = generate(config1, parser1.load())

    # Generate with idl_just_defs template
    config2 = Configuration()
    config2.database_url = f"sqlite+pysqlite:///{path.as_posix()}"
    config2.root_packages = ["{753A4DFC-7876-4b00-BB5A-6274AD3817C3}"]
    config2.template = "idl_just_defs.jinja2"
    config2.filter_stereotypes = ["hibw"]  # Use same filter for fair comparison
    parser2 = ModelParser(config2)
    idl_just_defs_output = generate(config2, parser2.load())

    # Extract struct definitions from both outputs
    def extract_struct_attributes(idl_text: str, struct_name: str) -> dict[str, str]:
        """Extract attribute name -> type mapping from a struct definition."""
        # Find the struct definition (not just the forward declaration)
        # Pattern handles: struct Name { ... }; and struct Name: Parent { ... };
        struct_pattern = rf"struct {struct_name}[^;{{]*\{{([^}}]*)\}};"

        # Find all matches (to skip forward declarations like "struct Name;")
        for match in re.finditer(struct_pattern, idl_text, re.DOTALL):
            struct_body = match.group(1)
            # Skip empty bodies (forward declarations might match)
            if not struct_body.strip():
                continue

            attributes = {}
            # Extract attribute declarations (handle both simple types and sequences/maps)
            # Patterns: sequence<type, N> name; or sequence<type> name; or type name;
            attr_pattern = r"\s+((?:sequence<[^>]+>|map<[^>]+>|[\w:]+))\s+(\w+);"
            for attr_match in re.finditer(attr_pattern, struct_body):
                attr_type = attr_match.group(1).strip()
                attr_name = attr_match.group(2).strip()
                attributes[attr_name] = attr_type

            # Return the first non-empty match
            if attributes:
                return attributes

        return {}

    # Test DataMessage struct
    struct_name = "DataMessage"
    attrs_idl = extract_struct_attributes(idl_output, struct_name)
    attrs_just_defs = extract_struct_attributes(idl_just_defs_output, struct_name)

    # Both should have the same attributes
    assert set(attrs_idl.keys()) == set(attrs_just_defs.keys()), (
        f"Attribute names differ between templates for {struct_name}:\n"
        f"idl: {sorted(attrs_idl.keys())}\n"
        f"idl_just_defs: {sorted(attrs_just_defs.keys())}"
    )

    # Types should be consistent (allowing for different but semantically equivalent types)
    for attr_name in attrs_idl:
        type_idl = attrs_idl[attr_name]
        type_just_defs = attrs_just_defs[attr_name]

        # Normalize types for comparison (remove whitespace variations)
        type_idl_norm = re.sub(r"\s+", "", type_idl)
        type_just_defs_norm = re.sub(r"\s+", "", type_just_defs)

        assert type_idl_norm == type_just_defs_norm, (
            f"Type mismatch for {struct_name}.{attr_name}:\n"
            f"  idl template:           {type_idl}\n"
            f"  idl_just_defs template: {type_just_defs}"
        )


def test_validate_idl_syntax() -> None:
    """Validate generated IDL files with external IDL parser.

    This test ensures that generated IDL files are syntactically correct
    and can be parsed by a standard OMG IDL parser. This catches issues like:
    - Syntax errors
    - Invalid type references
    - Malformed declarations
    - Template rendering bugs
    """
    test_data_dir = Path(__file__).parent / "data"
    idl_files = [
        test_data_dir / "nafv4.idl",
        test_data_dir / "nafv4_just_defs.idl",
    ]

    parser = IDLParser()
    errors = []

    for idl_file in idl_files:
        if not idl_file.exists():
            errors.append(f"{idl_file.name}: File not found (run test_generate* first)")
            continue

        try:
            # Parse the IDL file
            result = parser.load(str(idl_file))

            # Basic validation: result should be an IDLModule
            assert result is not None, f"{idl_file.name}: Parser returned None"
            assert hasattr(result, "name"), f"{idl_file.name}: Invalid parser result (missing 'name' attribute)"

        except Exception as e:
            errors.append(f"{idl_file.name}: {e}")

    # Report all errors at once for better visibility
    if errors:
        error_msg = "\n".join(f"  - {err}" for err in errors)
        raise AssertionError(f"IDL validation failed:\n{error_msg}")


def test_validate_generated_idl_on_the_fly() -> None:
    """Generate IDL and validate it in a single test.

    This test generates IDL from the database and immediately validates it,
    ensuring that any changes to templates or transformations produce valid IDL.
    """
    path = Path(__file__).parent / "data" / "nafv4.qea"

    # Test both templates
    test_configs = [
        ("idl.jinja2", ["lobw"]),
        ("idl_just_defs.jinja2", ["hibw"]),
    ]

    parser_instance = IDLParser()
    errors = []

    for template_name, filter_stereotypes in test_configs:
        config = Configuration()
        config.database_url = f"sqlite+pysqlite:///{path.as_posix()}"
        config.root_packages = ["{753A4DFC-7876-4b00-BB5A-6274AD3817C3}"]
        config.template = template_name
        config.filter_stereotypes = filter_stereotypes
        model_parser = ModelParser(config)
        idl_output = generate(config, model_parser.load())

        # Write to temporary file for parsing
        with tempfile.NamedTemporaryFile(mode="w", suffix=".idl", delete=False) as tmp:
            tmp.write(idl_output)
            tmp_path = tmp.name

        try:
            # Parse the generated IDL
            result = parser_instance.load(tmp_path)
            assert result is not None, f"{template_name}: Parser returned None"
        except Exception as e:
            errors.append(f"{template_name} (filter={filter_stereotypes}): {e}")
        finally:
            # Clean up temp file
            Path(tmp_path).unlink(missing_ok=True)

    if errors:
        error_msg = "\n".join(f"  - {err}" for err in errors)
        raise AssertionError(f"Generated IDL validation failed:\n{error_msg}")
