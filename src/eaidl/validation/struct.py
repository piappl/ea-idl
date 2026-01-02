from eaidl.config import Configuration
from eaidl.model import ModelClass
from eaidl.utils import is_camel_case
from .base import validator, RESERVED_NAMES
from .spellcheck import check_spelling, format_spelling_errors
import re


def context(cls: ModelClass) -> str:
    return f"(in {".".join(cls.namespace)}.{cls.name})"


@validator
def name_for_reserved_worlds(config: Configuration, cls: ModelClass) -> None:
    if cls.name in RESERVED_NAMES:
        raise ValueError(f"Class name is on reserved world list {context(cls)}")


@validator
def name_camel_convention(config: Configuration, cls: ModelClass):
    if not is_camel_case(cls.name):
        raise ValueError(f"Class name has wrong case, expected camel case {context(cls)}")


@validator
def is_experimental(config: Configuration, cls: ModelClass):
    if "experimental" in cls.stereotypes:
        raise ValueError(f"Class experimental {context(cls)}")


@validator
def stereotypes(config: Configuration, cls: ModelClass):
    # Check if we have one of proper stereotypes on all P7
    if config.stereotypes.main_class in cls.stereotypes:
        count = 0
        if config.stereotypes.idl_union in cls.stereotypes:
            if cls.is_union is not True:
                raise ValueError(f"Class doesn't have proper is_union flag {context(cls)}")
            count += 1
        if config.stereotypes.idl_struct in cls.stereotypes:
            if cls.is_struct is not True:
                raise ValueError(f"Class doesn't have proper is_struct flag {context(cls)}")
            count += 1
        if config.stereotypes.idl_enum in cls.stereotypes:
            if cls.is_enum is not True:
                raise ValueError(f"Class doesn't have proper is_enum flag {context(cls)}")
            count += 1
        if config.stereotypes.idl_typedef in cls.stereotypes:
            if cls.is_typedef is not True:
                raise ValueError(f"Class doesn't have proper is_typedef flag {context(cls)}")
            count += 1
        if config.stereotypes.idl_map in cls.stereotypes:
            if cls.is_map is not True:
                raise ValueError(f"Class doesn't have proper is_map flag {context(cls)}")
            count += 1
        if count != 1:
            raise ValueError(f"Class doesn't have proper stereotypes {cls.stereotypes} {context(cls)}")


@validator
def enum_prefix(config: Configuration, cls: ModelClass):
    # We prefix enumerations (to make sure those are unique)
    if config.stereotypes.main_class in cls.stereotypes and config.stereotypes.idl_enum in cls.stereotypes:
        for attribute in cls.attributes:
            if attribute.name is None:
                raise ValueError(f"No name in enumeration {cls.name} attribute {context(cls)}")
            if not attribute.name.startswith(cls.name):
                raise ValueError(f"No prefix in enumeration {attribute.name} {cls.name} attribute {context(cls)}")


@validator
def notes(config: Configuration, cls: ModelClass):
    if cls.notes is None or cls.notes.strip() == "":
        raise ValueError(f"Class '{cls.name}' has no description/comment/notes {context(cls)}")


@validator
def enum_attributes(config: Configuration, cls: ModelClass):
    if config.stereotypes.idl_enum not in cls.stereotypes:
        # We run this only for enums
        return

    # Check if enumeration attributes have same type
    types = set([attr.type for attr in cls.attributes])
    if len(types) != 1:
        # We should have a set (which has only unique items) with none
        raise ValueError(f"Enumeration needs to have no types {types} {context(cls)}")
    # Check default values (if set) are unique
    values = []
    for attr in cls.attributes:
        default = attr.properties.get("default")
        if default is None:
            continue
        values.append(default.value)
    count = len(cls.attributes)
    if len(values) != 0 and count != len(set(values)):
        raise ValueError(
            f"We expected to have values that match attributes numbers and all unique {context(cls)} {values}"
        )


@validator
def notes_spelling(config: Configuration, cls: ModelClass):
    """Check spelling in class notes/documentation."""
    if not config.spellcheck.enabled or not config.spellcheck.check_notes:
        return

    if cls.notes is None or cls.notes.strip() == "":
        return  # No notes to check

    errors = check_spelling(
        text=cls.notes,
        language=config.spellcheck.language,
        min_word_length=config.spellcheck.min_word_length,
        custom_words=config.spellcheck.custom_words,
    )

    if errors:
        raise ValueError(format_spelling_errors(errors, context(cls)))


@validator
def name_spelling(config: Configuration, cls: ModelClass):
    """Check spelling in class name (parsed from PascalCase)."""
    if not config.spellcheck.enabled or not config.spellcheck.check_identifiers:
        return

    if cls.name is None:
        return

    errors = check_spelling(
        text=cls.name,
        language=config.spellcheck.language,
        min_word_length=config.spellcheck.min_word_length,
        custom_words=config.spellcheck.custom_words,
    )

    if errors:
        raise ValueError(format_spelling_errors(errors, context(cls)))


@validator
def linked_notes_spelling(config: Configuration, cls: ModelClass):
    """Check spelling in linked notes (notes connected via NoteLink)."""
    if not config.spellcheck.enabled or not config.spellcheck.check_notes:
        return

    if not cls.linked_notes:
        return  # No linked notes to check

    for idx, note in enumerate(cls.linked_notes):
        if not note or not note.strip():
            continue

        errors = check_spelling(
            text=note,
            language=config.spellcheck.language,
            min_word_length=config.spellcheck.min_word_length,
            custom_words=config.spellcheck.custom_words,
        )

        if errors:
            ctx = f"{context(cls)} - linked note #{idx + 1}"
            raise ValueError(format_spelling_errors(errors, ctx))


@validator
def recursive_type_uses_sequence(config: Configuration, cls: ModelClass):
    """
    Ensure self-referencing struct attributes use sequences (IDL requirement).

    IDL does not support direct self-reference without sequence<>.
    Note: This only checks SELF-reference. Mutual recursion (A → B → A)
    is handled by cycle detection and can have direct references as long
    as at least one edge in the cycle uses a sequence.
    """
    if not config.allow_recursive_structs:
        return  # Skip if recursion support is disabled

    if not cls.is_struct:
        return  # Only applies to structs (unions can self-reference via discriminator)

    for attr in cls.attributes:
        # Check if attribute type references the parent struct (self-reference)
        if attr.type == cls.name and attr.namespace == cls.namespace:
            if not attr.is_collection:
                raise ValueError(
                    f"Self-referencing attribute '{cls.full_name}.{attr.name}' must be a sequence. "
                    f"IDL does not support direct self-reference in structs without sequence<>. {context(cls)}"
                )


@validator
def typedef_has_association(config: Configuration, cls: ModelClass) -> None:
    """
    Validate that typedefs have Association connectors to their referenced types.

    Best practice in Enterprise Architect is to model typedef relationships using
    Association connectors, not just the genlinks field. This validator checks that:
    1. The typedef has a parent_type defined (from genlinks)
    2. If parent_type references a non-primitive type, an Association connector exists
    3. The Association is indicated by a non-empty depends_on list

    This encourages proper EA modeling and makes dependencies explicit in the model.
    """
    if not cls.is_typedef:
        return  # Only applies to typedefs

    if not cls.parent_type:
        # Typedef without parent_type - this is a modeling error caught elsewhere
        return

    # Extract the referenced type name from parent_type
    # Handle cases like "sequence<Node>", "map<string, Node>", or "Node"
    ref_type_name = None

    # Try to extract from sequence<...>
    match = re.search(r"sequence<(.+?)>", cls.parent_type)
    if match:
        ref_type_name = match.group(1).strip()
    else:
        # Try to extract from map<key, value>
        match = re.search(r"map<[^,]+,\s*(.+?)>", cls.parent_type)
        if match:
            ref_type_name = match.group(1).strip()
        else:
            # Direct type reference (not a template)
            ref_type_name = cls.parent_type.strip()

    # Check if the referenced type is a primitive
    if ref_type_name and config.is_primitive_type(ref_type_name):
        # Primitive types don't need Association connectors
        return

    # If we're referencing a non-primitive type, we should have a dependency
    if ref_type_name and not cls.depends_on:
        raise ValueError(
            f"Typedef '{cls.full_name}' references type '{ref_type_name}' but has no Association connector. "
            f"Add an Association from the typedef to the referenced type in Enterprise Architect. {context(cls)}"
        )
