"""Stuff related to application configuration."""

from pydantic import BaseModel, ConfigDict
from typing import TypeAlias, List, Dict, Optional

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


class Configuration(BaseModel):
    stereotypes: ConfigurationStereotypes = ConfigurationStereotypes()
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
    #: List of supported primitive types. For those types we don't look for connection in attribute.
    primitive_types: List[str] = [
        "short",
        "unsigned short",
        "long",
        "unsigned long",
        "long long",
        "unsigned long long",
        "float",
        "double",
        "long double",
        "char",
        "wchar",
        "boolean",
        "octet",
        "string",
        "wstring",
    ]
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
        # "attribute.notes",
        "struct.name_camel_convention",
        "struct.notes",
        "package.stereotypes",
        "package.name_snake_convention",
        "package.notes",
    ]
    #: Enable unused class detection and filtering
    filter_unused_classes: bool = False
    #: Property that marks root classes for unused detection (e.g., "ext::interface")
    unused_root_property: str = "ext::interface"
