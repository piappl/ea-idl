"""Spellchecking utilities for EA-IDL validation."""

import logging
import re
from typing import List, Set, Optional, Dict, Protocol, runtime_checkable

log = logging.getLogger(__name__)

# Singleton backend instance (lazy initialized)
_backend_instance: Optional["SpellBackend"] = None
_custom_words: Set[str] = set()

# Built-in technical terms (always allowed)
TECHNICAL_TERMS = {
    # IDL keywords
    "struct",
    "union",
    "enum",
    "typedef",
    "module",
    "sequence",
    "string",
    "boolean",
    "octet",
    "char",
    "wchar",
    "short",
    "long",
    "float",
    "double",
    "annotation",
    "readonly",
    "attribute",
    "any",
    "component",
    "const",
    "context",
    "custom",
    "default",
    "exception",
    "factory",
    "fixed",
    "inout",
    "interface",
    "native",
    "oneway",
    "private",
    "public",
    "raises",
    "supports",
    "switch",
    "truncatable",
    "unsigned",
    "valuetype",
    "void",
    "wstring",
    # EA/modeling terms
    "stereotype",
    "stereotypes",
    "generalization",
    "association",
    "aggregation",
    "connector",
    "cardinality",
    "multiplicity",
    # Common abbreviations (lowercase versions)
    "uuid",
    "guid",
    "api",
    "url",
    "http",
    "https",
    "xml",
    "json",
    "sql",
    "db",
    "id",
    "pk",
    "fk",
    "dto",
    "cfg",
    "tmp",
    "attr",
    "idl",
    "qea",
    # Common data terms
    "timestamp",
    "iso",
    "utc",
    # Measurement and units
    "uint",
    "int",
}


@runtime_checkable
class SpellBackend(Protocol):
    """Protocol for spellcheck backends."""

    def check(self, word: str) -> bool:
        """Return True if the word is correctly spelled."""
        ...

    def suggest(self, word: str) -> List[str]:
        """Return spelling suggestions for a word."""
        ...

    def add_words(self, words: Set[str]) -> None:
        """Add custom words to the dictionary."""
        ...

    def unknown(self, words: List[str]) -> Set[str]:
        """Return the set of words not recognized by the spellchecker."""
        ...


class PySpellCheckerBackend:
    """Backend using pyspellchecker library."""

    def __init__(self, language: str = "en"):
        from spellchecker import SpellChecker

        self._checker = SpellChecker(language=language)

    def check(self, word: str) -> bool:
        return len(self._checker.unknown([word])) == 0

    def suggest(self, word: str) -> List[str]:
        candidates = self._checker.candidates(word)
        return list(candidates)[:5] if candidates else []

    def add_words(self, words: Set[str]) -> None:
        self._checker.word_frequency.load_words(words)

    def unknown(self, words: List[str]) -> Set[str]:
        return self._checker.unknown(words)


class EnchantBackend:
    """Backend using pyenchant library (supports en_US, en_GB, etc.)."""

    def __init__(self, language: str = "en_US"):
        try:
            import enchant
        except ImportError:
            raise ImportError(
                "pyenchant is required for the 'enchant' backend. "
                "Install it with: pip install eaidl[enchant]\n"
                "System dependency: libenchant-2-dev (apt) or enchant (brew)"
            )
        self._dict = enchant.Dict(language)
        self._custom_words: Set[str] = set()

    def check(self, word: str) -> bool:
        return word.lower() in self._custom_words or self._dict.check(word)

    def suggest(self, word: str) -> List[str]:
        return self._dict.suggest(word)[:5]

    def add_words(self, words: Set[str]) -> None:
        self._custom_words.update(w.lower() for w in words)

    def unknown(self, words: List[str]) -> Set[str]:
        return {w for w in words if not self.check(w)}


def get_backend(backend: str = "pyspellchecker", language: str = "en", custom_words: List[str] = None) -> SpellBackend:
    """Get or create singleton spellcheck backend instance."""
    global _backend_instance, _custom_words

    if _backend_instance is not None:
        current_type = "enchant" if isinstance(_backend_instance, EnchantBackend) else "pyspellchecker"
        if backend != current_type:
            log.warning(
                "Spellcheck backend already initialized as '%s', ignoring request for '%s'. "
                "Call reset_backend() first to switch backends.",
                current_type,
                backend,
            )

    if _backend_instance is None:
        log.debug("Initializing spellcheck backend=%s (language: %s)", backend, language)

        if backend == "enchant":
            _backend_instance = EnchantBackend(language=language)
        else:
            _backend_instance = PySpellCheckerBackend(language=language)

        # Add built-in technical terms
        _backend_instance.add_words(TECHNICAL_TERMS)
        _custom_words.update(TECHNICAL_TERMS)
        log.debug("Loaded %d built-in technical terms", len(TECHNICAL_TERMS))

    # Add custom words from config if provided
    if custom_words:
        new_custom = {w.lower() for w in custom_words if w} - _custom_words
        if new_custom:
            _backend_instance.add_words(new_custom)
            _custom_words.update(new_custom)
            log.debug("Loaded %d custom words from configuration", len(new_custom))

    return _backend_instance


def get_spellchecker(language: str = "en", custom_words: List[str] = None) -> "SpellBackend":
    """Legacy wrapper — delegates to get_backend with pyspellchecker."""
    return get_backend(backend="pyspellchecker", language=language, custom_words=custom_words)


def reset_backend() -> None:
    """Reset the singleton backend instance. Used for testing."""
    global _backend_instance, _custom_words
    _backend_instance = None
    _custom_words = set()


def add_learned_words(words: Set[str]) -> None:
    """Add words learned from the model to the spellchecker."""
    global _backend_instance, _custom_words

    if _backend_instance is not None:
        new_words = {w.lower() for w in words if w} - _custom_words
        if new_words:
            _backend_instance.add_words(new_words)
            _custom_words.update(new_words)
            log.debug("Auto-learned %d words from model", len(new_words))


def split_identifier(word: str) -> List[str]:
    """
    Split identifier into parts (handles camelCase, PascalCase, snake_case).

    Examples:
        MessageHeader -> ["Message", "Header"]
        message_type -> ["message", "type"]
        HTTPServer -> ["HTTP", "Server"]
        snake_case_name -> ["snake", "case", "name"]
        CQL2Expression -> ["CQL", "2", "Expression"]
        UTF8String -> ["UTF", "8", "String"]
    """
    # First split by underscore/hyphen
    parts = re.split(r"[_-]", word)

    # Then split camelCase within each part
    result = []
    for part in parts:
        if not part:
            continue

        # Insert space before/after numbers: CQL2Expression -> CQL 2 Expression
        spaced = re.sub(r"([a-zA-Z])(\d+)", r"\1 \2", part)
        spaced = re.sub(r"(\d+)([a-zA-Z])", r"\1 \2", spaced)

        # Insert space before uppercase letters (except first)
        # MessageType -> Message Type
        spaced = re.sub(r"([a-z])([A-Z])", r"\1 \2", spaced)

        # Handle consecutive caps: HTTPServer -> HTTP Server
        spaced = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", spaced)

        # Split and add to result
        result.extend(spaced.split())

    return result


def extract_words(text: str, min_word_length: int = 3, ignore_patterns: List[str] = None) -> List[str]:
    """Extract words from text for spellchecking."""
    if not text:
        return []

    if ignore_patterns is None:
        ignore_patterns = [
            r"https?://[^\s]+",  # URLs
            r"`[^`]+`",  # Inline code
            r"\b[A-Z]{2,}\b",  # Acronyms
        ]

    # Apply ignore patterns first
    for pattern in ignore_patterns:
        text = re.sub(pattern, " ", text)

    # Split into words (alphanumeric + underscore/hyphen/apostrophe)
    # Apostrophes are included to preserve contractions (don't, can't) and possessives (Allen's)
    words = re.findall(r"[a-zA-Z][a-zA-Z0-9_'-]*", text)

    # Filter and process words
    filtered = []
    for word in words:
        # Skip if too short
        if len(word) < min_word_length:
            continue

        # Skip if all caps (acronym)
        if word.isupper() and len(word) >= 2:
            continue

        # Skip if single letter
        if len(word) == 1:
            continue

        # Skip if looks like number with letters (e.g., "3d", "4x")
        if re.match(r"^\d+[a-z]+$", word.lower()):
            continue

        # If word contains apostrophe, it's a natural language word (contraction/possessive)
        # Don't split it - add as-is
        if "'" in word:
            filtered.append(word.lower())
            continue

        # Handle camelCase/PascalCase - split into parts
        parts = split_identifier(word)
        for part in parts:
            # Skip pure numbers
            if part.isdigit():
                continue
            if len(part) >= min_word_length and not part.isupper():
                filtered.append(part.lower())

    return filtered


def check_spelling(
    text: str,
    language: str = "en",
    min_word_length: int = 3,
    custom_words: List[str] = None,
    backend: str = "pyspellchecker",
) -> List[Dict[str, any]]:
    """Check spelling in text and return list of errors.

    Args:
        text: Text to check
        language: Language code (default: "en")
        min_word_length: Minimum word length to check (default: 3)
        custom_words: Additional custom words to allow (default: None)
        backend: Spellcheck backend to use (default: "pyspellchecker")

    Returns:
        List of dicts with keys: 'word', 'suggestions'
    """
    if not text or not text.strip():
        return []

    checker = get_backend(backend, language, custom_words)
    words = extract_words(text, min_word_length)

    if not words:
        return []

    # Find misspelled words
    misspelled = checker.unknown(words)

    if not misspelled:
        return []

    # Get suggestions for each misspelled word (deduplicate first)
    errors = []
    seen = set()
    for word in misspelled:
        if word not in seen:
            seen.add(word)
            suggestions = checker.suggest(word)
            errors.append({"word": word, "suggestions": suggestions})

    return errors


def format_spelling_errors(errors: List[Dict], context_str: str) -> str:
    """Format spelling errors into a readable message."""
    if not errors:
        return ""

    lines = [f"Spelling errors found {context_str}:"]
    for err in errors:
        word = err["word"]
        suggestions = err.get("suggestions", [])
        if suggestions:
            sugg_str = ", ".join(f"'{s}'" for s in suggestions[:3])
            lines.append(f"  - '{word}' (suggestions: {sugg_str})")
        else:
            lines.append(f"  - '{word}' (no suggestions)")

    return "\n".join(lines)
