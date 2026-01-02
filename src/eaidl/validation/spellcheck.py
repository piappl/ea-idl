"""Spellchecking utilities for EA-IDL validation."""

import logging
import re
from typing import List, Set, Optional, Dict
from spellchecker import SpellChecker

log = logging.getLogger(__name__)

# Singleton spellchecker instance (lazy initialized)
_spellchecker_instance: Optional[SpellChecker] = None
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


def get_spellchecker(language: str = "en", custom_words: List[str] = None) -> SpellChecker:
    """Get or create singleton spellchecker instance."""
    global _spellchecker_instance, _custom_words

    if _spellchecker_instance is None:
        log.debug("Initializing spellchecker (language: %s)", language)
        _spellchecker_instance = SpellChecker(language=language)

        # Add built-in technical terms
        _spellchecker_instance.word_frequency.load_words(TECHNICAL_TERMS)
        _custom_words.update(TECHNICAL_TERMS)
        log.debug("Loaded %d built-in technical terms", len(TECHNICAL_TERMS))

    # Add custom words from config if provided
    if custom_words:
        new_custom = {w.lower() for w in custom_words if w} - _custom_words
        if new_custom:
            _spellchecker_instance.word_frequency.load_words(new_custom)
            _custom_words.update(new_custom)
            log.debug("Loaded %d custom words from configuration", len(new_custom))

    return _spellchecker_instance


def add_learned_words(words: Set[str]) -> None:
    """Add words learned from the model to the spellchecker."""
    global _spellchecker_instance, _custom_words

    if _spellchecker_instance is not None:
        new_words = {w.lower() for w in words if w} - _custom_words
        if new_words:
            _spellchecker_instance.word_frequency.load_words(new_words)
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
    """
    # First split by underscore/hyphen
    parts = re.split(r"[_-]", word)

    # Then split camelCase within each part
    result = []
    for part in parts:
        if not part:
            continue

        # Insert space before uppercase letters (except first)
        # MessageType -> Message Type
        spaced = re.sub(r"([a-z])([A-Z])", r"\1 \2", part)

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
            if len(part) >= min_word_length and not part.isupper():
                filtered.append(part.lower())

    return filtered


def check_spelling(
    text: str, language: str = "en", min_word_length: int = 3, custom_words: List[str] = None
) -> List[Dict[str, any]]:
    """
    Check spelling in text and return list of errors.

    Args:
        text: Text to check
        language: Language code (default: "en")
        min_word_length: Minimum word length to check (default: 3)
        custom_words: Additional custom words to allow (default: None)

    Returns:
        List of dicts with keys: 'word', 'suggestions'
    """
    if not text or not text.strip():
        return []

    spellchecker = get_spellchecker(language, custom_words)
    words = extract_words(text, min_word_length)

    if not words:
        return []

    # Find misspelled words
    misspelled = spellchecker.unknown(words)

    if not misspelled:
        return []

    # Get suggestions for each misspelled word (deduplicate first)
    errors = []
    seen = set()
    for word in misspelled:
        if word not in seen:
            seen.add(word)
            suggestions = spellchecker.candidates(word)
            errors.append({"word": word, "suggestions": list(suggestions)[:5] if suggestions else []})

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
