"""Export EA model notes to YAML format for editing.

This module provides backward compatibility wrappers around the new Pydantic-based architecture.
"""

# Re-export from new architecture for backward compatibility
from eaidl.notes_model import NoteMetadata, NotesExport
from eaidl.notes_core import NotesCollector
from eaidl.notes_formats import YamlFormatter


class YamlExporter:
    """Exports notes to YAML format. Wrapper for backward compatibility."""

    def __init__(self, notes_export: NotesExport):
        """Initialize with NotesExport (Pydantic model)."""
        self.notes_export = notes_export

    def export_to_file(self, output_path: str):
        """Export to YAML file using new formatter."""
        YamlFormatter.export(self.notes_export, output_path)


# For backward compatibility, also export these
__all__ = ["NoteMetadata", "NotesExport", "NotesCollector", "YamlExporter"]
