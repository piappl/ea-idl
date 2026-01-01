"""Tests for primitive type mapping to IDL types."""

import pytest
from eaidl.config import Configuration
from eaidl.model import ModelAttribute, ModelClass
from eaidl import validation as v


class TestConfigurationTypeMethods:
    """Test Configuration class methods for type mapping."""

    def test_get_idl_type_with_known_primitive(self):
        """Test getting IDL type for a known primitive type."""
        config = Configuration()
        assert config.get_idl_type("int") == "long"
        assert config.get_idl_type("unsigned int") == "unsigned long"

    def test_get_idl_type_with_identity_mapping(self):
        """Test getting IDL type for types that map to themselves."""
        config = Configuration()
        assert config.get_idl_type("long") == "long"
        assert config.get_idl_type("string") == "string"
        assert config.get_idl_type("boolean") == "boolean"

    def test_get_idl_type_with_unknown_type(self):
        """Test getting IDL type for non-primitive type (returns as-is)."""
        config = Configuration()
        assert config.get_idl_type("MyCustomType") == "MyCustomType"
        assert config.get_idl_type("SomeNamespace::SomeType") == "SomeNamespace::SomeType"

    def test_is_primitive_type_returns_true_for_primitives(self):
        """Test is_primitive_type returns True for primitive types."""
        config = Configuration()
        assert config.is_primitive_type("int") is True
        assert config.is_primitive_type("long") is True
        assert config.is_primitive_type("string") is True
        assert config.is_primitive_type("boolean") is True

    def test_is_primitive_type_returns_false_for_custom_types(self):
        """Test is_primitive_type returns False for custom types."""
        config = Configuration()
        assert config.is_primitive_type("MyCustomType") is False
        assert config.is_primitive_type("SomeNamespace::SomeType") is False

    def test_custom_primitive_types_mapping(self):
        """Test configuration with custom primitive types mapping."""
        config = Configuration(
            primitive_types={
                "int32": "long",
                "int64": "long long",
                "text": "string",
            }
        )
        assert config.get_idl_type("int32") == "long"
        assert config.get_idl_type("int64") == "long long"
        assert config.get_idl_type("text") == "string"
        assert config.is_primitive_type("int32") is True
        assert config.is_primitive_type("int64") is True
        assert config.is_primitive_type("text") is True


class TestPrimitiveTypeMappedValidator:
    """Test the primitive_type_mapped validator."""

    def test_valid_primitive_type_passes(self):
        """Test that valid primitive types pass validation."""
        config = Configuration()
        attr = ModelAttribute(
            name="test_attr",
            alias="test_attr",
            type="long",
            attribute_id=1,
            guid="test-guid",
            connector=None,  # No connector means it's a primitive
        )
        cls = ModelClass(name="TestClass", object_id=1, namespace=["test"])
        # Should not raise
        v.attribute.primitive_type_mapped(config=config, attribute=attr, cls=cls)

    def test_unmapped_primitive_type_fails(self):
        """Test that unmapped primitive types fail validation."""
        config = Configuration()
        attr = ModelAttribute(
            name="test_attr",
            alias="test_attr",
            type="unknowntype",  # Not in primitive_types mapping
            attribute_id=1,
            guid="test-guid",
            connector=None,  # No connector means it should be a primitive
        )
        cls = ModelClass(name="TestClass", object_id=1, namespace=["test"])

        with pytest.raises(ValueError, match="not mapped in configuration"):
            v.attribute.primitive_type_mapped(config=config, attribute=attr, cls=cls)

    def test_enum_attributes_skip_validation(self):
        """Test that enum attributes skip primitive type validation."""
        config = Configuration()
        attr = ModelAttribute(
            name="ENUM_VALUE",
            alias="ENUM_VALUE",
            type=None,  # Enum values don't have types
            attribute_id=1,
            guid="test-guid",
            connector=None,
        )
        cls = ModelClass(
            name="TestEnum",
            object_id=1,
            namespace=["test"],
            stereotypes=[config.stereotypes.idl_enum],
        )
        # Should not raise even with no type
        v.attribute.primitive_type_mapped(config=config, attribute=attr, cls=cls)

    def test_attributes_with_connector_skip_validation(self):
        """Test that attributes with connectors skip validation."""
        from eaidl.model import ModelConnection

        config = Configuration()
        connector = ModelConnection(
            connector_id=1,
            connector_type="Association",
            start_object_id=1,
            end_object_id=2,
        )
        attr = ModelAttribute(
            name="test_attr",
            alias="test_attr",
            type="SomeClass",
            attribute_id=1,
            guid="test-guid",
            connector=connector,  # Has connector, so not a primitive
        )
        cls = ModelClass(name="TestClass", object_id=1, namespace=["test"])
        # Should not raise even though "SomeClass" is not in primitive_types
        v.attribute.primitive_type_mapped(config=config, attribute=attr, cls=cls)


class TestTypeMappingInOutput:
    """Test that type mapping is applied in IDL output."""

    def test_int_mapped_to_long_in_template(self):
        """Test that 'int' is mapped to 'long' in template output."""
        from eaidl.generate import create_env
        from eaidl.model import ModelClass, ModelAttribute

        config = Configuration()
        env = create_env(config)
        template = env.get_template("idl/gen_attribute.jinja2")

        attr = ModelAttribute(
            name="test_field",
            alias="test_field",
            type="int",
            attribute_id=1,
            guid="test-guid",
            namespace=[],
        )
        cls = ModelClass(name="TestClass", object_id=1, namespace=[])

        result = template.module.gen_attribute(None, cls, attr)
        assert "long test_field;" in result
        assert "int test_field;" not in result

    def test_unsigned_int_mapped_in_template(self):
        """Test that 'unsigned int' is mapped to 'unsigned long' in template output."""
        from eaidl.generate import create_env
        from eaidl.model import ModelClass, ModelAttribute

        config = Configuration()
        env = create_env(config)
        template = env.get_template("idl/gen_attribute.jinja2")

        attr = ModelAttribute(
            name="test_field",
            alias="test_field",
            type="unsigned int",
            attribute_id=1,
            guid="test-guid",
            namespace=[],
        )
        cls = ModelClass(name="TestClass", object_id=1, namespace=[])

        result = template.module.gen_attribute(None, cls, attr)
        assert "unsigned long test_field;" in result

    def test_typedef_type_mapping(self):
        """Test that type mapping works in typedef template."""
        from eaidl.generate import create_env
        from eaidl.model import ModelClass

        config = Configuration()
        env = create_env(config)
        template = env.get_template("idl/gen_typedef.jinja2")

        cls = ModelClass(
            name="MyInt",
            object_id=1,
            namespace=[],
            parent_type="int",  # Should be mapped to "long"
            is_typedef=True,
        )

        result = template.module.gen_typedef(cls)
        assert "typedef long MyInt;" in result
        assert "typedef int MyInt;" not in result
