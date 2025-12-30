"""
Tests for Mermaid diagram sanitization utilities.

Ensures special characters in names and notes are properly handled.
"""

from eaidl.mermaid_utils import (
    sanitize_id,
    escape_label,
    get_class_label,
    get_participant_declaration,
    format_note_text,
)


class TestSanitizeId:
    """Test ID sanitization for Mermaid identifiers."""

    def test_hash_symbol(self):
        """Test that hash symbols are removed."""
        assert sanitize_id("MUV_#1") == "MUV_1"
        assert sanitize_id("Test#Class") == "TestClass"

    def test_angle_brackets(self):
        """Test that angle brackets are removed (generics)."""
        assert sanitize_id("Data<T>") == "DataT"
        assert sanitize_id("List<String>") == "ListString"

    def test_special_chars(self):
        """Test various special characters are removed."""
        assert sanitize_id("Class@Name") == "ClassName"
        assert sanitize_id("Foo{Bar}") == "FooBar"
        assert sanitize_id("Test(1)") == "Test1"
        assert sanitize_id("A+B") == "AB"

    def test_separators(self):
        """Test that separators are converted to underscores."""
        assert sanitize_id("my-class") == "my_class"
        assert sanitize_id("Class::Name") == "Class_Name"
        assert sanitize_id("my class") == "my_class"

    def test_leading_number(self):
        """Test that leading numbers get underscore prepended."""
        assert sanitize_id("123Class") == "_123Class"
        assert sanitize_id("1") == "_1"

    def test_empty_string(self):
        """Test that empty/invalid strings get a default name."""
        assert sanitize_id("") == "UnknownClass"
        assert sanitize_id("@#$%") == "UnknownClass"

    def test_valid_name_unchanged(self):
        """Test that already-valid names are unchanged."""
        assert sanitize_id("MyClass") == "MyClass"
        assert sanitize_id("my_class_123") == "my_class_123"


class TestEscapeLabel:
    """Test label escaping for display text."""

    def test_double_quotes(self):
        """Test that double quotes are replaced with single quotes."""
        assert escape_label('Say "Hello"') == "Say 'Hello'"
        assert escape_label('Test"Quote') == "Test'Quote"

    def test_html_entities(self):
        """Test that HTML entities are decoded."""
        assert escape_label("&lt;Data&gt;") == "<Data>"
        assert escape_label("&amp;") == "&"
        assert escape_label("&quot;test&quot;") == "'test'"  # Quotes also replaced

    def test_newlines(self):
        """Test that newlines are converted to spaces."""
        assert escape_label("Line1\nLine2") == "Line1 Line2"
        assert escape_label("Line1\r\nLine2") == "Line1 Line2"

    def test_multiple_spaces(self):
        """Test that multiple spaces are collapsed."""
        assert escape_label("Multiple    spaces") == "Multiple spaces"
        assert escape_label("Tab\t\ttab") == "Tab tab"

    def test_backticks(self):
        """Test that backticks are replaced."""
        assert escape_label("`code`") == "'code'"

    def test_whitespace_trimming(self):
        """Test that leading/trailing whitespace is trimmed."""
        assert escape_label("  test  ") == "test"
        assert escape_label("\ntest\n") == "test"

    def test_empty_string(self):
        """Test that empty strings remain empty."""
        assert escape_label("") == ""
        assert escape_label(None) == ""


class TestGetClassLabel:
    """Test class label generation."""

    def test_simple_name(self):
        """Test that simple names don't use label syntax."""
        assert get_class_label("MyClass") == "MyClass"
        assert get_class_label("my_class") == "my_class"

    def test_name_with_special_chars(self):
        """Test that names with special chars use label syntax."""
        result = get_class_label("MUV_#1")
        assert result == 'MUV_1["MUV_#1"]'

    def test_name_with_angle_brackets(self):
        """Test generic-style names."""
        result = get_class_label("Data<T>")
        assert result == 'DataT["Data<T>"]'

    def test_name_with_namespace(self):
        """Test namespace separators."""
        result = get_class_label("ns::MyClass")
        assert result == 'ns_MyClass["ns::MyClass"]'


class TestGetParticipantDeclaration:
    """Test sequence diagram participant declarations."""

    def test_simple_name(self):
        """Test simple participant names."""
        assert get_participant_declaration("Server") == "participant Server"

    def test_name_with_special_chars(self):
        """Test participant with special characters."""
        result = get_participant_declaration("Service#1")
        assert result == 'participant Service1 as "Service#1"'

    def test_name_with_spaces(self):
        """Test participant with spaces."""
        result = get_participant_declaration("My Service")
        assert result == 'participant My_Service as "My Service"'


class TestFormatNoteText:
    """Test note text formatting."""

    def test_basic_escaping(self):
        """Test that notes are escaped."""
        result = format_note_text('Note with "quotes"')
        assert result == "Note with 'quotes'"

    def test_truncation(self):
        """Test that long notes are truncated."""
        long_text = "A" * 200
        result = format_note_text(long_text, max_length=50)
        assert len(result) == 50
        assert result.endswith("...")

    def test_no_truncation_when_zero(self):
        """Test that max_length=0 means no limit."""
        long_text = "A" * 200
        result = format_note_text(long_text, max_length=0)
        assert len(result) == 200

    def test_html_in_notes(self):
        """Test that HTML entities in notes are decoded."""
        result = format_note_text("&lt;Note&gt;")
        assert result == "<Note>"


class TestIntegration:
    """Integration tests for common scenarios."""

    def test_class_with_multiple_issues(self):
        """Test a class name with multiple problematic characters."""
        name = "Data<T>#1::Version{2}"
        safe_id = sanitize_id(name)
        label = get_class_label(name)

        # ID should be clean alphanumeric+underscore
        assert safe_id == "DataT1_Version2"
        # Label should preserve original but escape it
        assert label == 'DataT1_Version2["Data<T>#1::Version{2}"]'

    def test_real_world_ea_name(self):
        """Test a realistic EA class name."""
        name = "Message_Type<Extended>"
        safe_id = sanitize_id(name)
        label = get_class_label(name)

        assert safe_id == "Message_TypeExtended"
        assert label == 'Message_TypeExtended["Message_Type<Extended>"]'

    def test_sequence_participant_with_instance(self):
        """Test instance naming in sequence diagrams."""
        name = ":ServiceInstance#1"
        safe_id = sanitize_id(name)
        participant = get_participant_declaration(name)

        assert safe_id == "ServiceInstance1"
        assert participant == 'participant ServiceInstance1 as ":ServiceInstance#1"'
