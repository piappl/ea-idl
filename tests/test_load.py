from eaidl.load import ModelParser, get_prop
from eaidl.utils import Configuration
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
        "t_package": 6,
        "t_object": 13,
        "t_attribute": 11,
        "t_connector": 8,
        "t_objectproperties": 24,
        "t_xref": 18,  # Stereotypes, properties
    }

    for key, value in contents.items():
        assert session.query(getattr(base.classes, key)).count() == value
    # Just check one of packages
    TPackage = base.classes.t_package
    item = session.query(TPackage).filter(TPackage.Name == "message").scalar()
    assert item is not None


def test_load():
    parser = ModelParser(Configuration())
    model = parser.load()
    # Core is default
    assert model.name == "core"
    parser = ModelParser(Configuration(root_package="something not there"))
    inspect(model)
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


def test_get_prop() -> None:
    assert get_prop("", "NAME") == ""
    assert (
        get_prop(
            "@PROP=@NAME=isFinalSpecialization@ENDNAME;@TYPE=Boolean@ENDTYPE;@VALU=-1@ENDVALU;@PRMT=@ENDPRMT;@ENDPROP;",
            "PROP",
        )
        == "@NAME=isFinalSpecialization@ENDNAME;@TYPE=Boolean@ENDTYPE;@VALU=-1@ENDVALU;@PRMT=@ENDPRMT;"
    )
    assert (
        get_prop("@NAME=isFinalSpecialization@ENDNAME;@TYPE=Boolean@ENDTYPE;@VALU=-1@ENDVALU;", "NAME")
        == "isFinalSpecialization"
    )
    assert get_prop("@NAME=isFinalSpecialization@ENDNAME;@TYPE=Boolean@ENDTYPE;@VALU=-1@ENDVALU;", "TYPE") == "Boolean"
    assert get_prop("@NAME=isFinalSpecialization@ENDNAME;@TYPE=Boolean@ENDTYPE;@VALU=-1@ENDVALU;", "VALU") == "-1"


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
    assert parser.get_namespace(11) == ["core", "data", "types"]
    config.root_package = CORE_PACKAGE_GUID
    parser = ModelParser(config)
    parser.load()
    assert parser.get_namespace(2) == []  # Model
    assert parser.get_namespace(10) == []  # L7
    assert parser.get_namespace(3) == ["core"]
    assert parser.get_namespace(9) == ["core", "data"]
    assert parser.get_namespace(11) == ["core", "data", "types"]
    config.root_package = "L7"
    parser = ModelParser(config)
    parser.load()
    assert parser.get_namespace(2) == []  # Model
    assert parser.get_namespace(10) == ["L7"]  # L7
    assert parser.get_namespace(3) == []
    assert parser.get_namespace(9) == []
    assert parser.get_namespace(11) == []
