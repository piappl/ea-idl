from eaidl.utils import (
    load_config,
    is_camel_case,
    is_lower_camel_case,
    is_snake_case,
    is_lower_snake_case,
    get_prop,
    enum_name_from_union_attr,
)
from pathlib import Path
import pytest


def test_load_json() -> None:
    path = Path(__file__).parent / "data" / "config.json"
    config = load_config(path)
    assert config.database_url == "sqlite:///tests/data/nafv4.qea"


def test_load_yaml() -> None:
    path = Path(__file__).parent / "data" / "config.yaml"
    config = load_config(path)
    assert config.database_url == "sqlite:///tests/data/nafv4.qea"


def test_load_file_does_not_exist() -> None:
    path = "not_exists"
    with pytest.raises(FileNotFoundError):
        load_config(path)


def test_load_file_wrong_data() -> None:
    path = Path(__file__).parent / "data" / "wrong.yaml"
    with pytest.raises(ValueError):
        load_config(path)


@pytest.mark.parametrize(
    "value,expected",
    [
        ("", False),
        (" ", False),
        ("core module", False),
        ("coreModule", False),
        ("coreModule1", False),
        ("CoreModule1", True),
        ("CoreModule_1", False),
        ("Quaternion", True),
    ],
)
def test_is_camel_case(value, expected) -> None:
    assert is_camel_case(value) == expected


@pytest.mark.parametrize(
    "value,expected",
    [
        ("", False),
        (" ", False),
        ("core module", False),
        ("coreModule", True),
        ("coreModule1", True),
        ("coreModule_1", False),
        ("CoreModule", False),
    ],
)
def test_is_lower_camel_case(value, expected) -> None:
    assert is_lower_camel_case(value) == expected


@pytest.mark.parametrize(
    "value,expected",
    [
        ("", False),
        (" ", False),
        ("core module", False),
        ("coreModule", True),
        ("coreModule1", False),
        ("coreModule_1", True),
        ("CoreModule", True),
        ("core_module", True),
    ],
)
def test_is_snake_case(value, expected) -> None:
    assert is_snake_case(value) == expected


@pytest.mark.parametrize(
    "value,expected",
    [
        ("", False),
        (" ", False),
        ("core module", False),
        ("coreModule", False),
        ("coreModule1", False),
        ("coreModule_1", False),
        ("CoreModule", False),
        ("core_module_1", True),
        ("core_module", True),
        ("core", True),
    ],
)
def test_is_lower_snake_case(value, expected) -> None:
    assert is_lower_snake_case(value) == expected


def test_enum_name_from_union() -> None:
    # Union Measurement has attribute a_temperature_measurement
    # We need enum name (MeasurementTypeEnum)
    # From that enumeration name is MeasurementTypeEnum_TEMPERATURE_MEASUREMENT
    assert "MeasurementTypeEnum_TEMPERATURE_MEASUREMENT" == enum_name_from_union_attr(
        enum_name="MeasurementTypeEnum", attr_type="temperature_measurement"
    )


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
        get_prop(
            "@NAME=isFinalSpecialization@ENDNAME;@TYPE=Boolean@ENDTYPE;@VALU=-1@ENDVALU;",
            "NAME",
        )
        == "isFinalSpecialization"
    )
    assert (
        get_prop(
            "@NAME=isFinalSpecialization@ENDNAME;@TYPE=Boolean@ENDTYPE;@VALU=-1@ENDVALU;",
            "TYPE",
        )
        == "Boolean"
    )
    assert (
        get_prop(
            "@NAME=isFinalSpecialization@ENDNAME;@TYPE=Boolean@ENDTYPE;@VALU=-1@ENDVALU;",
            "VALU",
        )
        == "-1"
    )
