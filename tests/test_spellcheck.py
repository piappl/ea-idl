"""Tests for spellchecking functionality."""

import pytest
from eaidl.config import Configuration, ConfigurationSpellcheck
from eaidl.model import ModelAttribute, ModelClass, ModelPackage
from eaidl.validation.spellcheck import (
    extract_words,
    split_identifier,
    check_spelling,
    format_spelling_errors,
)
from eaidl.validation import attribute, struct, package


def test_split_identifier_camelCase():
    """Test splitting camelCase identifiers."""
    assert split_identifier("MessageHeader") == ["Message", "Header"]
    assert split_identifier("testVariable") == ["test", "Variable"]


def test_split_identifier_snake_case():
    """Test splitting snake_case identifiers."""
    assert split_identifier("message_type") == ["message", "type"]
    assert split_identifier("snake_case_name") == ["snake", "case", "name"]
    assert split_identifier("test_var") == ["test", "var"]


def test_split_identifier_consecutive_caps():
    """Test splitting identifiers with consecutive capitals."""
    assert split_identifier("HTTPServer") == ["HTTP", "Server"]
    assert split_identifier("XMLParser") == ["XML", "Parser"]
    assert split_identifier("URLConnection") == ["URL", "Connection"]


def test_split_identifier_mixed():
    """Test splitting mixed identifiers."""
    assert split_identifier("HTTP_Server") == ["HTTP", "Server"]
    assert split_identifier("test-hyphen") == ["test", "hyphen"]


def test_split_identifier_with_numbers():
    """Test splitting identifiers with numbers."""
    assert split_identifier("CQL2Expression") == ["CQL", "2", "Expression"]
    assert split_identifier("HTTP2Server") == ["HTTP", "2", "Server"]
    assert split_identifier("Base64Encoder") == ["Base", "64", "Encoder"]
    assert split_identifier("UTF8String") == ["UTF", "8", "String"]
    assert split_identifier("MD5Hash") == ["MD", "5", "Hash"]


def test_extract_words_basic():
    """Test basic word extraction."""
    config_spell = ConfigurationSpellcheck()
    text = "This is a test with some words"
    words = extract_words(text, config_spell.min_word_length)
    assert "this" in words
    assert "test" in words
    assert "some" in words
    assert "words" in words


def test_extract_words_ignores_short():
    """Test that short words are ignored."""
    text = "This is a test"
    words = extract_words(text, min_word_length=3)
    # "is" and "a" should be filtered out (length < 3)
    assert "is" not in words
    assert len([w for w in words if w == "a"]) == 0


def test_extract_words_ignores_acronyms():
    """Test that all-caps acronyms are ignored."""
    text = "The HTTP and XML protocols"
    words = extract_words(text, min_word_length=3)
    # HTTP and XML are all-caps, should be ignored
    assert "http" not in words
    assert "xml" not in words
    # But other words should be present
    assert "the" in words
    assert "protocols" in words


def test_extract_words_splits_identifiers():
    """Test that identifiers are split correctly."""
    text = "MessageHeader and snake_case_var"
    words = extract_words(text, min_word_length=3)
    # MessageHeader should be split
    assert "message" in words
    assert "header" in words
    # snake_case_var should be split
    assert "snake" in words
    assert "case" in words
    assert "var" in words


def test_check_spelling_correct():
    """Test spellcheck with correctly spelled text."""
    text = "This is correctly spelled text"
    errors = check_spelling(text)
    assert len(errors) == 0


def test_check_spelling_with_errors():
    """Test spellcheck with misspellings."""
    text = "This has incorect speling"
    errors = check_spelling(text)
    assert len(errors) == 2
    error_words = [e["word"] for e in errors]
    assert "incorect" in error_words
    assert "speling" in error_words


def test_check_spelling_suggestions():
    """Test that spelling errors include suggestions."""
    text = "This has incorect speling"
    errors = check_spelling(text)
    for error in errors:
        assert "suggestions" in error
        # Should have at least one suggestion
        assert isinstance(error["suggestions"], list)


def test_check_spelling_technical_terms():
    """Test that technical terms are allowed."""
    text = "struct with enum and typedef for uuid and guid"
    errors = check_spelling(text)
    # All these are technical terms, should have no errors
    assert len(errors) == 0


def test_check_spelling_custom_terms():
    """Test that technical terms from TECHNICAL_TERMS are allowed."""
    # Test all technical terms
    for term in ["struct", "union", "enum", "typedef", "stereotype", "uuid", "guid", "json", "xml"]:
        text = f"This uses {term} here"
        errors = check_spelling(text)
        # Should not flag the technical term
        error_words = [e["word"] for e in errors]
        assert term not in error_words


def test_format_spelling_errors():
    """Test error message formatting."""
    errors = [{"word": "teh", "suggestions": ["the", "tea"]}, {"word": "speling", "suggestions": ["spelling"]}]
    message = format_spelling_errors(errors, "(in test.Class.attr)")
    assert "Spelling errors found (in test.Class.attr):" in message
    assert "'teh'" in message
    assert "'the'" in message
    assert "'speling'" in message


def m_attr(name="test", notes=None):
    """Helper to create ModelAttribute for testing."""
    return ModelAttribute(name=name, alias=name, attribute_id=1, guid="test-guid", notes=notes)


def m_class(name="TestClass", notes=None):
    """Helper to create ModelClass for testing."""
    return ModelClass(name=name, object_id=1, notes=notes)


def m_package(name="test_package", notes=None):
    """Helper to create ModelPackage for testing."""
    return ModelPackage(name=name, package_id=1, object_id=1, guid="test-pkg-guid", notes=notes)


def test_attribute_notes_spelling_pass():
    """Test attribute notes validator with correct spelling."""
    config = Configuration(
        spellcheck=ConfigurationSpellcheck(enabled=True), validators_warn=["attribute.notes_spelling"]
    )
    attr = m_attr(name="test_attr", notes="This is correctly spelled documentation")
    cls = m_class()

    # Should not raise
    attribute.notes_spelling(config, attribute=attr, cls=cls)


def test_attribute_notes_spelling_fail():
    """Test attribute notes validator with misspellings."""
    config = Configuration(
        spellcheck=ConfigurationSpellcheck(enabled=True), validators_fail=["attribute.notes_spelling"]
    )
    attr = m_attr(name="test_attr", notes="This has mispeled words")
    cls = m_class()

    with pytest.raises(ValueError, match="Spelling errors"):
        attribute.notes_spelling(config, attribute=attr, cls=cls)


def test_attribute_notes_spelling_disabled():
    """Test that notes spellcheck is skipped when disabled."""
    config = Configuration(
        spellcheck=ConfigurationSpellcheck(enabled=False), validators_warn=["attribute.notes_spelling"]
    )
    attr = m_attr(name="test_attr", notes="This has mispeled words")
    cls = m_class()

    # Should not raise when disabled
    attribute.notes_spelling(config, attribute=attr, cls=cls)


def test_attribute_notes_spelling_check_notes_disabled():
    """Test that notes spellcheck is skipped when check_notes is False."""
    config = Configuration(
        spellcheck=ConfigurationSpellcheck(enabled=True, check_notes=False),
        validators_warn=["attribute.notes_spelling"],
    )
    attr = m_attr(name="test_attr", notes="This has mispeled words")
    cls = m_class()

    # Should not raise when check_notes is False
    attribute.notes_spelling(config, attribute=attr, cls=cls)


def test_attribute_name_spelling_pass():
    """Test attribute name validator with correct spelling."""
    config = Configuration(
        spellcheck=ConfigurationSpellcheck(enabled=True, check_identifiers=True),
        validators_warn=["attribute.name_spelling"],
    )
    attr = m_attr(name="test_variable")
    cls = m_class()

    # Should not raise - "test" and "variable" are both valid
    attribute.name_spelling(config, attribute=attr, cls=cls)


def test_attribute_name_spelling_fail():
    """Test attribute name validator with misspellings."""
    config = Configuration(
        spellcheck=ConfigurationSpellcheck(enabled=True, check_identifiers=True),
        validators_fail=["attribute.name_spelling"],
    )
    attr = m_attr(name="test_mispeling")
    cls = m_class()

    with pytest.raises(ValueError, match="Spelling errors"):
        attribute.name_spelling(config, attribute=attr, cls=cls)


def test_attribute_name_spelling_disabled():
    """Test that name spellcheck is skipped when check_identifiers is False."""
    config = Configuration(
        spellcheck=ConfigurationSpellcheck(enabled=True, check_identifiers=False),
        validators_warn=["attribute.name_spelling"],
    )
    attr = m_attr(name="test_mispeling")
    cls = m_class()

    # Should not raise when check_identifiers is False
    attribute.name_spelling(config, attribute=attr, cls=cls)


def test_struct_notes_spelling_pass():
    """Test struct notes validator with correct spelling."""
    config = Configuration(spellcheck=ConfigurationSpellcheck(enabled=True), validators_warn=["struct.notes_spelling"])
    cls = m_class(name="TestClass", notes="This is correctly spelled documentation")

    # Should not raise
    struct.notes_spelling(config, cls=cls)


def test_struct_notes_spelling_fail():
    """Test struct notes validator with misspellings."""
    config = Configuration(spellcheck=ConfigurationSpellcheck(enabled=True), validators_fail=["struct.notes_spelling"])
    cls = m_class(name="TestClass", notes="This has mispeled words")

    with pytest.raises(ValueError, match="Spelling errors"):
        struct.notes_spelling(config, cls=cls)


def test_struct_name_spelling_pass():
    """Test struct name validator with correct spelling."""
    config = Configuration(
        spellcheck=ConfigurationSpellcheck(enabled=True, check_identifiers=True),
        validators_warn=["struct.name_spelling"],
    )
    cls = m_class(name="MessageHeader")

    # Should not raise - "Message" and "Header" are both valid
    struct.name_spelling(config, cls=cls)


def test_struct_name_spelling_fail():
    """Test struct name validator with misspellings."""
    config = Configuration(
        spellcheck=ConfigurationSpellcheck(enabled=True, check_identifiers=True),
        validators_fail=["struct.name_spelling"],
    )
    cls = m_class(name="MessageMispeling")  # "Mispeling" is misspelled

    with pytest.raises(ValueError, match="Spelling errors"):
        struct.name_spelling(config, cls=cls)


def test_package_notes_spelling_pass():
    """Test package notes validator with correct spelling."""
    config = Configuration(spellcheck=ConfigurationSpellcheck(enabled=True), validators_warn=["package.notes_spelling"])
    pkg = m_package(name="test_package", notes="This is correctly spelled documentation")

    # Should not raise
    package.notes_spelling(config, package=pkg)


def test_package_notes_spelling_fail():
    """Test package notes validator with misspellings."""
    config = Configuration(spellcheck=ConfigurationSpellcheck(enabled=True), validators_fail=["package.notes_spelling"])
    pkg = m_package(name="test_package", notes="This has mispeled words")

    with pytest.raises(ValueError, match="Spelling errors"):
        package.notes_spelling(config, package=pkg)


def test_package_name_spelling_pass():
    """Test package name validator with correct spelling."""
    config = Configuration(
        spellcheck=ConfigurationSpellcheck(enabled=True, check_identifiers=True),
        validators_warn=["package.name_spelling"],
    )
    pkg = m_package(name="test_package")

    # Should not raise - "test" and "package" are both valid
    package.name_spelling(config, package=pkg)


def test_package_name_spelling_fail():
    """Test package name validator with misspellings."""
    config = Configuration(
        spellcheck=ConfigurationSpellcheck(enabled=True, check_identifiers=True),
        validators_fail=["package.name_spelling"],
    )
    pkg = m_package(name="test_mispeling")

    with pytest.raises(ValueError, match="Spelling errors"):
        package.name_spelling(config, package=pkg)


def test_empty_notes_skipped():
    """Test that empty notes don't cause errors."""
    config = Configuration(
        spellcheck=ConfigurationSpellcheck(enabled=True), validators_warn=["attribute.notes_spelling"]
    )
    attr = m_attr(name="test", notes="")
    cls = m_class()

    # Should not raise - empty notes are skipped
    attribute.notes_spelling(config, attribute=attr, cls=cls)


def test_none_notes_skipped():
    """Test that None notes don't cause errors."""
    config = Configuration(
        spellcheck=ConfigurationSpellcheck(enabled=True), validators_warn=["attribute.notes_spelling"]
    )
    attr = m_attr(name="test", notes=None)
    cls = m_class()

    # Should not raise - None notes are skipped
    attribute.notes_spelling(config, attribute=attr, cls=cls)


def test_technical_terms_in_notes():
    """Test that technical terms in notes are not flagged."""
    config = Configuration(
        spellcheck=ConfigurationSpellcheck(enabled=True), validators_warn=["attribute.notes_spelling"]
    )
    attr = m_attr(
        name="test",
        notes="This attribute uses struct and enum types with uuid identifiers and json serialization",
    )
    cls = m_class()

    # Should not raise - all technical terms
    attribute.notes_spelling(config, attribute=attr, cls=cls)


def test_min_word_length_config():
    """Test that min_word_length configuration is respected."""
    config = Configuration(
        spellcheck=ConfigurationSpellcheck(enabled=True, min_word_length=5),
        validators_fail=["attribute.notes_spelling"],
    )
    # "teh" is too short (< 5) but "mispeled" should be caught
    attr = m_attr(name="test", notes="teh word mispeled here")
    cls = m_class()

    with pytest.raises(ValueError) as excinfo:
        attribute.notes_spelling(config, attribute=attr, cls=cls)

    # Should only catch "mispeled", not "teh"
    assert "mispeled" in str(excinfo.value)
    # "teh" might still be caught if it's 3+ chars, but with min_word_length=5 it should be skipped
    # Actually, "word" and "here" are 4 chars, so they should also be skipped


def test_identifier_with_numbers_ignored():
    """Test that identifiers with numbers are handled correctly."""
    text = "test3d variable4x name"
    words = extract_words(text, min_word_length=3)
    # "3d" and "4x" should be ignored (number+letters pattern)
    # But "test", "variable", "name" should be present
    assert "test" in words or "variable" in words or "name" in words


def test_extract_words_with_contractions():
    """Test that contractions like doesn't, can't are preserved."""
    text = "doesn't can't won't shouldn't"
    words = extract_words(text, min_word_length=3)
    # Contractions should be kept whole
    assert "doesn't" in words
    assert "can't" in words
    assert "won't" in words
    assert "shouldn't" in words
    # Should NOT split into "doesn", "can", "won", etc.
    assert "doesn" not in words
    assert "won" not in words


def test_extract_words_with_possessives():
    """Test that possessives like Allen's, Allens's are preserved."""
    text = "Allen's book and Allens's property"
    words = extract_words(text, min_word_length=3)
    # Possessives should be kept whole
    assert "allen's" in words
    assert "allens's" in words
    # Regular words should still work
    assert "book" in words
    assert "property" in words


def test_check_spelling_contractions():
    """Test that common contractions are not flagged as spelling errors."""
    text = "It doesn't work and can't be fixed"
    errors = check_spelling(text)
    # Contractions are valid English words
    error_words = [e["word"] for e in errors]
    assert "doesn't" not in error_words
    assert "can't" not in error_words


def test_extract_words_with_numbers_in_identifiers():
    """Test that identifiers with numbers are split correctly."""
    text = "Using CQL2Expression and HTTP2Server"
    words = extract_words(text, min_word_length=3)
    # Should split and extract meaningful parts
    assert "cql" in words or "expression" in words  # CQL2Expression -> CQL, Expression
    assert "http" in words or "server" in words  # HTTP2Server -> HTTP, Server
    # Should NOT include the numbers themselves
    assert "2" not in words


def test_check_spelling_technical_identifiers_with_numbers():
    """Test that technical identifiers with numbers don't cause false positives."""
    text = "This uses CQL2Expression for queries"
    errors = check_spelling(text)
    error_words = [e["word"] for e in errors]
    # Should NOT flag "cql2expression" as a whole
    assert "cql2expression" not in error_words
    # Individual parts like "cql" might be flagged, but that's expected
    # (can be added to custom_words if needed)
