"""Operation registry: every model edit is a function ``fn(session, **kwargs)`` run by ``Session.run``."""

from __future__ import annotations

import importlib
from typing import Callable

OPERATIONS: dict[str, Callable] = {}

_MODULES = ("packages", "elements", "tags", "attributes", "connectors", "diagrams", "query")


def operation(name: str):
    """Register ``fn(session, **kwargs) -> str | None`` (returns the primary GUID touched/created)."""

    def register(fn):
        OPERATIONS[name] = fn
        return fn

    return register


def load_all() -> None:
    """Import every ops module so they register; modules not written yet are skipped."""
    for module in _MODULES:
        name = f"{__name__}.{module}"
        try:
            importlib.import_module(name)
        except ModuleNotFoundError as exc:
            # Only the module itself being absent is tolerated; a broken import inside it is a real error.
            if exc.name != name:
                raise
