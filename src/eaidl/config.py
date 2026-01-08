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


class DiagramConfiguration(BaseModel):
    """Configuration for diagram generation."""

    #: Which renderer to use (mermaid or plantuml)
    renderer: Literal["mermaid", "plantuml"] = "mermaid"
    #: PlantUML server URL (used when renderer is "plantuml")
    plantuml_server_url: str = "http://127.0.0.1:10005/"
    #: PlantUML request timeout in seconds
    plantuml_timeout: int = 30
    #: Maximum number of attributes to display in class diagrams (prevents overcrowding)
    max_attributes_displayed: int = 15


class Configuration(BaseModel):
    stereotypes: ConfigurationStereotypes = ConfigurationStereotypes()
    spellcheck: ConfigurationSpellcheck = ConfigurationSpellcheck()
    diagrams: DiagramConfiguration = DiagramConfiguration()
    model_config = ConfigDict(extra="forbid", validate_assignment=True)
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
    #: Stereotype used to keep unions when we filter_stereotypes
    keep_union_stereotype: Optional[str] = "keep"
    #: Prefix reserved attributes, if None, don't prefix. Otherwise prefix.
    prefix_attributes_reserved: Optional[str] = "_"
    #: List of packages to ignore
    ignore_packages: List[str] = []
    #: Name of minimum amount of items annotation
    min_items: str = "ext::minItems"
    #: Name of maximum amount of items annotation
    max_items: str = "ext::maxItems"
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
    annotations_from_stereotypes: List[str] = ["interface"]
    annotations: Dict[str, AnnotationType] = {
        "maximum": AnnotationType(
            idl_name="max",
            idl_default=True,
        ),
        "exclusiveMaximum": AnnotationType(idl_default=False, idl_types=["any value;"]),
        "minimum": AnnotationType(idl_name="min", idl_default=True),
        "optional": AnnotationType(idl_name="optional", idl_default=True),
        "exclusiveMinimum": AnnotationType(idl_default=False, idl_types=["any value;"]),
        "maxItems": AnnotationType(idl_default=False, idl_types=["unsigned long value;"]),
        "minItems": AnnotationType(idl_default=False, idl_types=["unsigned long value;"]),
        "unit": AnnotationType(
            idl_default=True,
        ),
        "interface": AnnotationType(idl_name="interface", idl_default=False),
        "pattern": AnnotationType(
            idl_default=False,
            idl_types=["string value;"],
            notes="Regular expression to match.",
        ),
        "isFinalSpecialization": AnnotationType(idl_default=True, idl_name="final"),
    }
    #: List of validation runs fail generation
    validators_fail: List[str] = [
        "attribute.name_for_reserved_worlds",
        "attribute.primitive_type_mapped",
        "struct.name_for_reserved_worlds",
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
        "attribute.name_snake_convention",
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
