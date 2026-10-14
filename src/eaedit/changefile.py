"""Change files: a session's operation log as YAML, and replaying one onto another session."""

from __future__ import annotations

import inspect
from datetime import datetime
from pathlib import Path
from typing import Iterable

import yaml

from eaedit.defaults import timestamp
from eaedit.errors import InvalidOperationError
from eaedit.ops import OPERATIONS, load_all
from eaedit.session import LoggedOp, OpResult, Session

VERSION = 1
AT_FORMAT = "%Y-%m-%d %H:%M:%S"


def save(session: Session, path: str | Path) -> None:
    data = {
        "eaedit": VERSION,
        "source": session.path.name,
        "author": session.author,
        "ops": [
            {"op": op.name, "at": timestamp(op.at), "args": dict(op.args), "created": list(op.created)}
            for op in session.log
        ],
    }
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)


def load(path: str | Path) -> list[LoggedOp]:
    return _read(path)[1]


def _read(path: str | Path) -> tuple[str | None, list[LoggedOp]]:
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict) or data.get("eaedit") != VERSION:
        found = data.get("eaedit") if isinstance(data, dict) else None
        raise InvalidOperationError(f"{path}: not an eaedit change file of version {VERSION} (found {found!r})")
    ops = []
    for index, entry in enumerate(data.get("ops") or [], 1):
        try:
            at = entry["at"]
            ops.append(
                LoggedOp(
                    entry["op"],
                    dict(entry.get("args") or {}),
                    at if isinstance(at, datetime) else datetime.strptime(str(at), AT_FORMAT),
                    list(entry.get("created") or []),
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise InvalidOperationError(f"{path}: operation {index} is malformed: {exc}") from None
    return data.get("author"), ops


def _call(op: LoggedOp) -> tuple[dict, list[str]]:
    """Arguments for ``Session.run`` and the GUIDs to queue so the operation mints what it minted before."""
    args, queue = dict(op.args), list(op.created)
    fn = OPERATIONS.get(op.name)
    if fn is None:
        return args, queue  # run() reports the unknown name
    # The primary GUID is passed explicitly, so it is not minted again: drop it from the queue.
    if queue and queue[0] == args.get("guid"):
        queue.pop(0)
    try:
        inspect.signature(fn).bind(None, **args)
    except TypeError as exc:
        raise InvalidOperationError(f"{op.name}: {exc}") from None
    return args, queue


def replay(session: Session, source: str | Path | Iterable[LoggedOp], author: str | None = None) -> list[OpResult]:
    """Run each logged operation on ``session`` with the clock fixed to its time and its GUIDs reproduced.

    Rows record who made the change, so ``author``, else the change file's author, stands in for the session's
    while it replays.
    """
    load_all()
    file_author, ops = _read(source) if isinstance(source, (str, Path)) else (None, list(source))
    author = author or file_author
    results = []
    for index, op in enumerate(ops, 1):
        clock, own_author = session.clock, session.author
        session.clock = lambda at=op.at: at
        session.author = author or own_author
        try:
            args, queue = _call(op)
            session.queue_guids(queue)
            results.append(session.run(op.name, **args))
        except Exception as exc:  # any failure, so the CLI's one-line error names the operation
            exc.add_note(f"in operation {index} ({op.name}) of the change file")
            raise
        finally:
            session.clock, session.author = clock, own_author
            session.queue_guids([])
    return results
