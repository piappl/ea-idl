from eaidl.config import Configuration
from eaidl.model import ModelPackage
from eaidl.utils import is_lower_snake_case
from .base import validator
from .validators import (
    get_package_context,
    check_notes_exist,
    create_spelling_validator,
)


def context(package: ModelPackage) -> str:
    """Get context string for package (delegates to validators.get_package_context)."""
    return get_package_context(package)


@validator
def name_snake_convention(config: Configuration, package: ModelPackage):
    if not is_lower_snake_case(package.name):
        raise ValueError(f"Package {package.name} has wrong case, expected lower snake case: {context(package)}")


@validator
def stereotypes(config: Configuration, package: ModelPackage):
    if config.stereotypes.package not in package.stereotypes:
        raise ValueError(
            f"Package {package.name} has wrong stereotypes, found {package.stereotypes} expected {config.stereotypes.package} {context(package)}"
        )


@validator
def is_experimental(config: Configuration, package: ModelPackage):
    """Check if package has experimental stereotype."""
    if "experimental" in package.stereotypes:
        raise ValueError(f"Package {package.name} is experimental {context(package)}")


@validator
def notes(config: Configuration, package: ModelPackage):
    """Check if package has notes/documentation."""
    check_notes_exist(package.notes, f"Package {package.name}", context(package))


# Spelling validators created using factory to eliminate duplication
_notes_spelling = create_spelling_validator(
    text_extractor=lambda package: package.notes, context_extractor=lambda package: context(package), check_type="notes"
)
_notes_spelling.__name__ = "notes_spelling"
_notes_spelling.__module__ = "eaidl.validation.package"
notes_spelling = validator(_notes_spelling)
notes_spelling.__doc__ = "Check spelling in package notes/documentation."

_name_spelling = create_spelling_validator(
    text_extractor=lambda package: package.name,
    context_extractor=lambda package: context(package),
    check_type="identifiers",
)
_name_spelling.__name__ = "name_spelling"
_name_spelling.__module__ = "eaidl.validation.package"
name_spelling = validator(_name_spelling)
name_spelling.__doc__ = "Check spelling in package name (parsed from snake_case)."

_unlinked_notes_spelling = create_spelling_validator(
    text_extractor=lambda package: package.unlinked_notes,
    context_extractor=lambda package: context(package),
    check_type="notes",
    note_description="unlinked note",
)
_unlinked_notes_spelling.__name__ = "unlinked_notes_spelling"
_unlinked_notes_spelling.__module__ = "eaidl.validation.package"
unlinked_notes_spelling = validator(_unlinked_notes_spelling)
unlinked_notes_spelling.__doc__ = "Check spelling in unlinked notes (notes not connected to any object)."
