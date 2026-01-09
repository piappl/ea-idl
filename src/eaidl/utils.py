import json
import yaml
import logging
from pydantic import ValidationError
from pathlib import Path
from eaidl.config import Configuration, JSON
from typing import Any
import re


def to_bool(val: bool | int | float | str) -> bool:
    """Heuristic conversion to boolean value.

    :param val: value to be converted
    :return: boolean value
    """
    if isinstance(val, str):
        if val.lower() in ["1", "true"]:
            return True
        else:
            return False
    if val:
        return True
    return False


def try_cast(value: Any, value_type, default=None) -> Any:
    try:
        return value_type(value)
    except ValueError:
        return default


def get_prop(value: str, key: str) -> str:
    """Extract property string from xref table fields.

    We can use it to extract PROP first:

    * value="@PROP=@NAME=isFinalSpecialization@ENDNAME;@TYPE=Boolean@ENDTYPE;@VALU=-1@ENDVALU;@PRMT=@ENDPRMT;@ENDPROP;"
    * name="PROP"

    Result of that is a single property, we can get value of:

    * value="@NAME=isFinalSpecialization@ENDNAME;@TYPE=Boolean@ENDTYPE;@VALU=-1@ENDVALU;@PRMT=@ENDPRMT;"
    * name="VALU"

    Result of that is a string "-1"


    :param value: value of field to be extracted from
    :param key: key to be extracted
    :return: value.
    """
    match = re.match(f".*@{key}=(.*?)@END{key};", value)
    if match is None or match.groups(0) is None or len(match.groups(0)) == 0:
        return ""
    return match.groups("")[0]


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


def is_camel_case(val: str, allowed_abbreviations: list[str] | None = None) -> bool:
    """Check if a string is in PascalCase/CamelCase format.

    :param val: String to check
    :param allowed_abbreviations: List of allowed abbreviations (e.g., ["MCM", "URI", "CQL"])
    :return: True if string matches PascalCase convention
    """
    if allowed_abbreviations:
        # Sort abbreviations by length (longest first) to avoid partial replacements
        sorted_abbrevs = sorted(allowed_abbreviations, key=len, reverse=True)

        # Replace each abbreviation with a placeholder that matches camel case
        # We use "Xxx" as placeholder since it's valid PascalCase
        temp_val = val
        replacements = []
        for abbrev in sorted_abbrevs:
            # Check if abbreviation appears in the string
            if abbrev in temp_val:
                placeholder = f"X{'x' * (len(abbrev) - 1)}"
                temp_val = temp_val.replace(abbrev, placeholder)
                replacements.append((abbrev, placeholder))

        # Check if the modified string is camel case
        return bool(re.match(CAMEL_CASE_RE, temp_val))

    return bool(re.match(CAMEL_CASE_RE, val))


def is_lower_camel_case(val: str) -> bool:
    return bool(re.match(LOWER_CAME_CASE, val))


def is_snake_case(val: str) -> bool:
    return bool(re.match(SNAKE_CASE_RE, val))


def is_lower_snake_case(val: str) -> bool:
    return bool(re.match(LOWER_SNAKE_CASE_RE, val))


def enum_name_from_union_attr(enum_name: str, attr_type: str) -> str:
    attr_conv = "_".join([part.upper() for part in attr_type.split("_")])
    return f"{enum_name}_{attr_conv}"


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
