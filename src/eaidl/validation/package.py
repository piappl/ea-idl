from eaidl.config import Configuration
from eaidl.model import ModelPackage
from eaidl.utils import is_lower_snake_case
from .base import validator
from .spellcheck import check_spelling, format_spelling_errors


def context(package: ModelPackage) -> str:
    return f"(in {".".join(package.namespace)})"


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
    if "experimental" in package.stereotypes:
        raise ValueError(f"Package {package.name} is experimental {context(package)}")


@validator
def notes(config: Configuration, package: ModelPackage):
    if package.notes is None or package.notes.strip() == "":
        raise ValueError(f"Package {package.name} has no description/comment/notes {context(package)}")


@validator
def notes_spelling(config: Configuration, package: ModelPackage):
    """Check spelling in package notes/documentation."""
    if not config.spellcheck.enabled or not config.spellcheck.check_notes:
        return

    if package.notes is None or package.notes.strip() == "":
        return  # No notes to check

    errors = check_spelling(
        text=package.notes,
        language=config.spellcheck.language,
        min_word_length=config.spellcheck.min_word_length,
        custom_words=config.spellcheck.custom_words,
    )

    if errors:
        raise ValueError(format_spelling_errors(errors, context(package)))


@validator
def name_spelling(config: Configuration, package: ModelPackage):
    """Check spelling in package name (parsed from snake_case)."""
    if not config.spellcheck.enabled or not config.spellcheck.check_identifiers:
        return

    if package.name is None:
        return

    errors = check_spelling(
        text=package.name,
        language=config.spellcheck.language,
        min_word_length=config.spellcheck.min_word_length,
        custom_words=config.spellcheck.custom_words,
    )

    if errors:
        raise ValueError(format_spelling_errors(errors, context(package)))


@validator
def unlinked_notes_spelling(config: Configuration, package: ModelPackage):
    """Check spelling in unlinked notes (notes not connected to any object)."""
    if not config.spellcheck.enabled or not config.spellcheck.check_notes:
        return

    if not package.unlinked_notes:
        return  # No unlinked notes to check

    for idx, note in enumerate(package.unlinked_notes):
        if not note or not note.strip():
            continue

        errors = check_spelling(
            text=note,
            language=config.spellcheck.language,
            min_word_length=config.spellcheck.min_word_length,
            custom_words=config.spellcheck.custom_words,
        )

        if errors:
            ctx = f"{context(package)} - unlinked note #{idx + 1}"
            raise ValueError(format_spelling_errors(errors, ctx))
