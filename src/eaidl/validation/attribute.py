from eaidl.config import Configuration
from eaidl.model import ModelAttribute, ModelClass
from eaidl.utils import is_lower_snake_case
from .base import validator, RESERVED_NAMES
from .validators import (
    get_attribute_context,
    check_experimental_stereotype,
    check_notes_exist,
    create_spelling_validator,
)


def context(attribute: ModelAttribute, cls: ModelClass) -> str:
    """Get context string for attribute (delegates to validators.get_attribute_context)."""
    return get_attribute_context(attribute, cls)


@validator
def name_for_reserved_worlds(config: Configuration, attribute: ModelAttribute, cls: ModelClass) -> None:
    """Check if parsed attribute name is not a reserved name."""
    if attribute.name in RESERVED_NAMES:
        raise ValueError(f"Attribute name '{attribute.name}' is on reserved world list {context(attribute, cls)}")


@validator
def primitive_type_mapped(config: Configuration, attribute: ModelAttribute, cls: ModelClass):
    """Check that primitive types have a mapping to valid IDL types.

    If an attribute has no connector and is not an enum, it must be a primitive type
    that exists in the primitive_types mapping.
    """
    if (
        attribute.connector is None
        and config.stereotypes.idl_enum not in cls.stereotypes
        and attribute.type is not None
        and not config.is_primitive_type(attribute.type)
    ):
        raise ValueError(
            f"Primitive type '{attribute.type}' is not mapped in configuration. "
            f"Add it to primitive_types mapping {context(attribute, cls)}"
        )


@validator
def connector_leads_to_type(config: Configuration, attribute: ModelAttribute, cls: ModelClass):
    """Check connection type.

    In normal condition we weed connector for all attributes, leading to a type of this attribute.

    Exceptions are for enumeration and attributes that are of primitive types.
    """
    if (
        attribute.connector is None
        and config.stereotypes.idl_enum not in cls.stereotypes
        and not config.is_primitive_type(attribute.type)
    ):
        raise ValueError(f"No connector found for attribute {context(attribute, cls)}")


@validator
def is_experimental(config: Configuration, attribute: ModelAttribute, cls: ModelClass):
    """Check if attribute has experimental stereotype."""
    check_experimental_stereotype(attribute.stereotypes, context(attribute, cls), "Attribute")


@validator
def optional_stereotype(config: Configuration, attribute: ModelAttribute, cls: ModelClass):
    """Check if optional attribute has proper stereotype."""
    if attribute.lower_bound in ["0"]:
        if "optional" not in attribute.stereotypes:
            raise ValueError(f"No <<optional>> stereotype found for optional attribute {context(attribute, cls)}")
    if "optional" in attribute.stereotypes:
        if attribute.lower_bound not in ["0"]:
            raise ValueError(f"Non optional attribute has <<optional>> stereotype {context(attribute, cls)}")


@validator
def parent_class_id_match(config: Configuration, attribute: ModelAttribute, cls: ModelClass):
    if cls.object_id != attribute.attribute_id:
        raise ValueError(
            f"Attribute parent id '{cls.object_id}' is different than attribute {attribute.attribute_id} {context(attribute, cls)}"
        )


@validator
def collection_configured(config: Configuration, attribute: ModelAttribute, cls: ModelClass):
    if attribute.is_collection and attribute.upper_bound in [None, "1", "0"]:
        raise ValueError(
            f"Attribute is collection, but upper bound is {attribute.upper_bound} {context(attribute, cls)}"
        )

    if not attribute.is_collection and attribute.upper_bound not in [
        None,
        "1",
        "0",
    ]:
        raise ValueError(
            f"Attribute is not collection, but upper bound is {attribute.upper_bound} {context(attribute, cls)}"
        )


@validator
def name_snake_convention(config: Configuration, attribute: ModelAttribute, cls: ModelClass):
    if (
        attribute.name is None
        or not is_lower_snake_case(attribute.name)
        and config.stereotypes.idl_enum not in cls.stereotypes
    ):
        raise ValueError(f"Attribute name has wrong case, expected snake case {context(attribute, cls)}")


@validator
def notes(config: Configuration, attribute: ModelAttribute, cls: ModelClass):
    """Check if attribute has notes/documentation."""
    check_notes_exist(attribute.notes, "Attribute name", context(attribute, cls))


# Spelling validators created using factory to eliminate duplication
_notes_spelling = create_spelling_validator(
    text_extractor=lambda attribute, cls: attribute.notes,
    context_extractor=lambda attribute, cls: context(attribute, cls),
    check_type="notes",
)
_notes_spelling.__name__ = "notes_spelling"
_notes_spelling.__module__ = "eaidl.validation.attribute"
notes_spelling = validator(_notes_spelling)
notes_spelling.__doc__ = "Check spelling in attribute notes/documentation."

_name_spelling = create_spelling_validator(
    text_extractor=lambda attribute, cls: attribute.name,
    context_extractor=lambda attribute, cls: context(attribute, cls),
    check_type="identifiers",
)
_name_spelling.__name__ = "name_spelling"
_name_spelling.__module__ = "eaidl.validation.attribute"
name_spelling = validator(_name_spelling)
name_spelling.__doc__ = "Check spelling in attribute name (parsed from snake_case)."
