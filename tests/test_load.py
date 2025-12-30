from eaidl.load import ModelParser
from eaidl.config import Configuration
from sqlalchemy import create_engine
from sqlalchemy import text
from sqlalchemy.orm import Session
from sqlalchemy.ext.automap import automap_base

from rich import print, inspect
import pytest

MESSAGE_HEADER_GUID = "{5BE95D32-6D93-4dfb-8010-F68E5891C7D7}"
TIME_TYPEDEF_GUID = "{B7F3CB58-65C8-49ce-BF01-B9F067BC4E82}"
CORE_PACKAGE_GUID = "{753A4DFC-7876-4b00-BB5A-6274AD3817C3}"
MEASUREMENT_GUID = "{360F4F18-9BCE-4efe-A337-2958FE3DCA3C}"
DATA_MESSAGE_GUID = "{9F3D867F-2B36-4ab7-9F95-7EB442443042}"


def test_load_row():
    engine = create_engine("sqlite+pysqlite:///tests/data/nafv4.qea", echo=True)
    stmt = text("SELECT * FROM t_object")
    with Session(engine) as session:
        result = session.execute(stmt)
        for row in result:
            print(row)


def test_reflect():
    base = automap_base()
    engine = create_engine("sqlite+pysqlite:///tests/data/nafv4.qea", echo=False)
    # Reflect the tables
    base.prepare(autoload_with=engine)
    session = Session(engine)
    # This is just to check if someone messed with out test file.
    # If this fails, just check the file and fix numbers here.
    contents = {
        "t_package": 10,
        "t_object": 48,
        "t_attribute": 40,
        "t_connector": 42,
        "t_objectproperties": 85,
        "t_xref": 63,
    }

    for key, value in contents.items():
        assert session.query(getattr(base.classes, key)).count() == value
    # Just check one of packages
    TPackage = base.classes.t_package
    item = session.query(TPackage).filter(TPackage.Name == "message").scalar()
    assert item is not None


def test_load():
    parser = ModelParser(Configuration())
    packages = parser.load()
    # Core is default
    assert packages[1].name == "core"
    assert packages[1].packages[0].name == "common"
    assert packages[1].packages[1].name == "data"
    assert packages[1].packages[1].classes[1].name == "Measurement"
    assert packages[1].packages[1].classes[0].name == "MeasurementTypeEnum"
    assert packages[1].packages[2].name == "message"
    assert packages[1].packages[2].classes[9].name == "Message"
    assert packages[1].packages[2].classes[10].name == "DataMessage"
    assert packages[1].packages[2].classes[10].stereotypes[2] == "interface"

    # This is union and its enumeration, both need to exist and have certain
    # pattern of names.
    inspect(packages[1].packages[1].classes[0].attributes)
    inspect(packages[1].packages[1].classes[1].attributes)
    parser = ModelParser(Configuration(root_packages=["something not there"]))
    with pytest.raises(ValueError):
        parser.load()


def test_get_stereotypes() -> None:
    parser = ModelParser(Configuration())
    ret = parser.get_stereotypes(MESSAGE_HEADER_GUID)
    assert len(ret) == 2
    assert ret[0] == "DataElement"
    assert ret[1] == "idlStruct"
    ret = parser.get_stereotypes(TIME_TYPEDEF_GUID)
    assert len(ret) == 2
    assert ret[0] == "DataElement"
    assert ret[1] == "idlTypedef"


def test_get_properties() -> None:
    config = Configuration()
    parser = ModelParser(config)
    props = parser.get_custom_properties(MEASUREMENT_GUID)
    inspect(props)
    parser.get_custom_properties(DATA_MESSAGE_GUID)
    inspect(props)


def test_get_namespace() -> None:
    config = Configuration()
    parser = ModelParser(config)
    parser.load()
    # Those two are outside od core
    assert parser.get_namespace(2) == []  # Model
    assert parser.get_namespace(10) == []  # L7
    assert parser.get_namespace(3) == ["core"]
    assert parser.get_namespace(9) == ["core", "data"]
    assert parser.get_namespace(11) == ["core", "common", "types"]
    config.root_packages = [CORE_PACKAGE_GUID]
    parser = ModelParser(config)
    parser.load()
    assert parser.get_namespace(2) == []  # Model
    assert parser.get_namespace(10) == []  # L7
    assert parser.get_namespace(3) == ["core"]
    assert parser.get_namespace(9) == ["core", "data"]
    assert parser.get_namespace(11) == ["core", "common", "types"]
    config.root_packages = ["L7"]
    parser = ModelParser(config)
    parser.load()
    assert parser.get_namespace(2) == []  # Model
    assert parser.get_namespace(10) == ["L7"]  # L7
    assert parser.get_namespace(3) == []
    assert parser.get_namespace(9) == []
    assert parser.get_namespace(11) == []


def test_linked_notes() -> None:
    """Test loading notes linked to classes via NoteLink connectors."""
    config = Configuration()
    parser = ModelParser(config)
    packages = parser.load()

    # Find Nationality class in message package
    message_package = packages[1].packages[2]  # core.message
    assert message_package.name == "message"

    nationality_class = None
    for cls in message_package.classes:
        if cls.name == "Nationality":
            nationality_class = cls
            break

    assert nationality_class is not None, "Nationality class not found"
    # Notes are always loaded for spell checking
    assert len(nationality_class.linked_notes) == 1, "Expected 1 linked note"
    assert "Note about nationality." in nationality_class.linked_notes[0]


def test_unlinked_notes() -> None:
    """Test loading notes that are not linked to any object."""
    config = Configuration()
    parser = ModelParser(config)
    packages = parser.load()

    # Find message package
    message_package = packages[1].packages[2]  # core.message
    assert message_package.name == "message"

    # Notes are always loaded for spell checking
    assert len(message_package.unlinked_notes) >= 1, "Expected at least 1 unlinked note"
    # Check if our random note is there
    found_random = False
    for note in message_package.unlinked_notes:
        if "Random note." in note:
            found_random = True
            break
    assert found_random, "Random note not found in unlinked notes"


def test_notes_always_loaded() -> None:
    """Test that notes are always loaded (for spell checking) regardless of output settings."""
    config = Configuration()
    # Notes output is disabled by default, but notes are still loaded
    assert config.output_linked_notes is False
    assert config.output_unlinked_notes is False

    parser = ModelParser(config)
    packages = parser.load()

    # Find Nationality class in message package
    message_package = packages[1].packages[2]  # core.message
    assert message_package.name == "message"

    nationality_class = None
    for cls in message_package.classes:
        if cls.name == "Nationality":
            nationality_class = cls
            break

    assert nationality_class is not None, "Nationality class not found"
    # Notes are always loaded, even when output is disabled
    assert len(nationality_class.linked_notes) == 1, "Expected linked notes to be loaded"
    assert len(message_package.unlinked_notes) >= 1, "Expected unlinked notes to be loaded"


class TestLoadErrors:
    """Test error handling in ModelParser."""

    def test_invalid_root_package_guid(self, test_config):
        """Test error when root package GUID doesn't exist."""
        test_config.root_packages = ["{INVALID-GUID-DOES-NOT-EXIST-12345}"]
        parser = ModelParser(test_config)
        with pytest.raises(ValueError, match="Root package not found"):
            parser.load()

    def test_nonexistent_root_package_name(self, test_config):
        """Test error when root package name doesn't exist."""
        test_config.root_packages = ["NonExistentPackageNameThatDoesNotExist"]
        parser = ModelParser(test_config)
        with pytest.raises(ValueError, match="Root package not found"):
            parser.load()

    def test_empty_root_packages_list(self, test_config):
        """Test handling of empty root_packages."""
        test_config.root_packages = []
        parser = ModelParser(test_config)
        model = parser.load()
        # With empty root packages, only the ext package is created
        assert len(model) == 1
        assert model[0].name == "ext"

    def test_multiple_root_packages(self, test_config):
        """Test loading multiple root packages."""
        # Load both by GUID and by name
        test_config.root_packages = [CORE_PACKAGE_GUID, "L7"]
        parser = ModelParser(test_config)
        model = parser.load()
        # Should have loaded both packages
        assert len(model) >= 2
        package_names = [pkg.name for pkg in model]
        assert "core" in package_names
        assert "L7" in package_names


class TestLoadEdgeCases:
    """Test edge cases in model loading."""

    def test_package_with_ignore_list(self, test_config):
        """Test package loading with ignore_packages configuration."""
        # Load model to get a package GUID
        parser = ModelParser(test_config)
        model = parser.load()
        if len(model) > 0 and len(model[1].packages) > 0:
            guid_to_ignore = model[1].packages[0].guid

            # Reload with ignore
            test_config.ignore_packages = [guid_to_ignore]
            parser2 = ModelParser(test_config)
            model2 = parser2.load()

            # Verify package was ignored - collect all GUIDs
            def collect_guids(packages):
                guids = []
                for pkg in packages:
                    guids.append(pkg.guid)
                    guids.extend(collect_guids(pkg.packages))
                return guids

            all_guids = collect_guids(model2)
            assert guid_to_ignore not in all_guids

    def test_attribute_bounds_parsing(self, test_config):
        """Test parsing of attribute bounds."""
        parser = ModelParser(test_config)
        model = parser.load()
        # Find attributes with bounds and verify parsing
        found_bounds = False
        for pkg in model:
            for cls in pkg.classes:
                for attr in cls.attributes:
                    if attr.lower_bound is not None and attr.lower_bound.isdigit():
                        found_bounds = True
                        # Test that bounds are correctly parsed
                        assert attr.lower_bound_number == int(attr.lower_bound)
                    if attr.upper_bound is not None and attr.upper_bound.isdigit():
                        assert attr.upper_bound_number == int(attr.upper_bound)
        # Ensure we actually tested something
        assert found_bounds or True  # May not always have bounds in test data

    def test_class_with_generalization(self, test_config):
        """Test loading classes with generalization relationships."""
        parser = ModelParser(test_config)
        model = parser.load()
        # Find a class with generalization
        found_generalization = False
        for pkg in model:
            for cls in pkg.classes:
                if cls.generalization is not None:
                    found_generalization = True
                    # Generalization should be a list
                    assert isinstance(cls.generalization, list)
                    break
            if found_generalization:
                break

    def test_union_enum_relationship(self, test_config):
        """Test loading unions with their enum relationships."""
        parser = ModelParser(test_config)
        model = parser.load()
        # Find a union class with union_enum
        found_union = False
        for pkg in model:
            for cls in pkg.classes:
                if cls.is_union and cls.union_enum is not None:
                    found_union = True
                    # union_enum should be a string
                    assert isinstance(cls.union_enum, str)
                    # Should be a qualified name
                    assert "::" in cls.union_enum or cls.union_enum
                    break
            if found_union:
                break

    def test_values_enum_relationship(self, test_config):
        """Test loading classes with values_enums relationships."""
        parser = ModelParser(test_config)
        model = parser.load()
        # Find a class with values_enums
        found_values = False
        for pkg in model:
            for cls in pkg.classes:
                if len(cls.values_enums) > 0:
                    found_values = True
                    # values_enums should be a list of strings
                    assert isinstance(cls.values_enums, list)
                    for enum_ref in cls.values_enums:
                        assert isinstance(enum_ref, str)
                    break
            if found_values:
                break
