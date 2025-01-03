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


class Configuration(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)
    #: Database connection string, see https://docs.sqlalchemy.org/en/20/core/connections.html
    database_url: str = "sqlite+pysqlite:///tests/data/nafv4.qea"
    #: Globally unique identifier (GUID) or name of root package that we want to generate for.
    root_package: str = "core"
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
    annotations: Dict[str, AnnotationType] = {
        "maximum": AnnotationType(
            idl_name="max",
            idl_default=True,
        ),
        "exclusiveMaximum": AnnotationType(idl_default=False, idl_types=["any value;"]),
        "minimum": AnnotationType(idl_name="min", idl_default=True),
        "exclusiveMinimum": AnnotationType(idl_default=False, idl_types=["any value;"]),
        "unit": AnnotationType(
            idl_default=True,
        ),
        "pattern": AnnotationType(idl_default=False, idl_types=["string value;"], notes="Regular expression to match."),
        "isFinalSpecialization": AnnotationType(idl_default=True, idl_name="final"),
    }
