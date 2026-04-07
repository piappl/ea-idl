"""Stuff related to application configuration."""

from pydantic import BaseModel, ConfigDict
from typing import TypeAlias, List, Dict, Optional, Literal

#: General JSON type
JSON: TypeAlias = dict[str, "JSON"] | list["JSON"] | str | int | float | bool | None


class AnnotationType(BaseModel):
    """Definition of IDL annotation.

    It can also be called tag, property or custom property depending on origin.

    It is normally stored in property table, but this is not the rule (final is stored as custom property in xref).
    EA user interface call them tags.

    This configures mapping of single property to our IDL requirements.
    Some are converted to standard IDL annotations, other to custom ones.

    We assume one value for now.

    """

    #: Name of IDL annotation.
    idl_name: Optional[str] = None
    #: True if it is standard IDL annotation (like min or max)
    idl_default: bool
    #: Types, needed for non IDL default attributes with values
    idl_types: List[str] = []
    #: Description, to comment out non IDL default attributes.
    notes: str = ""
    #: Alternative names that map to this annotation (e.g., EA tag names before renaming)
    aliases: List[str] = []


class ConfigurationStereotypes(BaseModel):
    """Configuration for stereotypes.

    We assume that all "class" like types have a common stereotype.
    Second stereotype should be IDL related.
    """

    main_class: str = "DataElement"
    package: str = "DataModel"
    idl_struct: str = "idlStruct"
    idl_union: str = "idlUnion"
    idl_enum: str = "idlEnum"
    idl_map: str = "idlMap"
    idl_map_key: str = "key"
    idl_map_value: str = "value"
    idl_typedef: str = "idlTypedef"


class ConfigurationSpellcheck(BaseModel):
    """Configuration for spellchecking."""

    #: Enable spellchecking
    enabled: bool = True
    #: Check notes/documentation fields
    check_notes: bool = True
    #: Check identifiers (class names, attribute names, package names)
    check_identifiers: bool = True
    #: Minimum word length to check (default 3, avoids checking "id", "db", etc.)
    min_word_length: int = 3
    #: Custom words to add to dictionary (project-specific terms, abbreviations)
    custom_words: List[str] = []
    #: Auto-learn words from model (class/attribute/package names)
    auto_learn_from_model: bool = True
    #: Language code for spellchecker (default: en)
    language: str = "en"
    #: Spellcheck backend: "pyspellchecker" (default, no system deps) or "enchant" (requires libenchant2, supports en_US/en_GB)
    backend: Literal["pyspellchecker", "enchant"] = "pyspellchecker"


class NativeDiagramStyleConfig(BaseModel):
    """Renderer-agnostic visual style for native EA diagram export.

    These values are consumed by whichever downstream renderer is used
    (SVG, Excalidraw, DrawIO, …).  Colours are CSS hex strings (#rrggbb).
    """

    # --- node colours ---
    node_header_color: str = "#4a7ab5"
    """Fill colour of the class-name header band."""
    node_header_text_color: str = "#ffffff"
    """Text colour inside the header band."""
    node_bg_color: str = "#ffffff"
    """Fill colour of the node body (attribute compartment)."""
    part_bg_color: str = "#dbeafe"
    """Fill colour of Part nodes inside composite structure diagrams."""
    node_border_color: str = "#2c5282"
    """Border / outline colour of class nodes."""
    node_border_width: int = 1
    """Border line width in pixels."""

    # --- note colours ---
    note_bg_color: str = "#fffde7"
    """Fill colour of Note objects."""
    note_border_color: str = "#f9a825"
    """Border colour of Note objects."""
    note_text_color: str = "#5d4037"
    """Text colour inside Note objects."""

    # --- connector colours ---
    connector_color: str = "#2c5282"
    """Default stroke colour for connectors."""
    connector_note_color: str = "#718096"
    """Stroke colour for NoteLink connectors (dashed)."""

    # --- canvas ---
    canvas_bg_color: str = "#f7fafc"
    """Background fill of the whole diagram canvas."""

    # --- typography ---
    font_family: str = "Arial, sans-serif"
    """Font family for all rendered text."""
    font_size: int = 11
    """Base font size (px) for node names."""
    attr_font_size: int = 10
    """Font size (px) for attribute rows."""
    note_font_size: int = 10
    """Font size (px) for Note text."""

    # --- links ---
    node_link_template: Optional[str] = None
    """
    URL template applied to every named class / part node when rendering SVG
    or Excalidraw.  Available format keys:

    * ``{name}``        — element name (e.g. ``Message``)
    * ``{object_id}``   — EA object ID integer
    * ``{type}``        — EA object type (``Class``, ``Part``, …)
    * ``{stereotype}``  — stereotype string (empty string if none)

    Example::

        node_link_template: "../types/{name}.html"

    When ``None`` (default) a stable placeholder URI ``eaidl:{name}`` is
    emitted.  Post-processors can replace these via
    :func:`~eaidl.native_diagram_svg.rewrite_svg_links`.
    Set to ``""`` (empty string) to suppress links entirely.
    """


class DiagramConfiguration(BaseModel):
    """Configuration for diagram generation."""

    #: Which renderer to use (mermaid, plantuml, or native)
    #:
    #: ``native`` renders EA diagrams directly from the QEA canvas geometry via
    #: :mod:`eaidl.native_diagram_svg`.  The auto-generated class diagram falls
    #: back to Mermaid since it has no canvas counterpart.
    renderer: Literal["mermaid", "plantuml", "native"] = "mermaid"
    #: PlantUML server URL (used when renderer is "plantuml")
    plantuml_server_url: str = "http://127.0.0.1:10005/"
    #: PlantUML request timeout in seconds
    plantuml_timeout: int = 30
    #: Maximum number of attributes to display in class diagrams (prevents overcrowding)
    max_attributes_displayed: int = 15
    #: Visual style for native diagram export (SVG, Excalidraw, DrawIO…)
    native_diagram_style: NativeDiagramStyleConfig = NativeDiagramStyleConfig()


class Configuration(BaseModel):
    stereotypes: ConfigurationStereotypes = ConfigurationStereotypes()
    spellcheck: ConfigurationSpellcheck = ConfigurationSpellcheck()
    diagrams: DiagramConfiguration = DiagramConfiguration()
    model_config = ConfigDict(extra="forbid", validate_assignment=True)
    #: List of allowed abbreviations/acronyms (e.g., ["MCM", "URI", "CQL"])
    #: Used for camelCase naming convention AND added to spellcheck dictionary
    allowed_abbreviations: List[str] = [
        "UUID",
        "GUID",
        "API",
        "URL",
        "HTTP",
        "HTTPS",
        "XML",
        "JSON",
        "SQL",
        "DB",
        "ID",
        "PK",
        "FK",
        "DTO",
        "CFG",
        "TMP",
        "ATTR",
        "IDL",
        "QEA",
        "ISO",
        "UTC",
        "UINT",
        "INT",
    ]
    #: Database connection string, see https://docs.sqlalchemy.org/en/20/core/connections.html
    database_url: str = "sqlite+pysqlite:///tests/data/nafv4.qea"
    #: Globally unique identifier (GUID) or name of root package that we want to generate for.
    root_packages: List[str] = ["core"]
    #: Name of template
    template: str = "idl.jinja2"
    #: Name of root package - it will override whatever is in model
    root_package_name: Optional[str] = None
    #: Enable map post process
    enable_maps: bool = True
    #: List of stereotypes to filter out
    filter_stereotypes: Optional[List[str]] = None
    #: List of stereotypes to privatize (replace type with 'any' instead of removing)
    private_stereotypes: Optional[List[str]] = None
    #: If True, collapse empty unions by default and use keep_union_stereotype to preserve them
    #: If False, keep empty unions by default and use collapse_union_stereotype to remove them
    collapse_empty_unions_by_default: bool = False
    #: Stereotype used to keep unions when collapse_empty_unions_by_default is True
    keep_union_stereotype: Optional[str] = "keep"
    #: Stereotype used to collapse unions when collapse_empty_unions_by_default is False
    collapse_union_stereotype: Optional[str] = "collapse"
    #: How to handle IDL reserved words: "fail" (stop), "prefix" (rename), "allow" (ignore)
    reserved_words_action: Literal["fail", "prefix", "allow"] = "fail"
    #: Prefix to use when reserved_words_action="prefix" (e.g., "idl_")
    reserved_words_prefix: str = "idl_"
    #: How to handle danger words: "fail" (stop), "warn" (log warning), "allow" (ignore)
    danger_words_action: Literal["fail", "warn", "allow"] = "warn"
    #: Prefix to use when danger_words_action="prefix" (e.g., "idl_")
    danger_words_prefix: str = "idl_"
    #: Custom list of reserved words (uses IDL_RESERVED_WORDS if empty)
    reserved_words: List[str] = []
    #: Custom list of danger words (uses DANGER_WORDS if empty)
    danger_words: List[str] = []
    #: List of packages to ignore
    ignore_packages: List[str] = []
    #: Name of minimum amount of items annotation
    min_items: str = "ext::min_items"
    #: Name of maximum amount of items annotation
    max_items: str = "ext::max_items"
    #: Name of minimum slength annotation
    min_length: str = "ext::min_length"
    #: Name of maximum length annotation
    max_length: str = "ext::max_length"
    #: Mapping of EA primitive types to IDL types.
    #: Keys are types as they appear in EA model, values are IDL types to output.
    #: For those types we don't look for connection in attribute.
    #: Common aliases like "int" map to their proper IDL equivalents.
    primitive_types: Dict[str, str] = {
        # IDL standard types (identity mapping)
        "short": "short",
        "unsigned short": "unsigned short",
        "long": "long",
        "unsigned long": "unsigned long",
        "long long": "long long",
        "unsigned long long": "unsigned long long",
        "float": "float",
        "double": "double",
        "long double": "long double",
        "char": "char",
        "wchar": "wchar",
        "boolean": "boolean",
        "octet": "octet",
        "string": "string",
        # The ea can be stupid.
        "str": "string",
        "wstring": "wstring",
        # Common aliases (mapped to IDL equivalents)
        "int": "long",  # int is not valid IDL, map to long (32-bit)
        "unsigned int": "unsigned long",  # unsigned int -> unsigned long
    }
    #: If we want to output stereotype as annotation
    annotations_from_stereotypes: List[str] = []
    annotations: Dict[str, AnnotationType] = {
        "maximum": AnnotationType(
            idl_name="max",
            idl_default=True,
        ),
        "exclusive_maximum": AnnotationType(
            idl_default=False,
            idl_types=["any value;"],
        ),
        "minimum": AnnotationType(idl_name="min", idl_default=True),
        "optional": AnnotationType(idl_name="optional", idl_default=True),
        "exclusive_minimum": AnnotationType(
            idl_default=False,
            idl_types=["any value;"],
        ),
        "max_items": AnnotationType(
            idl_default=False,
            idl_types=["unsigned long value;"],
        ),
        "min_items": AnnotationType(
            idl_default=False,
            idl_types=["unsigned long value;"],
        ),
        "min_length": AnnotationType(
            idl_default=False,
            idl_types=["unsigned long value;"],
        ),
        "max_length": AnnotationType(
            idl_default=False,
            idl_types=["unsigned long value;"],
        ),
        "unit": AnnotationType(
            idl_default=True,
        ),
        "pattern_ecma262": AnnotationType(
            idl_default=False,
            idl_types=["string value;"],
        ),
        "pattern_xsd": AnnotationType(
            idl_default=False,
            idl_types=["string value;"],
        ),
        "pattern_python": AnnotationType(
            idl_default=False,
            idl_types=["string value;"],
        ),
    }
    #: List of validation runs fail generation
    validators_fail: List[str] = [
        "attribute.name_is_reserved_word",
        "attribute.primitive_type_mapped",
        "struct.name_is_reserved_word",
        "struct.stereotypes",
        "struct.enum_prefix",
    ]
    #: List of validation runs that produce error
    validators_error: List[str] = [
        "attribute.connector_leads_to_type",
        "attribute.optional_stereotype",
        "attribute.parent_class_id_match",
        "attribute.collection_configured",
        "struct.enum_attributes",
        "struct.is_experimental",
        "package.is_experimental",
        "attribute.is_experimental",
    ]
    #: List of validation runs that produce warning
    validators_warn: List[str] = [
        "attribute.name_is_danger_word",
        "attribute.name_snake_convention",
        "struct.name_is_danger_word",
        "struct.name_camel_convention",
        "struct.typedef_has_association",
        "package.stereotypes",
        "package.name_snake_convention",
    ]
    #: List of validation runs that produce informational messages
    validators_inform: List[str] = [
        # Notes validators
        # "attribute.notes",
        "struct.notes",
        "package.notes",
        # Spellchecking validators
        "attribute.notes_spelling",
        "attribute.name_spelling",
        "struct.notes_spelling",
        "struct.name_spelling",
        "struct.linked_notes_spelling",
        "package.notes_spelling",
        "package.name_spelling",
        "package.unlinked_notes_spelling",
    ]
    #: Enable abstract class flattening (copy attributes to concrete children)
    flatten_abstract_classes: bool = True
    #: Enable unused class detection and filtering
    filter_unused_classes: bool = False
    #: Property that marks root classes for unused detection (e.g., "ext::interface")
    unused_root_property: str = "ext::interface"
    #: Output notes that are linked to classes/objects via NoteLink connectors (always loaded for spell checking)
    output_linked_notes: bool = False
    #: Output notes that are not linked to any object in packages (always loaded for spell checking)
    output_unlinked_notes: bool = False
    #: Enable recursive struct support (generates forward declarations for circular dependencies)
    allow_recursive_structs: bool = True
    #: Optional preprocessor flag name to wrap ext annotation definitions.
    #: If set, the ext annotations section will be wrapped with #ifdef or #ifndef.
    #: If None (default), no preprocessor directive is added.
    ext_ifdef_flag: Optional[str] = "LOCAL_EXT_DEFINED"
    #: If True, use #ifndef instead of #ifdef for the ext annotations section.
    #: Only applies when ext_ifdef_flag is set.
    ext_ifdef_negate: bool = False
    #: If True, emit @value annotation on enumeration attributes.
    #: When False (default), enumeration attributes are output without @value.
    enum_emit_value: bool = False

    def find_annotation(self, name: str) -> tuple[str, AnnotationType] | None:
        """Find an annotation by direct key match or alias.

        :param name: EA tag name to look up
        :return: (config_key, annotation_type) or None
        """
        if name in self.annotations:
            return (name, self.annotations[name])
        for key, annotation in self.annotations.items():
            if name in annotation.aliases:
                return (key, annotation)
        return None

    def get_idl_type(self, ea_type: str) -> str:
        """Get the IDL type for a given EA type.

        If the type is a primitive type (exists in primitive_types mapping),
        returns the mapped IDL type. Otherwise, returns the type as-is.

        :param ea_type: Type as it appears in EA model
        :return: IDL type to output
        """
        return self.primitive_types.get(ea_type, ea_type)

    def is_primitive_type(self, ea_type: str) -> bool:
        """Check if a type is a primitive type.

        :param ea_type: Type as it appears in EA model
        :return: True if type is in primitive_types mapping
        """
        return ea_type in self.primitive_types
