"""Reusable validation utilities and helpers.

This module provides common validation functions and factories to eliminate
code duplication across struct.py, attribute.py, and package.py validators.
"""

from typing import Callable, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from eaidl.config import Configuration
    from eaidl.model import ModelClass, ModelAttribute, ModelPackage


# ============================================================================
# Context Helper Functions
# ============================================================================


def get_class_context(cls: "ModelClass") -> str:
    """Get context string for a class."""
    return f"(in {'.'.join(cls.namespace)}.{cls.name})"


def get_attribute_context(attribute: "ModelAttribute", cls: "ModelClass") -> str:
    """Get context string for an attribute."""
    return f"(in {'.'.join(cls.namespace)}.{cls.name}.{attribute.name}:{attribute.type})"


def get_package_context(package: "ModelPackage") -> str:
    """Get context string for a package."""
    return f"(in {'.'.join(package.namespace)})"


# ============================================================================
# Common Validation Helpers
# ============================================================================


def check_experimental_stereotype(stereotypes: list[str], context_str: str, entity_type: str = "") -> None:
    """Check if object has experimental stereotype and raise if found.

    Args:
        stereotypes: List of stereotypes
        context_str: Context string for error message
        entity_type: Type of entity (e.g., "Class", "Attribute", "Package") for error message

    Raises:
        ValueError: If 'experimental' stereotype is found
    """
    if "experimental" in stereotypes:
        if entity_type:
            raise ValueError(f"{entity_type} experimental {context_str}")
        else:
            raise ValueError(f"experimental {context_str}")


def check_notes_exist(notes: Optional[str], entity_name: str, context_str: str) -> None:
    """Check if notes/documentation exists and is not empty.

    Args:
        notes: Notes text to check
        entity_name: Name of the entity (for error message)
        context_str: Context string for error message

    Raises:
        ValueError: If notes are missing or empty
    """
    if notes is None or notes.strip() == "":
        raise ValueError(f"{entity_name} has no description/comment/notes {context_str}")


# ============================================================================
# Spelling Validator Factory
# ============================================================================


def create_spelling_validator(
    text_extractor: Callable,
    context_extractor: Callable,
    check_type: str = "notes",  # "notes" or "identifiers"
    note_description: str = "notes",  # For error messages
):
    """Factory function to create spelling validators.

    This eliminates the duplication of 9 spelling validators across the codebase
    by providing a single factory that creates validators with the same structure
    but different text extraction logic.

    Args:
        text_extractor: Function to extract text to check. Signature depends on context:
                       - For classes: (cls) -> str
                       - For attributes: (attribute, cls) -> str
                       - For packages: (package) -> str or (package) -> list[str]
        context_extractor: Function to get context string. Same signature as text_extractor.
        check_type: Either "notes" or "identifiers" - determines which config flag to check
        note_description: Description for error context (e.g., "notes", "linked note #1")

    Returns:
        A validator function decorated with @validator

    Example:
        >>> # Create a class notes spelling validator
        >>> notes_spelling = create_spelling_validator(
        ...     text_extractor=lambda cls: cls.notes,
        ...     context_extractor=get_class_context,
        ...     check_type="notes"
        ... )
    """
    from .spellcheck import check_spelling, format_spelling_errors

    def spelling_validator(config: "Configuration", **kwargs):
        """Check spelling in text."""
        # Check if spellchecking is enabled
        if not config.spellcheck.enabled:
            return

        # Check if this type of spellchecking is enabled
        if check_type == "notes" and not config.spellcheck.check_notes:
            return
        if check_type == "identifiers" and not config.spellcheck.check_identifiers:
            return

        # Extract text to check
        text = text_extractor(**kwargs)

        # Handle both single strings and lists of texts
        texts_to_check = []
        contexts = []

        if isinstance(text, list):
            # Multiple texts (e.g., linked notes)
            for idx, item in enumerate(text):
                # Handle LinkedNote objects or strings
                if hasattr(item, "content"):
                    if item.content and item.content.strip():
                        texts_to_check.append(item.content)
                        base_context = context_extractor(**kwargs)
                        contexts.append(f"{base_context} - {note_description} #{idx + 1}")
                elif item and item.strip():
                    texts_to_check.append(item)
                    base_context = context_extractor(**kwargs)
                    contexts.append(f"{base_context} - {note_description} #{idx + 1}")
        else:
            # Single text
            if text is None or not text.strip():
                return  # No text to check

            texts_to_check.append(text)
            contexts.append(context_extractor(**kwargs))

        # Check spelling for each text
        for text_item, context_str in zip(texts_to_check, contexts):
            errors = check_spelling(
                text=text_item,
                language=config.spellcheck.language,
                min_word_length=config.spellcheck.min_word_length,
                custom_words=config.spellcheck.custom_words,
            )

            if errors:
                raise ValueError(format_spelling_errors(errors, context_str))

    return spelling_validator


# ============================================================================
# Convenience Functions for Common Patterns
# ============================================================================


def validate_class_experimental(config: "Configuration", cls: "ModelClass") -> None:
    """Check if class has experimental stereotype.

    This can be used directly in validators or as a helper.
    """
    check_experimental_stereotype(cls.stereotypes, get_class_context(cls))


def validate_class_notes(config: "Configuration", cls: "ModelClass") -> None:
    """Check if class has notes.

    This can be used directly in validators or as a helper.
    """
    check_notes_exist(cls.notes, f"Class '{cls.name}'", get_class_context(cls))


def validate_attribute_experimental(config: "Configuration", attribute: "ModelAttribute", cls: "ModelClass") -> None:
    """Check if attribute has experimental stereotype."""
    check_experimental_stereotype(attribute.stereotypes, get_attribute_context(attribute, cls))


def validate_attribute_notes(config: "Configuration", attribute: "ModelAttribute", cls: "ModelClass") -> None:
    """Check if attribute has notes."""
    check_notes_exist(attribute.notes, "Attribute name", get_attribute_context(attribute, cls))


def validate_package_experimental(config: "Configuration", package: "ModelPackage") -> None:
    """Check if package has experimental stereotype."""
    check_experimental_stereotype(
        package.stereotypes, f"Package {package.name} is experimental {get_package_context(package)}"
    )


def validate_package_notes(config: "Configuration", package: "ModelPackage") -> None:
    """Check if package has notes."""
    check_notes_exist(package.notes, f"Package {package.name}", get_package_context(package))
