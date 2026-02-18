"""Core notes collection and import logic shared between formats."""

import hashlib
from typing import List, Optional

import markdown

from eaidl.config import Configuration
from eaidl.html_utils import convert_to_ea_html, strip_html
from eaidl.load import ModelParser, base
from eaidl.model import ModelAttribute, ModelClass, ModelPackage
from eaidl.notes_model import (
    ImportStatus,
    ImportSummary,
    NoteImportResult,
    NoteMetadata,
    NotesExport,
    NotesExportMetadata,
    NoteType,
)


class NotesCollector:
    """Collects all notes from model into Pydantic-based exportable format."""

    def __init__(self, config: Configuration, model: List[ModelPackage]):
        self.config = config
        self.model = model
        self.notes: List[NoteMetadata] = []

    def collect_all_notes(self) -> NotesExport:
        """Walk entire model tree and collect all notes."""
        for package in self.model:
            if package.name == "ext":  # Skip generated ext package
                continue
            self._collect_package_notes(package)

        metadata = NotesExportMetadata(
            root_packages=self.config.root_packages,
            database_url=self.config.database_url,
            note_count=len(self.notes),
        )

        return NotesExport(metadata=metadata, notes=self.notes)

    def _collect_package_notes(self, package: ModelPackage, parent_path: str = ""):
        """Recursively collect notes from package tree."""
        path = f"{parent_path}/{package.name}" if parent_path else package.name

        # Package main note (always export, even if empty)
        self._add_note(
            note_type=NoteType.PACKAGE_MAIN,
            object_id=package.object_id,
            namespace=package.namespace,
            object_name=package.name,
            content_html=package.notes,
            path=path,
        )

        # Package unlinked notes (free-floating notes in package)
        for idx, unlinked_note in enumerate(package.unlinked_notes):
            self._add_note(
                note_type=NoteType.PACKAGE_UNLINKED,
                object_id=package.package_id,
                note_id=unlinked_note.note_id,
                namespace=package.namespace,
                object_name=f"unlinked_{idx + 1}",
                content_html=unlinked_note.content_html,
                content_md=unlinked_note.content,
                checksum=unlinked_note.checksum,
                path=f"{path}/unlinked_{idx + 1}",
            )

        # Class notes
        for cls in package.classes:
            self._collect_class_notes(cls, path)

        # Recurse to child packages
        for child in package.packages:
            self._collect_package_notes(child, path)

    def _collect_class_notes(self, cls: ModelClass, package_path: str):
        """Collect notes from a class and its attributes."""
        path = f"{package_path}/{cls.name}"

        # Class main note (always export, even if empty)
        self._add_note(
            note_type=NoteType.CLASS_MAIN,
            object_id=cls.object_id,
            namespace=cls.namespace,
            object_name=cls.name,
            content_html=cls.notes,
            path=path,
        )

        # Class linked notes
        for idx, linked_note in enumerate(cls.linked_notes):
            self._add_note(
                note_type=NoteType.CLASS_LINKED,
                object_id=cls.object_id,
                note_id=linked_note.note_id,
                namespace=cls.namespace,
                object_name=cls.name,
                content_html=linked_note.content_html,
                content_md=linked_note.content,
                checksum=linked_note.checksum,
                path=f"{path}/linked_{idx + 1}",
            )

        # Attribute notes
        for attr in cls.attributes:
            self._collect_attribute_notes(attr, path, cls.namespace)

    def _collect_attribute_notes(self, attr: ModelAttribute, class_path: str, parent_namespace: List[str]):
        """Collect notes from an attribute."""
        path = f"{class_path}/{attr.name}"

        # Attribute main note (always export, even if empty)
        self._add_note(
            note_type=NoteType.ATTRIBUTE_MAIN,
            object_id=attr.attribute_id,
            namespace=parent_namespace,
            object_name=attr.name,
            content_html=attr.notes,
            path=path,
            object_guid=attr.guid,
        )

        # Attribute linked notes
        for idx, linked_note in enumerate(attr.linked_notes):
            self._add_note(
                note_type=NoteType.ATTRIBUTE_LINKED,
                object_id=attr.attribute_id,
                note_id=linked_note.note_id,
                namespace=parent_namespace,
                object_name=attr.name,
                content_html=linked_note.content_html,
                content_md=linked_note.content,
                checksum=linked_note.checksum,
                path=f"{path}/linked_{idx + 1}",
                object_guid=attr.guid,
            )

    def _add_note(
        self,
        note_type: NoteType,
        object_id: int,
        namespace: List[str],
        object_name: str,
        content_html: Optional[str],
        path: str,
        note_id: Optional[int] = None,
        content_md: Optional[str] = None,
        checksum: Optional[str] = None,
        object_guid: Optional[str] = None,
    ):
        """Add a note to the collection with metadata."""
        # Handle None content by treating as empty string
        if content_html is None:
            content_html = ""
        # If content_md and checksum not provided, compute them
        if content_md is None:
            content_md = strip_html(content_html) or ""
        if checksum is None:
            checksum = hashlib.md5(content_html.encode("utf-8")).hexdigest()

        note = NoteMetadata(
            note_type=note_type,
            object_id=object_id,
            note_id=note_id,
            namespace=namespace,
            object_name=object_name,
            content_md=content_md,
            content_html=content_html,
            checksum=checksum,
            path=path,
            object_guid=object_guid,
        )
        self.notes.append(note)


class NotesImporter:
    """Validates and imports notes from Pydantic models to database."""

    def __init__(self, config: Configuration, parser: ModelParser):
        self.config = config
        self.parser = parser
        self.results: List[NoteImportResult] = []

    def validate_and_import(
        self, notes: List[NoteMetadata], dry_run: bool = True, strict: bool = False
    ) -> ImportSummary:
        """Validate each note and prepare imports.

        Args:
            notes: Notes parsed from document
            dry_run: If True, don't commit changes
            strict: If True, fail entire import on any checksum mismatch
        """
        self.results = []

        for note in notes:
            result = self._validate_note(note)
            self.results.append(result)

            if strict and result.status == ImportStatus.CHECKSUM_MISMATCH:
                raise ValueError(
                    f"Strict mode: Checksum mismatch for {note.path}\n" f"EA model changed since export. Cannot import."
                )

        # Generate summary
        summary = self._generate_summary()

        # Perform imports if not dry run
        if not dry_run:
            self._commit_imports()

        return summary

    def _validate_note(self, note: NoteMetadata) -> NoteImportResult:
        """Validate a single note against current EA database.

        Returns ImportStatus indicating what to do with this note.
        """
        # Query current note content from database
        current_html = self._get_current_note_html(note)

        if current_html is None:
            return NoteImportResult(
                note_type=note.note_type,
                object_id=note.object_id,
                note_id=note.note_id,
                path=note.path,
                status=ImportStatus.NOT_FOUND,
                message=f"Object not found in database: {note.path}",
                object_guid=note.object_guid,
            )

        # Calculate current checksum
        current_checksum = hashlib.md5(current_html.encode("utf-8")).hexdigest()

        # Compare with exported checksum
        if current_checksum != note.checksum:
            return NoteImportResult(
                note_type=note.note_type,
                object_id=note.object_id,
                note_id=note.note_id,
                path=note.path,
                status=ImportStatus.CHECKSUM_MISMATCH,
                message="Checksum mismatch: EA model changed since export",
                old_content=strip_html(current_html),
                object_guid=note.object_guid,
            )

        # Checksum matches - check if content changed in document
        current_md = strip_html(current_html)
        if current_md.strip() == note.content_md.strip():
            return NoteImportResult(
                note_type=note.note_type,
                object_id=note.object_id,
                note_id=note.note_id,
                path=note.path,
                status=ImportStatus.CONTENT_UNCHANGED,
                message="Content unchanged",
                object_guid=note.object_guid,
            )

        # All validation passed - this note can be imported
        return NoteImportResult(
            note_type=note.note_type,
            object_id=note.object_id,
            note_id=note.note_id,
            path=note.path,
            status=ImportStatus.SUCCESS,
            message="Ready to import",
            old_content=current_md,
            new_content=note.content_md,
            object_guid=note.object_guid,
        )

    def _get_current_note_html(self, note: NoteMetadata) -> Optional[str]:
        """Query current note content from EA database.

        Returns:
            str: The note content (may be empty string if no note)
            None: If the object was not found in database
        """
        TObject = base.classes.t_object
        TAttribute = base.classes.t_attribute

        if note.note_type == NoteType.PACKAGE_MAIN:
            # Query package note from t_object (package as object)
            obj = self.parser.session.query(TObject).filter(TObject.attr_object_id == note.object_id).scalar()
            if obj is None:
                return None
            # Apply strip_html to match how ModelParser stores notes
            return strip_html(obj.attr_note or "", special=True)

        elif note.note_type in (NoteType.PACKAGE_UNLINKED, NoteType.CLASS_LINKED, NoteType.ATTRIBUTE_LINKED):
            # Query linked/unlinked note from t_object
            note_obj = self.parser.session.query(TObject).filter(TObject.attr_object_id == note.note_id).scalar()
            if note_obj is None:
                return None
            return note_obj.attr_note or ""

        elif note.note_type == NoteType.CLASS_MAIN:
            # Query class note
            obj = self.parser.session.query(TObject).filter(TObject.attr_object_id == note.object_id).scalar()
            if obj is None:
                return None
            # Apply strip_html to match how ModelParser stores notes
            return strip_html(obj.attr_note or "", special=True)

        elif note.note_type == NoteType.ATTRIBUTE_MAIN:
            # Query attribute note using GUID (attr_object_id is not unique - it's the parent class ID)
            attr = self.parser.session.query(TAttribute).filter(TAttribute.attr_ea_guid == note.object_guid).scalar()
            if attr is None:
                return None
            # Apply strip_html to match how ModelParser stores notes
            return strip_html(attr.attr_notes or "", special=True)

        return None

    def _commit_imports(self):
        """Commit successful imports to database."""
        for result in self.results:
            if result.status != ImportStatus.SUCCESS:
                continue

            # Convert markdown back to HTML
            html_content = markdown.markdown(result.new_content, extensions=["extra", "sane_lists"])

            # Convert to EA-compatible HTML format (<b> instead of <strong>, etc.)
            html_content = convert_to_ea_html(html_content)

            # Update database based on note type
            self._update_note_in_database(result, html_content)

        # Commit all changes
        self.parser.session.commit()

    def _update_note_in_database(self, result: NoteImportResult, html_content: str):
        """Update a single note in the EA database."""
        TObject = base.classes.t_object
        TAttribute = base.classes.t_attribute

        if result.note_type == NoteType.PACKAGE_MAIN:
            obj = self.parser.session.query(TObject).filter(TObject.attr_object_id == result.object_id).first()
            if obj:
                obj.attr_note = html_content

        elif result.note_type in (NoteType.PACKAGE_UNLINKED, NoteType.CLASS_LINKED, NoteType.ATTRIBUTE_LINKED):
            note_obj = self.parser.session.query(TObject).filter(TObject.attr_object_id == result.note_id).first()
            if note_obj:
                note_obj.attr_note = html_content

        elif result.note_type == NoteType.CLASS_MAIN:
            obj = self.parser.session.query(TObject).filter(TObject.attr_object_id == result.object_id).first()
            if obj:
                obj.attr_note = html_content

        elif result.note_type == NoteType.ATTRIBUTE_MAIN:
            # Use GUID for attribute lookup (attr_object_id is not unique - it's the parent class ID)
            attr = self.parser.session.query(TAttribute).filter(TAttribute.attr_ea_guid == result.object_guid).first()
            if attr:
                attr.attr_notes = html_content

    def _generate_summary(self) -> ImportSummary:
        """Generate import summary from results."""
        status_counts = {
            ImportStatus.SUCCESS: 0,
            ImportStatus.CHECKSUM_MISMATCH: 0,
            ImportStatus.CONTENT_UNCHANGED: 0,
            ImportStatus.NOT_FOUND: 0,
            ImportStatus.ERROR: 0,
        }

        for result in self.results:
            status_counts[result.status] += 1

        return ImportSummary(
            total_notes=len(self.results),
            imported=status_counts[ImportStatus.SUCCESS],
            skipped_checksum=status_counts[ImportStatus.CHECKSUM_MISMATCH],
            skipped_unchanged=status_counts[ImportStatus.CONTENT_UNCHANGED],
            not_found=status_counts[ImportStatus.NOT_FOUND],
            errors=status_counts[ImportStatus.ERROR],
            results=self.results,
        )
