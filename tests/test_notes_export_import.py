"""Tests for notes export/import functionality."""

import pytest
import tempfile
import os

from eaidl.utils import load_config
from eaidl.load import ModelParser
from eaidl.notes_export import NotesCollector, DocxExporter
from eaidl.notes_import import DocxImporter, ImportStatus


@pytest.fixture
def config():
    """Load test configuration."""
    return load_config("config/sqlite.yaml")


@pytest.fixture
def parser(config):
    """Create parser with test database."""
    return ModelParser(config)


@pytest.fixture
def packages(parser):
    """Load test model."""
    return parser.load()


class TestNotesExport:
    """Test note export functionality."""

    def test_collect_all_notes(self, config, packages):
        """Test collecting all notes from model."""
        collector = NotesCollector(config, packages)
        notes_export = collector.collect_all_notes()

        assert len(notes_export.notes) > 0
        assert notes_export.metadata.export_timestamp is not None
        assert notes_export.metadata.root_packages == config.root_packages

    def test_collect_note_types(self, config, packages):
        """Test that all note types are collected."""
        collector = NotesCollector(config, packages)
        notes_export = collector.collect_all_notes()

        note_types = {note.note_type for note in notes_export.notes}

        # We should have at least some of these types
        expected_types = {
            "package_main",
            "package_unlinked",
            "class_main",
            "class_linked",
            "attribute_main",
            "attribute_linked",
        }

        # Check that we have some expected types
        assert len(note_types.intersection(expected_types)) > 0

    def test_attribute_notes_have_guid(self, config, packages):
        """Test that attribute notes have GUID set."""
        collector = NotesCollector(config, packages)
        notes_export = collector.collect_all_notes()

        attr_notes = [n for n in notes_export.notes if n.note_type in ("attribute_main", "attribute_linked")]

        # All attribute notes should have GUID
        for note in attr_notes:
            assert note.object_guid is not None
            assert note.object_guid.startswith("{")
            assert note.object_guid.endswith("}")

    def test_export_docx(self, config, packages):
        """Test exporting notes to DOCX file."""
        collector = NotesCollector(config, packages)
        notes_export = collector.collect_all_notes()

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = os.path.join(tmpdir, "test_notes.docx")
            exporter = DocxExporter(notes_export)
            exporter.export_to_file(output_path)

            assert os.path.exists(output_path)
            assert os.path.getsize(output_path) > 0

    def test_items_without_notes_are_exported(self, config, packages):
        """Test that items without notes are exported with empty content.

        This ensures reviewers can see ALL items in the export and add
        documentation to items that are currently missing notes.
        """
        collector = NotesCollector(config, packages)
        notes_export = collector.collect_all_notes()

        # Find notes with empty content
        empty_notes = [n for n in notes_export.notes if n.content_md == ""]
        notes_with_content = [n for n in notes_export.notes if n.content_md != ""]

        # We should have both empty and non-empty notes
        assert len(empty_notes) > 0, "Expected some items without notes to be exported"
        assert len(notes_with_content) > 0, "Expected some items with notes to be exported"

        # Empty notes should have valid checksums (checksum of empty string)
        empty_string_checksum = "d41d8cd98f00b204e9800998ecf8427e"  # MD5 of ""
        for note in empty_notes:
            assert note.checksum == empty_string_checksum, f"Empty note {note.path} should have empty string checksum"

        # Verify we have empty notes for different types
        empty_note_types = {n.note_type for n in empty_notes}
        assert (
            "package_main" in empty_note_types
            or "class_main" in empty_note_types
            or "attribute_main" in empty_note_types
        )

    def test_all_classes_and_attributes_exported(self, config, packages):
        """Test that ALL classes and attributes are exported, not just those with notes."""
        collector = NotesCollector(config, packages)
        notes_export = collector.collect_all_notes()

        # Count classes and attributes in the model
        def count_items(pkgs):
            total_classes = 0
            total_attrs = 0
            for pkg in pkgs:
                total_classes += len(pkg.classes)
                for cls in pkg.classes:
                    total_attrs += len(cls.attributes)
                child_classes, child_attrs = count_items(pkg.packages)
                total_classes += child_classes
                total_attrs += child_attrs
            return total_classes, total_attrs

        model_classes, model_attrs = count_items(packages)

        # Count exported class and attribute notes
        class_notes = [n for n in notes_export.notes if n.note_type == "class_main"]
        attr_notes = [n for n in notes_export.notes if n.note_type == "attribute_main"]

        # Should have a note entry for every class and attribute
        assert len(class_notes) == model_classes, f"Expected {model_classes} class notes, got {len(class_notes)}"
        assert len(attr_notes) == model_attrs, f"Expected {model_attrs} attribute notes, got {len(attr_notes)}"


class TestNotesImport:
    """Test note import functionality."""

    def test_round_trip_unchanged(self, config, parser, packages):
        """Test round-trip export/import with no changes."""
        # Export
        collector = NotesCollector(config, packages)
        notes_export = collector.collect_all_notes()

        with tempfile.TemporaryDirectory() as tmpdir:
            docx_path = os.path.join(tmpdir, "test_notes.docx")

            exporter = DocxExporter(notes_export)
            exporter.export_to_file(docx_path)

            # Import
            importer = DocxImporter(docx_path, config, parser)
            parsed_notes = importer.parse_document()

            # Should parse same number of notes
            assert len(parsed_notes) == len(notes_export.notes)

            # Validate (dry-run)
            summary = importer.validate_and_import(parsed_notes, dry_run=True)

            # All notes should be unchanged
            assert summary.total_notes == len(notes_export.notes)
            assert summary.skipped_unchanged == len(notes_export.notes)
            assert summary.imported == 0
            assert summary.skipped_checksum == 0
            assert summary.not_found == 0
            assert summary.errors == 0

    def test_parse_document(self, config, parser, packages):
        """Test parsing DOCX document."""
        collector = NotesCollector(config, packages)
        notes_export = collector.collect_all_notes()

        with tempfile.TemporaryDirectory() as tmpdir:
            docx_path = os.path.join(tmpdir, "test_notes.docx")

            exporter = DocxExporter(notes_export)
            exporter.export_to_file(docx_path)

            importer = DocxImporter(docx_path, config, parser)
            parsed_notes = importer.parse_document()

            # Check that metadata is preserved
            assert len(parsed_notes) > 0

            # Check first note has expected fields
            note = parsed_notes[0]
            assert note.note_type is not None
            assert note.object_id is not None
            assert note.checksum is not None
            assert note.path is not None

    def test_attribute_notes_have_guid_after_import(self, config, parser, packages):
        """Test that attribute notes retain GUID after round-trip."""
        collector = NotesCollector(config, packages)
        notes_export = collector.collect_all_notes()

        with tempfile.TemporaryDirectory() as tmpdir:
            docx_path = os.path.join(tmpdir, "test_notes.docx")

            exporter = DocxExporter(notes_export)
            exporter.export_to_file(docx_path)

            importer = DocxImporter(docx_path, config, parser)
            parsed_notes = importer.parse_document()

            # Find attribute notes
            attr_notes = [n for n in parsed_notes if n.note_type in ("attribute_main", "attribute_linked")]

            # All should have GUID
            for note in attr_notes:
                assert note.object_guid is not None
                assert note.object_guid.startswith("{")

    def test_modified_note_detection(self, config, parser, packages):
        """Test that modified notes are detected."""
        collector = NotesCollector(config, packages)
        notes_export = collector.collect_all_notes()

        with tempfile.TemporaryDirectory() as tmpdir:
            docx_path = os.path.join(tmpdir, "test_notes.docx")

            exporter = DocxExporter(notes_export)
            exporter.export_to_file(docx_path)

            # Parse and modify a note
            importer = DocxImporter(docx_path, config, parser)
            parsed_notes = importer.parse_document()

            # Modify first note
            if len(parsed_notes) > 0:
                parsed_notes[0].content_md = "MODIFIED CONTENT FOR TEST"

                # Validate
                summary = importer.validate_and_import(parsed_notes, dry_run=True)

                # Should detect the change
                assert summary.imported >= 1  # At least one note ready to import

    def test_checksum_validation(self, config, parser, packages):
        """Test checksum validation for detecting EA changes."""
        collector = NotesCollector(config, packages)
        notes_export = collector.collect_all_notes()

        with tempfile.TemporaryDirectory() as tmpdir:
            docx_path = os.path.join(tmpdir, "test_notes.docx")

            exporter = DocxExporter(notes_export)
            exporter.export_to_file(docx_path)

            # Parse notes
            importer = DocxImporter(docx_path, config, parser)
            parsed_notes = importer.parse_document()

            # Modify checksum to simulate EA change
            if len(parsed_notes) > 0:
                parsed_notes[0].checksum = "00000000000000000000000000000000"  # Invalid but valid length

                # Validate
                summary = importer.validate_and_import(parsed_notes, dry_run=True)

                # Should detect checksum mismatch
                assert summary.skipped_checksum >= 1

    def test_import_summary_structure(self, config, parser, packages):
        """Test that import summary has correct structure."""
        collector = NotesCollector(config, packages)
        notes_export = collector.collect_all_notes()

        with tempfile.TemporaryDirectory() as tmpdir:
            docx_path = os.path.join(tmpdir, "test_notes.docx")

            exporter = DocxExporter(notes_export)
            exporter.export_to_file(docx_path)

            importer = DocxImporter(docx_path, config, parser)
            parsed_notes = importer.parse_document()

            summary = importer.validate_and_import(parsed_notes, dry_run=True)

            # Check summary fields
            assert summary.total_notes == len(parsed_notes)
            assert summary.imported >= 0
            assert summary.skipped_checksum >= 0
            assert summary.skipped_unchanged >= 0
            assert summary.not_found >= 0
            assert summary.errors >= 0
            assert len(summary.results) == len(parsed_notes)

            # Check that all results have required fields
            for result in summary.results:
                assert result.note_type is not None
                assert result.path is not None
                assert result.status in ImportStatus
                assert result.message is not None


class TestPartialImport:
    """Test partial import functionality (parallel review workflow)."""

    def test_partial_import_scenario(self, config, parser, packages):
        """Test importing only valid notes when some have checksum mismatches."""
        collector = NotesCollector(config, packages)
        notes_export = collector.collect_all_notes()

        with tempfile.TemporaryDirectory() as tmpdir:
            docx_path = os.path.join(tmpdir, "test_notes.docx")

            exporter = DocxExporter(notes_export)
            exporter.export_to_file(docx_path)

            importer = DocxImporter(docx_path, config, parser)
            parsed_notes = importer.parse_document()

            if len(parsed_notes) >= 3:
                # Simulate parallel review scenario:
                # - Note 0: Modified by reviewer (valid checksum, changed content)
                # - Note 1: Changed in EA since export (invalid checksum)
                # - Note 2: Unchanged

                parsed_notes[0].content_md = "MODIFIED BY REVIEWER"
                parsed_notes[1].checksum = "11111111111111111111111111111111"  # Invalid but valid length
                # Note 2 unchanged

                summary = importer.validate_and_import(parsed_notes, dry_run=True)

                # Should import note 0, skip note 1, skip note 2
                assert summary.imported >= 1  # Modified note
                assert summary.skipped_checksum >= 1  # Invalid checksum
                assert summary.skipped_unchanged >= 1  # Unchanged note
