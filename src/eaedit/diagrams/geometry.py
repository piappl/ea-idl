"""Diagram object rectangles: SVG orientation in eaedit, EA's negative-y columns in the database."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from eaedit.errors import InvalidOperationError

#: ``(left, top, right, bottom)``, y growing downwards, all non-negative.
Rect = tuple[int, int, int, int]


def check_rect(rect: Sequence[int]) -> Rect:
    """``rect`` as a tuple; any 4-sequence is accepted, as the change file stores it as a list."""
    try:
        left, top, right, bottom = (int(v) for v in rect)
    except (TypeError, ValueError):
        raise InvalidOperationError(f"a rectangle is (left, top, right, bottom), not {rect!r}") from None
    if min(left, top) < 0 or right <= left or bottom <= top:
        raise InvalidOperationError(f"rectangle {rect!r} must have 0 <= left < right and 0 <= top < bottom")
    return left, top, right, bottom


def to_ea(rect: Sequence[int]) -> dict[str, int]:
    """Columns of ``t_diagramobjects``: EA stores y negated (RectTop/RectBottom of the hand-made p2 rows)."""
    left, top, right, bottom = check_rect(rect)
    return {"attr_rectleft": left, "attr_recttop": -top, "attr_rectright": right, "attr_rectbottom": -bottom}


def from_ea(values: dict[str, Any]) -> Rect:
    """The rectangle of a ``t_diagramobjects`` row."""
    return (
        values["attr_rectleft"],
        -values["attr_recttop"],
        values["attr_rectright"],
        -values["attr_rectbottom"],
    )
