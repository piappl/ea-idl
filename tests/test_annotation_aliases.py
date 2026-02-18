"""Tests for AnnotationType aliases and Configuration.find_annotation."""

from pathlib import Path

from eaidl.config import AnnotationType, Configuration
from eaidl.generate import generate
from eaidl.load import ModelParser
from eaidl.tree_utils import find_class


class TestFindAnnotation:
    """Tests for Configuration.find_annotation method."""

    def setup_method(self):
        self.config = Configuration(
            annotations={
                "exclusive_maximum": AnnotationType(
                    idl_default=False,
                    idl_types=["any value;"],
                    aliases=["exclusiveMaximum"],
                ),
                "my_max": AnnotationType(
                    idl_default=True,
                    idl_name="max",
                    aliases=["maximum"],
                ),
                "no_alias": AnnotationType(
                    idl_default=True,
                    idl_name="plain",
                ),
            }
        )

    def test_direct_key_match(self):
        result = self.config.find_annotation("exclusive_maximum")
        assert result is not None
        key, annotation = result
        assert key == "exclusive_maximum"
        assert annotation.idl_default is False

    def test_alias_match(self):
        result = self.config.find_annotation("exclusiveMaximum")
        assert result is not None
        key, annotation = result
        assert key == "exclusive_maximum"
        assert annotation.aliases == ["exclusiveMaximum"]

    def test_alias_match_returns_config_key_not_alias(self):
        result = self.config.find_annotation("maximum")
        assert result is not None
        key, _ = result
        assert key == "my_max"

    def test_no_match_returns_none(self):
        result = self.config.find_annotation("nonexistent")
        assert result is None

    def test_direct_key_takes_priority_over_alias(self):
        """If a name matches both a direct key and an alias, direct key wins."""
        config = Configuration(
            annotations={
                "foo": AnnotationType(idl_default=True, aliases=["bar"]),
                "bar": AnnotationType(idl_default=False),
            }
        )
        result = config.find_annotation("bar")
        assert result is not None
        key, annotation = result
        assert key == "bar"
        assert annotation.idl_default is False

    def test_works_for_idl_default_true(self):
        result = self.config.find_annotation("maximum")
        assert result is not None
        _, annotation = result
        assert annotation.idl_default is True
        assert annotation.idl_name == "max"

    def test_works_for_idl_default_false(self):
        result = self.config.find_annotation("exclusiveMaximum")
        assert result is not None
        _, annotation = result
        assert annotation.idl_default is False

    def test_no_alias_annotation_found_by_key(self):
        result = self.config.find_annotation("no_alias")
        assert result is not None
        key, annotation = result
        assert key == "no_alias"
        assert annotation.idl_name == "plain"


def _make_config_with_aliases() -> Configuration:
    """Create a config that renames exclusiveMaximum -> exclusive_maximum via alias."""
    config = Configuration()
    config.database_url = f"sqlite+pysqlite:///{(Path(__file__).parent / 'data' / 'nafv4.qea').as_posix()}"
    config.root_packages = ["{753A4DFC-7876-4b00-BB5A-6274AD3817C3}"]
    config.reserved_words_action = "allow"
    # Rename exclusiveMaximum -> exclusive_maximum via alias
    config.annotations["exclusive_maximum"] = AnnotationType(
        idl_default=False,
        idl_types=["any value;"],
        aliases=["exclusiveMaximum"],
    )
    # Remove the original key so only the alias path works
    del config.annotations["exclusiveMaximum"]
    return config


def test_alias_renames_ext_annotation_in_model():
    """EA tag 'exclusiveMaximum' should become ext::exclusive_maximum in the model."""
    config = _make_config_with_aliases()
    parser = ModelParser(config)
    packages = parser.load()

    cls = find_class(packages, lambda c: c.name == "TemperatureMeasurement")
    assert cls is not None, "TemperatureMeasurement not found in model"

    # Should use config key, not EA tag name
    assert (
        "ext::exclusive_maximum" in cls.properties
    ), f"Expected ext::exclusive_maximum in properties, got: {list(cls.properties.keys())}"
    assert "ext::exclusiveMaximum" not in cls.properties, "Old EA tag name ext::exclusiveMaximum should not appear"


def test_alias_renames_ext_annotation_definition():
    """The ext module should define @annotation exclusive_maximum, not exclusiveMaximum."""
    config = _make_config_with_aliases()
    parser = ModelParser(config)
    packages = parser.load()

    # The ext package is always the first one
    ext_pkg = packages[0]
    assert ext_pkg.name == "ext"

    prop_names = [pt.property for pt in ext_pkg.property_types]
    assert "exclusive_maximum" in prop_names, f"Expected exclusive_maximum in ext property_types, got: {prop_names}"
    assert "exclusiveMaximum" not in prop_names, "Old EA tag name exclusiveMaximum should not appear in ext definitions"


def test_alias_renames_ext_annotation_in_generated_idl():
    """Generated IDL should use exclusive_maximum everywhere, not exclusiveMaximum."""
    config = _make_config_with_aliases()
    parser = ModelParser(config)
    idl_output = generate(config, parser.load())

    # Annotation definition should use the config key
    assert "@annotation exclusive_maximum" in idl_output
    assert "@annotation exclusiveMaximum" not in idl_output

    # Usage should reference the renamed annotation
    assert "@ext::exclusive_maximum(" in idl_output
    assert "@ext::exclusiveMaximum(" not in idl_output


def test_alias_standard_annotation_uses_idl_name():
    """An alias on an idl_default=True annotation should still use idl_name in output.

    EA has tag 'minimum' on TemperatureMeasurement. We rename the config key
    to 'renamed_min' with alias=['minimum'] and idl_name='min'.
    The property should still appear as 'min' (from idl_name).
    """
    config = Configuration()
    config.database_url = f"sqlite+pysqlite:///{(Path(__file__).parent / 'data' / 'nafv4.qea').as_posix()}"
    config.root_packages = ["{753A4DFC-7876-4b00-BB5A-6274AD3817C3}"]
    config.reserved_words_action = "allow"
    # Rename "minimum" config key to "renamed_min" with alias, keeping idl_name="min"
    config.annotations["renamed_min"] = AnnotationType(
        idl_default=True,
        idl_name="min",
        aliases=["minimum"],
    )
    del config.annotations["minimum"]

    parser = ModelParser(config)
    packages = parser.load()

    cls = find_class(packages, lambda c: c.name == "TemperatureMeasurement")
    assert cls is not None
    # idl_name takes precedence for idl_default=True annotations
    assert "min" in cls.properties, f"Expected 'min' in properties, got: {list(cls.properties.keys())}"
    assert cls.properties["min"].value == -40


def test_without_alias_uses_original_names():
    """Baseline: without aliases, EA tag names are used directly (existing behavior)."""
    config = Configuration()
    config.database_url = f"sqlite+pysqlite:///{(Path(__file__).parent / 'data' / 'nafv4.qea').as_posix()}"
    config.root_packages = ["{753A4DFC-7876-4b00-BB5A-6274AD3817C3}"]
    config.reserved_words_action = "allow"

    parser = ModelParser(config)
    idl_output = generate(config, parser.load())

    # Default config uses "exclusiveMaximum" as the key directly
    assert "@annotation exclusiveMaximum" in idl_output
    assert "@ext::exclusiveMaximum(" in idl_output
