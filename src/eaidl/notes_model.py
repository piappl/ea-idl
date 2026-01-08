"""Pydantic models for notes export/import functionality."""

from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator


class NoteType(str, Enum):
    """Type of note in the EA model."""

    PACKAGE_MAIN = "package_main"
    PACKAGE_UNLINKED = "package_unlinked"
    CLASS_MAIN = "class_main"
    CLASS_LINKED = "class_linked"
    ATTRIBUTE_MAIN = "attribute_main"
    ATTRIBUTE_LINKED = "attribute_linked"


class NoteMetadata(BaseModel):
    """Metadata for a single note in the export."""

    note_type: NoteType = Field(..., description="Type of note")
    object_id: int = Field(..., description="ID of package/class/attribute", gt=0)
    note_id: Optional[int] = Field(None, description="ID of Note object (None for main notes)", gt=0)
    namespace: List[str] = Field(..., description="Full namespace path")
    object_name: str = Field(..., min_length=1, description="Name of package/class/attribute")
    content_md: str = Field("", description="Markdown content")
    content_html: str = Field("", description="Original HTML (for checksum)")
    checksum: str = Field(..., min_length=32, max_length=32, description="MD5 of HTML content")
    path: str = Field(..., min_length=1, description="Hierarchical path for structure")
    object_guid: Optional[str] = Field(
        None, pattern=r"^\{[A-Fa-f0-9\-]+\}$", description="GUID for attributes (attr_object_id is not unique)"
    )

    @field_validator("object_guid", mode="before")
    @classmethod
    def validate_guid_format(cls, v: Optional[str]) -> Optional[str]:
        """Validate GUID format if present."""
        if v is None or v == "":
            return None
        if not v.startswith("{") or not v.endswith("}"):
            raise ValueError("GUID must be in format {XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX}")
        return v

    model_config = {"frozen": False, "validate_assignment": True}


class NotesExportMetadata(BaseModel):
    """Metadata about the export operation."""

    export_timestamp: datetime = Field(default_factory=datetime.now, description="When the export was created")
    root_packages: List[str] = Field(..., min_length=1, description="Root package GUIDs")
    database_url: str = Field(..., min_length=1, description="Database URL for reference")
    note_count: int = Field(..., ge=0, description="Total number of notes exported")

    model_config = {"frozen": False}


class NotesExport(BaseModel):
    """Container for all notes being exported."""

    metadata: NotesExportMetadata = Field(..., description="Export metadata")
    notes: List[NoteMetadata] = Field(default_factory=list, description="List of notes")

    @field_validator("notes")
    @classmethod
    def validate_note_count(cls, v: List[NoteMetadata], info) -> List[NoteMetadata]:
        """Ensure note count matches actual notes."""
        # Can't validate here because metadata might not be set yet
        return v

    def model_post_init(self, __context) -> None:
        """Validate after all fields are set."""
        if self.metadata.note_count != len(self.notes):
            raise ValueError(f"note_count ({self.metadata.note_count}) does not match actual notes ({len(self.notes)})")

    model_config = {"frozen": False, "validate_assignment": True}


class ImportStatus(str, Enum):
    """Status of a note import."""

    SUCCESS = "success"
    CHECKSUM_MISMATCH = "checksum_mismatch"
    NOT_FOUND = "not_found"
    CONTENT_UNCHANGED = "unchanged"
    ERROR = "error"


class NoteImportResult(BaseModel):
    """Result of importing a single note."""

    note_type: NoteType = Field(..., description="Type of note")
    object_id: int = Field(..., gt=0, description="Object ID")
    note_id: Optional[int] = Field(None, gt=0, description="Note ID if applicable")
    path: str = Field(..., min_length=1, description="Hierarchical path")
    status: ImportStatus = Field(..., description="Import status")
    message: str = Field(..., min_length=1, description="Status message")
    old_content: Optional[str] = Field(None, description="Original content (if changed)")
    new_content: Optional[str] = Field(None, description="New content (if changed)")
    object_guid: Optional[str] = Field(None, description="Object GUID if applicable")

    model_config = {"frozen": False}


class ImportSummary(BaseModel):
    """Summary of entire import operation."""

    total_notes: int = Field(..., ge=0, description="Total notes processed")
    imported: int = Field(..., ge=0, description="Successfully imported")
    skipped_checksum: int = Field(..., ge=0, description="Skipped due to checksum mismatch")
    skipped_unchanged: int = Field(..., ge=0, description="Skipped as unchanged")
    not_found: int = Field(..., ge=0, description="Not found in database")
    errors: int = Field(..., ge=0, description="Errors encountered")
    results: List[NoteImportResult] = Field(default_factory=list, description="Individual results")

    @field_validator("results")
    @classmethod
    def validate_totals(cls, v: List[NoteImportResult], info) -> List[NoteImportResult]:
        """Validate that result count matches total."""
        # Can't validate here as other fields might not be set yet
        return v

    def model_post_init(self, __context) -> None:
        """Validate after all fields are set."""
        if len(self.results) != self.total_notes:
            raise ValueError(f"results count ({len(self.results)}) does not match total_notes ({self.total_notes})")

        # Validate sum of statuses matches
        expected_total = self.imported + self.skipped_checksum + self.skipped_unchanged + self.not_found + self.errors
        if expected_total != self.total_notes:
            raise ValueError(f"sum of status counts ({expected_total}) does not match total_notes ({self.total_notes})")

    def print_report(self):
        """Print human-readable import report."""
        print("\n" + "=" * 80)
        print("NOTE IMPORT SUMMARY")
        print("=" * 80)
        print(f"Total notes in document: {self.total_notes}")
        print(f"Successfully imported:   {self.imported}")
        print(f"Skipped (checksum):      {self.skipped_checksum}")
        print(f"Skipped (unchanged):     {self.skipped_unchanged}")
        print(f"Not found in model:      {self.not_found}")
        print(f"Errors:                  {self.errors}")
        print("=" * 80)

        if self.skipped_checksum > 0:
            print(f"\n⚠  {self.skipped_checksum} notes were skipped due to checksum mismatch")
            print("   (EA model changed since export)")

        if self.errors > 0:
            print(f"\n❌ {self.errors} errors occurred during import")

        if self.imported > 0:
            print(f"\n✓ Successfully imported {self.imported} note updates")

    model_config = {"frozen": False, "validate_assignment": True}
