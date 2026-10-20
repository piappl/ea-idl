"""Operation registry: every model edit is a function ``fn(session, **kwargs)`` run by ``Session.run``."""

from __future__ import annotations

import importlib
from typing import Callable

OPERATIONS: dict[str, Callable] = {}

_MODULES = ("packages", "elements", "tags", "attributes", "connectors", "diagrams", "notes", "layout", "query")


def operation(name: str):
    """Register ``fn(session, **kwargs) -> str | None`` (returns the primary GUID touched/created)."""

    def register(fn):
        from eaedit.session import Session  # ops modules load after the session module

        if name in dir(Session) or name in Session.__annotations__:
            # ``session.<name>`` would reach the attribute, never the operation.
            raise ValueError(f"operation name {name!r} is taken by a Session attribute")
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
