from eaidl.config import Configuration
from eaidl.model import ModelAttribute, ModelClass
from eaidl.utils import is_lower_snake_case
from .base import validator, RESERVED_NAMES
from .spellcheck import check_spelling, format_spelling_errors


def context(attribute: ModelAttribute, cls: ModelClass) -> str:
    return f"(in {".".join(cls.namespace)}.{cls.name}.{attribute.name}:{attribute.type})"


@validator
def name_for_reserved_worlds(config: Configuration, attribute: ModelAttribute, cls: ModelClass) -> None:
    """Check if parsed attribute name is not a reserved name."""
    if attribute.name in RESERVED_NAMES:
        raise ValueError(f"Attribute name '{attribute.name}' is on reserved world list {context(attribute, cls)}")


@validator
def connector_leads_to_type(config: Configuration, attribute: ModelAttribute, cls: ModelClass):
    """Check connection type.

    In normal condition we weed connector for all attributes, leading to a type of this attribute.

    Exceptions are for enumeration and attributes that are of primitive types.
    """
    if (
        attribute.connector is None
        and config.stereotypes.idl_enum not in cls.stereotypes
        and attribute.type not in config.primitive_types
    ):
        raise ValueError(f"No connector found for attribute {context(attribute, cls)}")


@validator
def is_experimental(config: Configuration, attribute: ModelAttribute, cls: ModelClass):
    if "experimental" in attribute.stereotypes:
        raise ValueError(f"Attribute experimental {context(attribute, cls)}")


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
    if attribute.notes is None or attribute.notes.strip() == "":
        raise ValueError(f"Attribute name has no description/comment/notes {context(attribute, cls)}")


@validator
def notes_spelling(config: Configuration, attribute: ModelAttribute, cls: ModelClass):
    """Check spelling in attribute notes/documentation."""
    if not config.spellcheck.enabled or not config.spellcheck.check_notes:
        return

    if attribute.notes is None or attribute.notes.strip() == "":
        return  # No notes to check

    errors = check_spelling(
        text=attribute.notes,
        language=config.spellcheck.language,
        min_word_length=config.spellcheck.min_word_length,
        custom_words=config.spellcheck.custom_words,
    )

    if errors:
        raise ValueError(format_spelling_errors(errors, context(attribute, cls)))


@validator
def name_spelling(config: Configuration, attribute: ModelAttribute, cls: ModelClass):
    """Check spelling in attribute name (parsed from snake_case)."""
    if not config.spellcheck.enabled or not config.spellcheck.check_identifiers:
        return

    if attribute.name is None:
        return

    errors = check_spelling(
        text=attribute.name,
        language=config.spellcheck.language,
        min_word_length=config.spellcheck.min_word_length,
        custom_words=config.spellcheck.custom_words,
    )

    if errors:
        raise ValueError(format_spelling_errors(errors, context(attribute, cls)))
