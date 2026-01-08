"""Import edited notes from YAML back to EA database.

This module provides backward compatibility wrappers around the new Pydantic-based architecture.
"""

# Re-export from new architecture for backward compatibility
from eaidl.notes_model import ImportStatus, NoteImportResult, ImportSummary, NoteMetadata
from eaidl.notes_core import NotesImporter
from eaidl.notes_formats import YamlFormatter
from eaidl.config import Configuration
from eaidl.load import ModelParser
from typing import List


class YamlImporter:
    """Imports notes from YAML with per-note validation. Wrapper for backward compatibility."""

    def __init__(self, yaml_path: str, config: Configuration, parser: ModelParser):
        """Initialize YAML importer."""
        self.yaml_path = yaml_path
        self.config = config
        self.parser = parser
        self.importer = NotesImporter(config, parser)

    def parse_yaml(self) -> List[NoteMetadata]:
        """Parse YAML and extract notes with metadata."""
        return YamlFormatter.parse(self.yaml_path)

    def validate_and_import(
        self, notes: List[NoteMetadata], dry_run: bool = True, strict: bool = False
    ) -> ImportSummary:
        """Validate each note and prepare imports.

        Args:
            notes: Notes parsed from YAML
            dry_run: If True, don't commit changes
            strict: If True, fail entire import on any checksum mismatch
        """
        return self.importer.validate_and_import(notes, dry_run=dry_run, strict=strict)


# For backward compatibility, also export these
__all__ = ["ImportStatus", "NoteImportResult", "ImportSummary", "YamlImporter", "NoteMetadata"]
