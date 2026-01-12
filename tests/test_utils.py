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
    "value,abbreviations,expected",
    [
        # Without abbreviations, these should fail
        ("MCMContact", None, False),
        ("URI", None, False),
        ("CQL2ExpressionTypeEnum", None, False),
        # With abbreviations, these should pass
        ("MCMContact", ["MCM"], True),
        ("URI", ["URI"], True),
        ("CQL2ExpressionTypeEnum", ["CQL"], True),
        # Mixed cases
        ("URLParser", ["URL"], True),
        ("HTTPSConnection", ["HTTPS"], True),
        ("XMLHttpRequest", ["XML", "HTTP"], True),
        # Edge cases
        ("XMLParser", ["XML"], True),
        ("ParserXML", ["XML"], True),
        ("XML", ["XML"], True),
        # Should still fail even with abbreviations if not camel case
        ("mCMContact", ["MCM"], False),
        ("MCM_Contact", ["MCM"], False),
        # Multiple abbreviations in one name
        ("HTTPSURLParser", ["HTTPS", "URL"], True),
    ],
)
def test_is_camel_case_with_abbreviations(value, abbreviations, expected) -> None:
    assert is_camel_case(value, abbreviations) == expected


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


def test_yaml_include_single_file() -> None:
    """Test YAML include with a single file."""
    path = Path(__file__).parent / "data" / "config_with_single_include.yaml"
    config = load_config(path)
    # Should load the base config
    assert config.database_url == "sqlite:///tests/data/nafv4.qea"
    assert config.root_packages == ["core", "shared"]
    assert config.template == "idl.jinja2"
    assert config.spellcheck.enabled is True
    assert config.spellcheck.check_notes is True
    assert config.diagrams.renderer == "mermaid"


def test_yaml_include_multiple_files() -> None:
    """Test YAML include with multiple files (deep merge)."""
    path = Path(__file__).parent / "data" / "config_with_multiple_includes.yaml"
    config = load_config(path)
    # Should merge base and override
    assert config.database_url == "sqlite:///tests/data/nafv4.qea"
    # Override should win
    assert config.root_packages == ["custom"]
    assert config.template == "idl_just_defs.jinja2"
    # Spellcheck should be deep merged
    assert config.spellcheck.enabled is True  # from base
    assert config.spellcheck.check_notes is False  # from override
    assert config.spellcheck.custom_words == ["foo", "bar"]  # from override
    # Diagrams should be deep merged
    assert config.diagrams.renderer == "plantuml"  # from override
    assert config.diagrams.max_attributes_displayed == 10  # from base


def test_yaml_include_with_inline_override() -> None:
    """Test YAML include for partial config sections."""
    path = Path(__file__).parent / "data" / "config_with_inline_override.yaml"
    config = load_config(path)
    # Direct values from main config
    assert config.database_url == "sqlite:///tests/data/nafv4.qea"
    assert config.root_packages == ["core"]
    assert config.template == "custom_template.jinja2"
    assert config.enable_maps is False
    # Spellcheck section included from separate file
    assert config.spellcheck.enabled is True
    assert config.spellcheck.check_notes is False
    assert config.spellcheck.check_identifiers is True
    assert config.spellcheck.min_word_length == 5
    assert config.spellcheck.custom_words == ["test", "example"]
