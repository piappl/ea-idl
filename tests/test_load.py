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
        "t_package": 7,
        "t_object": 36,  # 33 + 3 note objects (67, 68, 69)
        "t_attribute": 38,
        "t_connector": 36,  # 35 + 1 NoteLink connector to Nationality
        "t_objectproperties": 65,
        "t_xref": 49,  #     Stereotypes, properties
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
