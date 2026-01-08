"""Tests for YAML notes export/import functionality."""

import pytest
import tempfile
import os
import yaml

from eaidl.utils import load_config
from eaidl.load import ModelParser
from eaidl.notes_core import NotesCollector, NotesImporter
from eaidl.notes_formats import YamlFormatter
from eaidl.notes_model import ImportStatus


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


class TestYamlExport:
    """Test YAML note export functionality."""

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

    def test_export_yaml(self, config, packages):
        """Test exporting notes to YAML file."""
        collector = NotesCollector(config, packages)
        notes_export = collector.collect_all_notes()

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = os.path.join(tmpdir, "test_notes.yaml")
            YamlFormatter.export(notes_export, output_path)

            assert os.path.exists(output_path)
            assert os.path.getsize(output_path) > 0

            # Verify it's valid YAML
            with open(output_path, "r") as f:
                data = yaml.safe_load(f)
                assert "metadata" in data
                assert "notes" in data
                assert len(data["notes"]) == notes_export.metadata.note_count


class TestYamlImport:
    """Test YAML note import functionality."""

    def test_round_trip_unchanged(self, config, parser, packages):
        """Test round-trip export/import with no changes."""
        # Export
        collector = NotesCollector(config, packages)
        notes_export = collector.collect_all_notes()

        with tempfile.TemporaryDirectory() as tmpdir:
            yaml_path = os.path.join(tmpdir, "test_notes.yaml")

            YamlFormatter.export(notes_export, yaml_path)

            # Import
            parsed_notes = YamlFormatter.parse(yaml_path)

            # Should parse same number of notes
            assert len(parsed_notes) == notes_export.metadata.note_count

            # Validate (dry-run)
            importer = NotesImporter(config, parser)
            importer = NotesImporter(config, parser)
            summary = importer.validate_and_import(parsed_notes, dry_run=True)

            # All notes should be unchanged
            assert summary.total_notes == notes_export.metadata.note_count
            assert summary.skipped_unchanged == notes_export.metadata.note_count
            assert summary.imported == 0
            assert summary.skipped_checksum == 0
            assert summary.not_found == 0
            assert summary.errors == 0

    def test_parse_yaml(self, config, parser, packages):
        """Test parsing YAML document."""
        collector = NotesCollector(config, packages)
        notes_export = collector.collect_all_notes()

        with tempfile.TemporaryDirectory() as tmpdir:
            yaml_path = os.path.join(tmpdir, "test_notes.yaml")

            YamlFormatter.export(notes_export, yaml_path)

            parsed_notes = YamlFormatter.parse(yaml_path)

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
            yaml_path = os.path.join(tmpdir, "test_notes.yaml")

            YamlFormatter.export(notes_export, yaml_path)

            parsed_notes = YamlFormatter.parse(yaml_path)

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
            yaml_path = os.path.join(tmpdir, "test_notes.yaml")

            YamlFormatter.export(notes_export, yaml_path)

            # Parse and modify a note
            parsed_notes = YamlFormatter.parse(yaml_path)

            # Modify first note
            if len(parsed_notes) > 0:
                parsed_notes[0].content_md = "MODIFIED CONTENT FOR TEST"

                # Validate
                importer = NotesImporter(config, parser)
                summary = importer.validate_and_import(parsed_notes, dry_run=True)

                # Should detect the change
                assert summary.imported >= 1  # At least one note ready to import

    def test_checksum_validation(self, config, parser, packages):
        """Test checksum validation for detecting EA changes."""
        collector = NotesCollector(config, packages)
        notes_export = collector.collect_all_notes()

        with tempfile.TemporaryDirectory() as tmpdir:
            yaml_path = os.path.join(tmpdir, "test_notes.yaml")

            YamlFormatter.export(notes_export, yaml_path)

            # Parse notes
            parsed_notes = YamlFormatter.parse(yaml_path)

            # Modify checksum to simulate EA change
            if len(parsed_notes) > 0:
                parsed_notes[0].checksum = "00000000000000000000000000000000"  # Invalid but valid length

                # Validate
                importer = NotesImporter(config, parser)
                summary = importer.validate_and_import(parsed_notes, dry_run=True)

                # Should detect checksum mismatch
                assert summary.skipped_checksum >= 1

    def test_import_summary_structure(self, config, parser, packages):
        """Test that import summary has correct structure."""
        collector = NotesCollector(config, packages)
        notes_export = collector.collect_all_notes()

        with tempfile.TemporaryDirectory() as tmpdir:
            yaml_path = os.path.join(tmpdir, "test_notes.yaml")

            YamlFormatter.export(notes_export, yaml_path)

            parsed_notes = YamlFormatter.parse(yaml_path)

            importer = NotesImporter(config, parser)
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

    def test_yaml_human_readable(self, config, packages):
        """Test that exported YAML is human-readable and well-formatted."""
        collector = NotesCollector(config, packages)
        notes_export = collector.collect_all_notes()

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = os.path.join(tmpdir, "test_notes.yaml")
            YamlFormatter.export(notes_export, output_path)

            # Read file and check formatting
            with open(output_path, "r") as f:
                content = f.read()

                # Check for header comments
                assert "# EA-IDL Notes Export" in content
                assert "# EDITING INSTRUCTIONS:" in content

                # Check YAML is valid
                f.seek(0)
                data = yaml.safe_load(f)

                # Check structure
                assert "metadata" in data
                assert "instructions" in data
                assert "notes" in data

                # Check metadata
                assert "export_timestamp" in data["metadata"]
                assert "root_packages" in data["metadata"]
                assert "note_count" in data["metadata"]


class TestPartialImport:
    """Test partial import functionality (parallel review workflow)."""

    def test_partial_import_scenario(self, config, parser, packages):
        """Test importing only valid notes when some have checksum mismatches."""
        collector = NotesCollector(config, packages)
        notes_export = collector.collect_all_notes()

        with tempfile.TemporaryDirectory() as tmpdir:
            yaml_path = os.path.join(tmpdir, "test_notes.yaml")

            YamlFormatter.export(notes_export, yaml_path)

            parsed_notes = YamlFormatter.parse(yaml_path)

            if len(parsed_notes) >= 3:
                # Simulate parallel review scenario:
                # - Note 0: Modified by reviewer (valid checksum, changed content)
                # - Note 1: Changed in EA since export (invalid checksum)
                # - Note 2: Unchanged

                parsed_notes[0].content_md = "MODIFIED BY REVIEWER"
                parsed_notes[1].checksum = "11111111111111111111111111111111"  # Invalid but valid length
                # Note 2 unchanged

                importer = NotesImporter(config, parser)
                summary = importer.validate_and_import(parsed_notes, dry_run=True)

                # Should import note 0, skip note 1, skip note 2
                assert summary.imported >= 1  # Modified note
                assert summary.skipped_checksum >= 1  # Invalid checksum
                assert summary.skipped_unchanged >= 1  # Unchanged note
