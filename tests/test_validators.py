import pytest
import uuid
from typing import Optional
from eaidl import validation as v
from eaidl.config import Configuration
from eaidl.model import ModelAttribute, ModelClass


def m_attr(name: str = "attr", attribute_id: int = 0, type: Optional[str] = None, **kwargs) -> ModelAttribute:
    defaults = {
        "name": name,
        "alias": name,
        "attribute_id": attribute_id,
        "type": type,
        "guid": str(uuid.uuid4()),
    }
    return ModelAttribute(**{**defaults, **kwargs})


def m_class(name: str = "cls", object_id: int = 0, **kwargs) -> ModelClass:
    defaults = {
        "name": name,
        "object_id": object_id,
        "guid": str(uuid.uuid4()),
        "namespace": ["root"],
    }
    return ModelClass(**{**defaults, **kwargs})


def test_attribute_name_is_reserved_word() -> None:
    """Test that IDL reserved words in attribute names fail validation."""
    with pytest.raises(ValueError, match="IDL reserved word"):
        v.attribute.name_is_reserved_word(
            Configuration(reserved_words_action="fail", validators_fail=["attribute.name_is_reserved_word"]),
            attribute=m_attr(name="struct"),
            cls=m_class(),
        )
    # This will not run test, validators are disabled
    v.attribute.name_is_reserved_word(
        Configuration(validators_fail=[]),
        attribute=m_attr(name="struct"),
        cls=m_class(),
    )
    # With prefix action, validation should pass (prefixing happens in load phase)
    v.attribute.name_is_reserved_word(
        Configuration(reserved_words_action="prefix", validators_fail=["attribute.name_is_reserved_word"]),
        attribute=m_attr(name="struct"),
        cls=m_class(),
    )
    # Correct output
    v.attribute.name_is_reserved_word(
        Configuration(validators_fail=[]),
        attribute=m_attr(name="valid_name"),
        cls=m_class(),
    )


def test_attribute_connector_leads_to_type() -> None:
    with pytest.raises(ValueError):
        v.attribute.connector_leads_to_type(
            Configuration(validators_fail=["attribute.connector_leads_to_type"]),
            attribute=m_attr(name="from"),
            cls=m_class(),
        )
    # Will work for primitive
    v.attribute.connector_leads_to_type(
        Configuration(validators_fail=["attribute.connector_leads_to_type"]),
        attribute=m_attr(name="from", type="string"),
        cls=m_class(),
    )


# ============================================================================
# Phase 4.3: Edge Case Tests
# ============================================================================


class TestStructValidators:
    """Test edge cases for struct validators."""

    def test_reserved_word_in_class_name(self):
        """Test validation fails for IDL reserved words in class names."""
        config = Configuration(reserved_words_action="fail", validators_fail=["struct.name_is_reserved_word"])
        cls = m_class(name="struct")  # IDL reserved word

        with pytest.raises(ValueError, match="IDL reserved word"):
            v.struct.name_is_reserved_word(config, cls=cls)

    def test_incorrect_camel_case(self):
        """Test validation fails on incorrect naming convention."""
        config = Configuration(validators_fail=["struct.name_camel_convention"])
        cls = m_class(name="bad_snake_case")

        with pytest.raises(ValueError, match="wrong case"):
            v.struct.name_camel_convention(config, cls=cls)

    def test_camel_case_with_abbreviations(self):
        """Test validation passes for class names with allowed abbreviations."""
        # Without abbreviations, these should fail
        config = Configuration(validators_fail=["struct.name_camel_convention"])

        cls_mcm = m_class(name="MCMContact")
        with pytest.raises(ValueError, match="wrong case"):
            v.struct.name_camel_convention(config, cls=cls_mcm)

        cls_uri = m_class(name="URI")
        with pytest.raises(ValueError, match="wrong case"):
            v.struct.name_camel_convention(config, cls=cls_uri)

        # With abbreviations, these should pass
        config_with_abbrev = Configuration(
            validators_fail=["struct.name_camel_convention"], allowed_abbreviations=["MCM", "URI", "CQL"]
        )

        v.struct.name_camel_convention(config_with_abbrev, cls=cls_mcm)
        v.struct.name_camel_convention(config_with_abbrev, cls=cls_uri)
        v.struct.name_camel_convention(config_with_abbrev, cls=m_class(name="CQL2ExpressionTypeEnum"))

    def test_experimental_stereotype(self):
        """Test validation fails for experimental classes."""
        config = Configuration(validators_fail=["struct.is_experimental"])
        cls = m_class(name="ExperimentalClass", stereotypes=["experimental"])

        with pytest.raises(ValueError, match="experimental"):
            v.struct.is_experimental(config, cls=cls)

    def test_invalid_stereotype_combination(self):
        """Test validation fails for conflicting stereotypes."""
        config = Configuration(validators_fail=["struct.stereotypes"])
        cls = m_class(
            name="BadClass",
            stereotypes=[
                config.stereotypes.main_class,
                config.stereotypes.idl_struct,
                config.stereotypes.idl_enum,  # Can't be both!
            ],
            is_struct=True,
            is_enum=True,
        )

        with pytest.raises(ValueError, match="proper stereotypes"):
            v.struct.stereotypes(config, cls=cls)

    def test_stereotype_flag_mismatch(self):
        """Test validation fails when stereotype doesn't match flag."""
        config = Configuration(validators_fail=["struct.stereotypes"])
        cls = m_class(
            name="BadClass",
            stereotypes=[config.stereotypes.main_class, config.stereotypes.idl_struct],
            is_struct=False,  # Flag doesn't match stereotype
        )

        with pytest.raises(ValueError, match="is_struct flag"):
            v.struct.stereotypes(config, cls=cls)

    def test_enum_without_prefix(self):
        """Test validation fails for enum values without common prefix."""
        config = Configuration(validators_fail=["struct.enum_prefix"])
        cls = m_class(
            name="Color",
            stereotypes=[config.stereotypes.main_class, config.stereotypes.idl_enum],
            is_enum=True,
            attributes=[
                m_attr(name="Color_RED", attribute_id=1),
                m_attr(name="Color_GREEN", attribute_id=2),
                m_attr(name="UNRELATED", attribute_id=3),  # No common prefix
            ],
        )

        with pytest.raises(ValueError, match="No prefix"):
            v.struct.enum_prefix(config, cls=cls)

    def test_enum_attribute_with_none_name(self):
        """Test validation fails for enum attribute without name."""
        config = Configuration(validators_fail=["struct.enum_prefix"])
        # Create attribute with None name directly in dict
        attr = m_attr(name="temp", attribute_id=1)
        attr.name = None  # Set to None after creation

        cls = m_class(
            name="Status",
            stereotypes=[config.stereotypes.main_class, config.stereotypes.idl_enum],
            is_enum=True,
            attributes=[attr],
        )

        with pytest.raises(ValueError, match="No name"):
            v.struct.enum_prefix(config, cls=cls)

    def test_missing_notes(self):
        """Test validation fails on missing documentation."""
        config = Configuration(validators_fail=["struct.notes"])
        cls = m_class(name="Undocumented", notes=None)

        with pytest.raises(ValueError, match="no description"):
            v.struct.notes(config, cls=cls)

    def test_empty_notes(self):
        """Test validation fails on empty documentation."""
        config = Configuration(validators_fail=["struct.notes"])
        cls = m_class(name="EmptyDocs", notes="   ")  # Only whitespace

        with pytest.raises(ValueError, match="no description"):
            v.struct.notes(config, cls=cls)

    def test_enum_with_typed_attributes(self):
        """Test that enums with typed attributes fail validation."""
        config = Configuration(validators_fail=["struct.enum_attributes"])
        cls = m_class(
            name="BadEnum",
            stereotypes=[config.stereotypes.idl_enum],
            is_enum=True,
            attributes=[
                m_attr(name="value1", type="int", attribute_id=1),
                m_attr(name="value2", type="string", attribute_id=2),
            ],
        )

        with pytest.raises(ValueError, match="have no types"):
            v.struct.enum_attributes(config, cls=cls)

    def test_enum_with_duplicate_default_values(self):
        """Test enum validation fails with duplicate default values."""
        config = Configuration(validators_fail=["struct.enum_attributes"])

        # Create attributes with duplicate default values
        attr1 = m_attr(name="value1", attribute_id=1)
        attr1.properties = {"default": type("obj", (object,), {"value": "1"})}

        attr2 = m_attr(name="value2", attribute_id=2)
        attr2.properties = {"default": type("obj", (object,), {"value": "1"})}  # Same value

        cls = m_class(
            name="DuplicateEnum",
            stereotypes=[config.stereotypes.idl_enum],
            is_enum=True,
            attributes=[attr1, attr2],
        )

        with pytest.raises(ValueError, match="all unique"):
            v.struct.enum_attributes(config, cls=cls)


class TestAttributeValidators:
    """Test edge cases for attribute validators."""

    def test_experimental_attribute(self):
        """Test validation fails for experimental attributes."""
        config = Configuration(validators_fail=["attribute.is_experimental"])
        attr = m_attr(name="experimental_field", stereotypes=["experimental"])
        cls = m_class(name="TestClass")

        with pytest.raises(ValueError, match="experimental"):
            v.attribute.is_experimental(config, attribute=attr, cls=cls)

    def test_optional_without_stereotype(self):
        """Test validation fails for optional attribute without stereotype."""
        config = Configuration(validators_fail=["attribute.optional_stereotype"])
        attr = m_attr(name="field", lower_bound="0", stereotypes=[])  # Optional but no stereotype
        cls = m_class(name="TestClass")

        with pytest.raises(ValueError, match="No <<optional>> stereotype"):
            v.attribute.optional_stereotype(config, attribute=attr, cls=cls)

    def test_stereotype_without_optional(self):
        """Test validation fails for non-optional attribute with optional stereotype."""
        config = Configuration(validators_fail=["attribute.optional_stereotype"])
        attr = m_attr(name="field", lower_bound="1", stereotypes=["optional"])  # Not optional but has stereotype
        cls = m_class(name="TestClass")

        with pytest.raises(ValueError, match="Non optional"):
            v.attribute.optional_stereotype(config, attribute=attr, cls=cls)

    def test_parent_class_id_mismatch(self):
        """Test validation fails when parent class ID doesn't match."""
        config = Configuration(validators_fail=["attribute.parent_class_id_match"])
        attr = m_attr(name="field", attribute_id=999)  # Different ID
        cls = m_class(name="TestClass", object_id=123)

        with pytest.raises(ValueError, match="parent id"):
            v.attribute.parent_class_id_match(config, attribute=attr, cls=cls)

    def test_collection_with_wrong_bounds(self):
        """Test collection attribute with incorrect bounds."""
        config = Configuration(validators_fail=["attribute.collection_configured"])

        # Collection with upper bound of 1
        attr = m_attr(name="items", is_collection=True, upper_bound="1")
        cls = m_class(name="TestClass")

        with pytest.raises(ValueError, match="is collection, but upper bound"):
            v.attribute.collection_configured(config, attribute=attr, cls=cls)

    def test_non_collection_with_many_bounds(self):
        """Test non-collection attribute with many upper bound."""
        config = Configuration(validators_fail=["attribute.collection_configured"])

        # Non-collection with upper bound of *
        attr = m_attr(name="item", is_collection=False, upper_bound="*")
        cls = m_class(name="TestClass")

        with pytest.raises(ValueError, match="not collection, but upper bound"):
            v.attribute.collection_configured(config, attribute=attr, cls=cls)

    def test_incorrect_snake_case(self):
        """Test validation fails on incorrect naming convention."""
        config = Configuration(validators_fail=["attribute.name_snake_convention"])
        attr = m_attr(name="BadCamelCase")  # Should be snake_case
        cls = m_class(name="TestClass")

        with pytest.raises(ValueError, match="wrong case"):
            v.attribute.name_snake_convention(config, attribute=attr, cls=cls)

    def test_attribute_with_null_name(self):
        """Test validation fails for attribute with null name."""
        config = Configuration(validators_fail=["attribute.name_snake_convention"])
        # Create attribute with empty name then set to None
        attr = m_attr(name="temp")
        attr.name = None
        cls = m_class(name="TestClass")

        with pytest.raises(ValueError, match="wrong case"):
            v.attribute.name_snake_convention(config, attribute=attr, cls=cls)

    def test_attribute_missing_notes(self):
        """Test validation fails for attribute without documentation."""
        config = Configuration(validators_fail=["attribute.notes"])
        attr = m_attr(name="field", notes=None)
        cls = m_class(name="TestClass")

        with pytest.raises(ValueError, match="no description"):
            v.attribute.notes(config, attribute=attr, cls=cls)

    def test_attribute_empty_notes(self):
        """Test validation fails for attribute with empty documentation."""
        config = Configuration(validators_fail=["attribute.notes"])
        attr = m_attr(name="field", notes="  \n  ")  # Only whitespace
        cls = m_class(name="TestClass")

        with pytest.raises(ValueError, match="no description"):
            v.attribute.notes(config, attribute=attr, cls=cls)


class TestTypedefValidators:
    """Test validators for typedef classes."""

    def test_typedef_without_association_fails(self):
        """Test validation fails for typedef without Association connector (direct reference)."""
        config = Configuration(validators_fail=["struct.typedef_has_association"])
        cls = m_class(
            name="MyNode",
            is_typedef=True,
            parent_type="Node",  # Direct reference, not sequence
            depends_on=[],  # No Association connector
        )

        with pytest.raises(ValueError, match="has no Association connector"):
            v.struct.typedef_has_association(config, cls=cls)

    def test_typedef_with_association_passes(self):
        """Test validation passes for typedef with Association connector (direct reference)."""
        config = Configuration(validators_fail=["struct.typedef_has_association"])
        cls = m_class(
            name="MyNode",
            is_typedef=True,
            parent_type="Node",  # Direct reference
            depends_on=[123],  # Association connector present
        )

        # Should not raise
        v.struct.typedef_has_association(config, cls=cls)

    def test_typedef_primitive_type_passes(self):
        """Test validation passes for typedef to primitive type."""
        config = Configuration(validators_fail=["struct.typedef_has_association"])
        cls = m_class(
            name="MyString",
            is_typedef=True,
            parent_type="string",
            depends_on=[],  # No Association needed for primitives
        )

        # Should not raise - primitive types don't need Association
        v.struct.typedef_has_association(config, cls=cls)

    def test_typedef_sequence_of_primitive_passes(self):
        """Test validation passes for typedef to sequence of primitive."""
        config = Configuration(validators_fail=["struct.typedef_has_association"])
        cls = m_class(
            name="StringList",
            is_typedef=True,
            parent_type="sequence<string>",
            depends_on=[],  # No Association needed for sequence types
        )

        # Should not raise - sequence types don't need Association
        v.struct.typedef_has_association(config, cls=cls)

    def test_typedef_sequence_of_custom_type_passes(self):
        """Test validation passes for typedef to sequence of custom type (no Association needed)."""
        config = Configuration(validators_fail=["struct.typedef_has_association"])
        cls = m_class(
            name="NodeList",
            is_typedef=True,
            parent_type="sequence<Node>",
            depends_on=[],  # No Association needed for sequence types
        )

        # Should not raise - sequence<T> doesn't require Association even for custom types
        v.struct.typedef_has_association(config, cls=cls)

    def test_typedef_map_without_association_passes(self):
        """Test validation passes for typedef to map (no Association needed)."""
        config = Configuration(validators_fail=["struct.typedef_has_association"])
        cls = m_class(
            name="NodeMap",
            is_typedef=True,
            parent_type="map<string, Node>",
            depends_on=[],  # No Association needed for map types
        )

        # Should not raise - map<K,V> doesn't require Association
        v.struct.typedef_has_association(config, cls=cls)

    def test_typedef_direct_reference_without_association_fails(self):
        """Test validation fails for typedef with direct type reference."""
        config = Configuration(validators_fail=["struct.typedef_has_association"])
        cls = m_class(
            name="MyNode",
            is_typedef=True,
            parent_type="Node",
            depends_on=[],  # No Association connector
        )

        with pytest.raises(ValueError, match="has no Association connector"):
            v.struct.typedef_has_association(config, cls=cls)

    def test_typedef_validator_disabled_passes(self):
        """Test that validator doesn't run when disabled."""
        config = Configuration(validators_fail=[])  # Validator not enabled
        cls = m_class(
            name="NodeList",
            is_typedef=True,
            parent_type="sequence<Node>",
            depends_on=[],  # No Association, but validator disabled
        )

        # Should not raise when validator is disabled
        v.struct.typedef_has_association(config, cls=cls)

    def test_typedef_without_parent_type_passes(self):
        """Test that typedef without parent_type is skipped."""
        config = Configuration(validators_fail=["struct.typedef_has_association"])
        cls = m_class(
            name="BrokenTypedef",
            is_typedef=True,
            parent_type=None,  # Missing parent_type
            depends_on=[],
        )

        # Should not raise - this is a different modeling error
        v.struct.typedef_has_association(config, cls=cls)

    def test_non_typedef_class_skipped(self):
        """Test that non-typedef classes are skipped."""
        config = Configuration(validators_fail=["struct.typedef_has_association"])
        cls = m_class(
            name="RegularStruct",
            is_typedef=False,
            is_struct=True,
            depends_on=[],
        )

        # Should not raise - validator only applies to typedefs
        v.struct.typedef_has_association(config, cls=cls)


class TestReservedWordsRefactoring:
    """Test the refactored reserved words handling."""

    def test_class_reserved_word_fails(self):
        """Test that IDL reserved words in class names fail when action is 'fail'."""
        config = Configuration(reserved_words_action="fail", validators_fail=["struct.name_is_reserved_word"])
        cls = m_class(name="struct")
        with pytest.raises(ValueError, match="IDL reserved word"):
            v.struct.name_is_reserved_word(config, cls=cls)

    def test_class_reserved_word_with_prefix_action_passes(self):
        """Test that reserved words pass validation when action is 'prefix'."""
        config = Configuration(reserved_words_action="prefix", validators_fail=["struct.name_is_reserved_word"])
        cls = m_class(name="struct")
        # Should not raise - prefixing happens in load phase
        v.struct.name_is_reserved_word(config, cls=cls)

    def test_class_reserved_word_with_allow_action_passes(self):
        """Test that reserved words pass validation when action is 'allow'."""
        config = Configuration(reserved_words_action="allow", validators_fail=["struct.name_is_reserved_word"])
        cls = m_class(name="struct")
        # Should not raise
        v.struct.name_is_reserved_word(config, cls=cls)

    def test_attribute_reserved_word_fails(self):
        """Test that IDL reserved words in attribute names fail when action is 'fail'."""
        config = Configuration(reserved_words_action="fail", validators_fail=["attribute.name_is_reserved_word"])
        attr = m_attr(name="interface")
        cls = m_class()
        with pytest.raises(ValueError, match="IDL reserved word"):
            v.attribute.name_is_reserved_word(config, attribute=attr, cls=cls)

    def test_class_danger_word_warns(self):
        """Test that danger words trigger warnings for classes."""
        config = Configuration(danger_words_action="warn", validators_warn=["struct.name_is_danger_word"])
        cls = m_class(name="class")  # Python keyword
        # Should not raise when in warn list - just logs warning
        v.struct.name_is_danger_word(config, cls=cls)

    def test_class_danger_word_fails(self):
        """Test that danger words can fail validation when action is 'fail'."""
        config = Configuration(danger_words_action="fail", validators_fail=["struct.name_is_danger_word"])
        cls = m_class(name="import")  # Python keyword
        with pytest.raises(ValueError, match="may cause issues"):
            v.struct.name_is_danger_word(config, cls=cls)

    def test_class_danger_word_with_allow_action_passes(self):
        """Test that danger words pass when action is 'allow'."""
        config = Configuration(danger_words_action="allow", validators_warn=["struct.name_is_danger_word"])
        cls = m_class(name="class")
        # Should not raise
        v.struct.name_is_danger_word(config, cls=cls)

    def test_attribute_danger_word_warns(self):
        """Test that danger words trigger warnings for attributes."""
        config = Configuration(danger_words_action="warn", validators_warn=["attribute.name_is_danger_word"])
        attr = m_attr(name="class")  # Python keyword
        cls = m_class()
        # Should not raise when in warn list - just logs warning
        v.attribute.name_is_danger_word(config, attribute=attr, cls=cls)

    def test_custom_reserved_words_list(self):
        """Test using a custom list of reserved words."""
        config = Configuration(
            reserved_words=["custom", "forbidden"],
            reserved_words_action="fail",
            validators_fail=["struct.name_is_reserved_word"],
        )
        # Custom word should fail
        cls_custom = m_class(name="custom")
        with pytest.raises(ValueError, match="IDL reserved word"):
            v.struct.name_is_reserved_word(config, cls=cls_custom)

        # Standard IDL word should pass (not in custom list)
        cls_struct = m_class(name="struct")
        v.struct.name_is_reserved_word(config, cls=cls_struct)

    def test_custom_danger_words_list(self):
        """Test using a custom list of danger words."""
        config = Configuration(
            danger_words=["dangerous", "unsafe"],
            danger_words_action="warn",
            validators_warn=["attribute.name_is_danger_word"],
        )
        # Custom danger word should warn (not raise)
        attr_danger = m_attr(name="dangerous")
        cls = m_class()
        v.attribute.name_is_danger_word(config, attribute=attr_danger, cls=cls)

        # Python keyword should pass (not in custom list)
        attr_class = m_attr(name="class")
        v.attribute.name_is_danger_word(config, attribute=attr_class, cls=cls)


class TestPrefixFunctionality:
    """Test the apply_prefix_with_case function."""

    def test_prefix_attribute_snake_case(self):
        """Test that attributes get snake_case prefix."""
        from eaidl.validation.base import apply_prefix_with_case

        assert apply_prefix_with_case("struct", "idl_", is_class=False) == "idl_struct"
        assert apply_prefix_with_case("interface", "idl_", is_class=False) == "idl_interface"
        assert apply_prefix_with_case("default", "idl_", is_class=False) == "idl_default"

    def test_prefix_class_pascal_case(self):
        """Test that classes get PascalCase prefix."""
        from eaidl.validation.base import apply_prefix_with_case

        assert apply_prefix_with_case("struct", "idl_", is_class=True) == "IdlStruct"
        assert apply_prefix_with_case("interface", "idl_", is_class=True) == "IdlInterface"
        assert apply_prefix_with_case("Union", "idl_", is_class=True) == "IdlUnion"

    def test_prefix_with_custom_prefix(self):
        """Test using a custom prefix string."""
        from eaidl.validation.base import apply_prefix_with_case

        # Custom prefix for attributes
        assert apply_prefix_with_case("struct", "my_", is_class=False) == "my_struct"
        # Custom prefix for classes
        assert apply_prefix_with_case("struct", "my_", is_class=True) == "MyStruct"
