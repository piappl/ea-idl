import json
import yaml
from pydantic import BaseModel, ConfigDict, ValidationError
from typing import TypeAlias, List, Dict
from pathlib import Path
import re

JSON: TypeAlias = dict[str, "JSON"] | list["JSON"] | str | int | float | bool | None


class Configuration(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)
    database_url: str = "sqlite+pysqlite:///tests/data/nafv4.qea"
    # This is guid or name of root package that we want to generate for.
    root_package: str = "core"
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
    properties: List[str] = [
        "maximum",
        "exclusiveMaximum",
        "minimum",
        "exclusiveMinimum",
        "unit",
    ]
    #: If property exists in properties list, we might also have it in here.
    #: This will convert property name.
    properties_map: Dict[str, str] = {"maximum": "max", "minimum": "min"}


def load_config_file(path: str | Path) -> JSON:
    if isinstance(path, str):
        path = Path(path)
    with open(path, encoding="UTF-8") as file:
        if path.suffix in [".yaml", ".yml"]:
            loaded = yaml.safe_load(file)
        else:
            loaded = json.load(file)
    return loaded


def load_config(file_name: str | Path) -> Configuration:
    try:
        return Configuration().model_validate(load_config_file(file_name))
    except ValidationError as error:
        raise ValueError("Error parsing configuration file") from error


# https://stackoverflow.com/questions/1128305/regex-for-pascalcased-words-aka-camelcased-with-leading-uppercase-letter
# CAMEL_CASE_RE = re.compile(r"^[A-Z]([A-Z0-9]*[a-z][a-z0-9]*[A-Z]|[a-z0-9]*[A-Z][A-Z0-9]*[a-z])[A-Za-z0-9]*")
# LOWER_CAME_CASE = re.compile(r"^[a-z]([A-Z0-9]*[a-z][a-z0-9]*[A-Z]|[a-z0-9]*[A-Z][A-Z0-9]*[a-z])[A-Za-z0-9]*")
CAMEL_CASE_RE = re.compile(r"^[A-Z](([a-z0-9]+[A-Z]?)*)$")
LOWER_CAME_CASE = re.compile(r"^[a-z](([a-z0-9]+[A-Z]?)*)$")
# https://stackoverflow.com/questions/73185030/regex-expression-for-matching-snake-case
SNAKE_CASE_RE = re.compile(r"^[a-zA-Z]+(_[a-zA-Z0-9]+)*$")
LOWER_SNAKE_CASE_RE = re.compile(r"^[a-z]+(_[a-z0-9]+)*$")


def is_camel_case(val: str) -> bool:
    return bool(re.match(CAMEL_CASE_RE, val))


def is_lower_camel_case(val: str) -> bool:
    return bool(re.match(LOWER_CAME_CASE, val))


def is_snake_case(val: str) -> bool:
    return bool(re.match(SNAKE_CASE_RE, val))


def is_lower_snake_case(val: str) -> bool:
    return bool(re.match(LOWER_SNAKE_CASE_RE, val))
