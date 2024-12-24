import json
import yaml
import logging
from pydantic import BaseModel, ConfigDict, ValidationError
from typing import TypeAlias, List, Dict, Optional
from pathlib import Path
import re

JSON: TypeAlias = dict[str, "JSON"] | list["JSON"] | str | int | float | bool | None


class PropertyType(BaseModel):
    idl_name: Optional[str] = None
    idl_default: bool
    idl_types: List[str] = []
    description: str = ""


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
    properties: Dict[str, PropertyType] = {
        "maximum": PropertyType(
            idl_name="max",
            idl_default=True,
        ),
        "exclusiveMaximum": PropertyType(idl_default=False, idl_types=["any value;"]),
        "minimum": PropertyType(idl_name="min", idl_default=True),
        "exclusiveMinimum": PropertyType(idl_default=False, idl_types=["any value;"]),
        "unit": PropertyType(
            idl_default=True,
        ),
    }


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


class LogFormatter(logging.Formatter):
    _grey = "\x1b[38;21m"
    _green = "\x1b[32m"
    _yellow = "\x1b[33;21m"
    _red = "\x1b[31;21m"
    _bold_red = "\x1b[31;1m"
    _black = "\u001b[30m"
    _yellow = "\u001b[33m"
    _blue = "\u001b[34m"
    _magenta = "\u001b[35m"
    _cyan = "\u001b[36m"
    _white = "\u001b[37m"
    _reset = "\x1b[0m"
    _bold = "\u001b[1m"
    _prefix = (
        _green
        + "%(asctime)s  "
        + _reset
        + _blue
        + "%(name)s "
        + _reset
        + _white
        + "%(funcName)s "
        + _reset
        + _bold
        + _grey
        + "%(levelname)s "
        + _reset
    )
    _message = "%(message)s"
    _formats = {
        logging.DEBUG: _prefix + _grey + _message + _reset,
        logging.INFO: _prefix + _white + _message + _reset,
        logging.WARNING: _prefix + _yellow + _message + _reset,
        logging.ERROR: _prefix + _red + _message + _reset,
        logging.CRITICAL: _prefix + _bold_red + _message + _reset,
    }

    def format(self, record):
        log_fmt = self._formats.get(record.levelno)
        formatter = logging.Formatter(log_fmt)
        return formatter.format(record)

    @classmethod
    def factory(cls):
        return cls()
