"""Parsers for references and settings EA embeds inside text columns."""

import re
from dataclasses import dataclass
from typing import Any

#: EA GUID: braces, hex digits, case as EA wrote it (often mixed).
GUID_RE = re.compile(r"\{[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\}")


def is_guid(value: Any) -> bool:
    return isinstance(value, str) and GUID_RE.fullmatch(value) is not None


def parse_kv(text: str | None) -> dict[str, str]:
    """Parse EA's ``key=value;key=value;`` strings. The first occurrence of a key wins."""
    result: dict[str, str] = {}
    for part in (text or "").split(";"):
        if "=" in part:
            key, value = part.split("=", 1)
            result.setdefault(key, value)
    return result


def duid(object_style: str | None) -> str | None:
    """Diagram-local ID of a diagram object (``DUID=`` in ``t_diagramobjects.ObjectStyle``)."""
    return parse_kv(object_style).get("DUID") or None


def link_ends(style: str | None) -> tuple[str | None, str | None]:
    """``(SOID, EOID)`` of a diagram link: DUIDs of the source and target diagram objects."""
    values = parse_kv(style)
    return values.get("SOID") or None, values.get("EOID") or None


@dataclass(frozen=True)
class Stereotype:
    name: str
    fqname: str | None
    guid: str | None


class StereoFormatError(ValueError):
    """A ``t_xref`` stereotype list that does not follow ``@STEREO;...;@ENDSTEREO;``."""


_START, _END = "@STEREO;", "@ENDSTEREO;"


def parse_stereotypes(text: str | None) -> list[Stereotype]:
    """Parse a ``t_xref`` ``Stereotypes`` description; the first entry is the primary stereotype."""
    rest = (text or "").strip()
    result = []
    while rest:
        if not rest.startswith(_START):
            raise StereoFormatError(f"expected {_START!r} at {rest[:40]!r}")
        end = rest.find(_END)
        if end < 0:
            raise StereoFormatError(f"missing {_END!r} in {text!r}")
        values = parse_kv(rest[len(_START) : end])
        if not values.get("Name"):
            raise StereoFormatError(f"stereotype without Name in {text!r}")
        result.append(Stereotype(values["Name"], values.get("FQName"), values.get("GUID")))
        rest = rest[end + len(_END) :].strip()
    return result
