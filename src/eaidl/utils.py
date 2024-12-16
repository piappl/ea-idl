import json
import yaml
from pydantic import BaseModel, ConfigDict, ValidationError
from typing import TypeAlias, List
from pathlib import Path

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
