"""Editing session: a working copy of a repository, changed only through journalled operations."""

from __future__ import annotations

import functools
import getpass
import inspect
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable

from eacore.backends.sql import SqlBackend
from eacore.catalogue import Catalogue, CatalogueSet
from eacore.changes import ChangeSet, Delete, Insert, Update
from eacore.diff import diff
from eacore.integrity import Issue, check
from eacore.records import Key, Record, RecordSet, Ref
from eacore.report import render_text
from eaedit import defaults, resolve
from eaedit.catalogue import load_catalogues
from eaedit.errors import CommitRefusedError, EditWarning, InvalidOperationError, NotFoundError, ScopeError
from eaedit.ops import OPERATIONS, load_all, query
from eaedit.scope import Scope

#: ``(table, key, record before the operation's first touch, or None if it did not exist)``
JournalEntry = tuple[str, Key, Record | None]

REPOSITORY = "(repository)"


@dataclass
class OpResult:
    guid: str | None
    warnings: list[EditWarning]


@dataclass
class LoggedOp:
    name: str
    args: dict[str, Any]
    at: datetime
    #: Every GUID the operation minted with ``Session.new_guid``, in order; replay queues them again.
    created: list[str] = field(default_factory=list)


@dataclass
class Preview:
    changes: ChangeSet
    report: str
    new_issues: list[Issue]
    warnings: list[EditWarning]
    touched: dict[str, int]
    outside_focus: list[str]


@dataclass
class _Done:
    """What undo needs about one finished operation."""

    journal: list[JournalEntry]
    warnings: list[EditWarning]


@dataclass
class _Running:
    journal: list[JournalEntry]
    touched: set[tuple[str, Key]]
    warnings: list[EditWarning]
    at: datetime
    created: list[str]
    minted: list[str] = field(default_factory=list)


def _clone(record: Record) -> Record:
    return Record(record.table, record.key, dict(record.values), record.rid)


@functools.cache
def _takes_guid(fn: Callable) -> bool:
    """Whether an operation has a ``guid`` parameter, so its logged arguments can carry the GUID it minted."""
    return "guid" in inspect.signature(fn).parameters


def _keywords(name: str, args: tuple, kwargs: dict) -> dict:
    """``kwargs`` with positional ``args`` bound to the operation's parameter names, as the log records them."""
    if not args:
        return kwargs
    signature = inspect.signature(OPERATIONS[name])
    try:
        bound = signature.bind(None, *args, **kwargs)
    except TypeError as exc:
        raise InvalidOperationError(f"{name}: {exc}") from None
    result: dict = {}
    for parameter, value in list(bound.arguments.items())[1:]:  # the first parameter is the session
        if signature.parameters[parameter].kind is inspect.Parameter.VAR_KEYWORD:
            result.update(value)
        else:
            result[parameter] = value
    return result


def _issue_id(issue: Issue) -> tuple:
    return (issue.severity, issue.rule, issue.ref, issue.message)


class Session:
    def __init__(
        self,
        path: Path,
        backend: SqlBackend,
        original: RecordSet,
        catalogues: CatalogueSet,
        scope: Scope,
        author: str,
        clock: Callable[[], datetime],
    ) -> None:
        self.path = path
        self.backend = backend
        self.original = original
        self.working = original.copy()
        self.catalogues = catalogues
        self.scope = scope
        self.author = author
        self.clock = clock
        self.log: list[LoggedOp] = []
        self.warnings: list[EditWarning] = []
        self._done: list[_Done] = []
        self._running: _Running | None = None
        self._baseline_issues: set[tuple] | None = None
        #: GUIDs ``new_guid`` hands out before minting fresh ones (replay seeds it per operation).
        self._guid_queue: list[str] = []

    @classmethod
    def open(
        cls,
        path: str | Path,
        focus: Iterable[str] = (),
        policy: str = "connected",
        catalogues: Iterable[str | Path | Catalogue] = (),
        infer: bool = True,
        author: str | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> Session:
        load_all()
        path = Path(path)
        backend = SqlBackend.for_file(path)
        original = backend.load()
        original.meta["path"] = str(path)
        scope = Scope([resolve.find(original, f, kinds=("package",)) for f in focus], policy)
        return cls(
            path,
            backend,
            original,
            load_catalogues(catalogues, original, infer_from_model=infer),
            scope,
            author or getpass.getuser(),
            clock or datetime.now,
        )

    # --- primitives for ops (only way ops change state) ---

    def _current(self) -> _Running:
        if self._running is None:
            raise InvalidOperationError("the working copy changes only inside an operation (Session.run)")
        return self._running

    def _journal(self, table: str, key: Key) -> None:
        op = self._current()
        if (table, key) in op.touched:
            return
        op.touched.add((table, key))
        before = self.working.get(table, key)
        op.journal.append((table, key, _clone(before) if before is not None else None))

    def put(self, record: Record) -> None:
        self._journal(record.table, record.key)
        if self.working.get(record.table, record.key) is not None:
            self.working.remove(record.table, record.key)
        self.working.add(record)

    def drop(self, table: str, key: Key) -> Record:
        self._current()
        if self.working.get(table, key) is None:
            raise NotFoundError(f"no record {table} {key}")
        self._journal(table, key)
        return self.working.remove(table, key)

    def warn(self, code: str, message: str, target: str | None = None, rule_source: str | None = None) -> None:
        self._current().warnings.append(EditWarning(code, message, target, rule_source))

    def find(self, identifier: str, kinds: Iterable[str] = ("package", "element", "attribute", "connector")) -> Ref:
        return resolve.find(self.working, identifier, kinds=kinds)

    def now(self) -> datetime:
        return self._current().at

    def created(self, guid: str) -> None:
        self._current().created.append(guid)

    def new_guid(self) -> str:
        """The GUID for a new record: the next queued one, else a fresh one. Ops mint every GUID here."""
        op = self._current()
        guid = self._guid_queue.pop(0) if self._guid_queue else defaults.new_guid()
        op.created.append(guid)
        op.minted.append(guid)
        return guid

    def queue_guids(self, guids: Iterable[str]) -> None:
        """GUIDs for the next operation's ``new_guid`` calls, in order (replay reproduces an operation's GUIDs)."""
        self._guid_queue = list(guids)

    def columns(self, table: str) -> list[str]:
        return self.backend.columns(table)

    # --- running ---

    def run(self, name: str, /, **kwargs) -> OpResult:
        fn = OPERATIONS.get(name)
        if fn is None:
            self._guid_queue = []
            raise InvalidOperationError(f"unknown operation {name!r}")
        if self._running is not None:
            # The queue belongs to the running operation, whose own run clears it when it ends.
            raise InvalidOperationError(f"{name!r} called while another operation is running")
        op = _Running([], set(), [], self.clock(), [])
        self._running = op
        try:
            guid = fn(self, **kwargs)
            self._check_scope(op)
        except BaseException:
            self._rollback(op.journal)
            raise
        finally:
            self._running = None
            self._guid_queue = []
        args = dict(kwargs)
        if op.created and "guid" not in args and _takes_guid(fn):
            args["guid"] = op.created[0]
        self.log.append(LoggedOp(name, args, op.at, list(op.minted)))
        self._done.append(_Done(op.journal, op.warnings))
        self.warnings.extend(op.warnings)
        return OpResult(guid, list(op.warnings))

    def __getattr__(self, name: str):
        # Only reached for missing attributes; touches no instance state, so copy/pickle probes are safe.
        if name in OPERATIONS:
            return lambda *args, **kwargs: self.run(name, **_keywords(name, args, kwargs))
        raise AttributeError(f"{type(self).__name__!r} object has no attribute {name!r}")

    def _check_scope(self, op: _Running) -> None:
        changes = ChangeSet()
        extra_before = {}
        for table, key, before in op.journal:
            after = self.working.get(table, key)
            if before is not None:
                extra_before[(table, key)] = before
            if before is None and after is not None:
                changes.inserts.append(Insert(after))
            elif before is not None and after is None:
                changes.deletes.append(Delete(table, key, before))
            elif before is not None and after is not None:
                old, new = before.values, after.values
                changed = {
                    c: (old.get(c), new.get(c)) for c in sorted(old.keys() | new.keys()) if old.get(c) != new.get(c)
                }
                if changed:
                    changes.updates.append(Update(table, key, changed))
        problems = self.scope.violations(changes, self.original, self.working, extra_before=extra_before)
        if not problems:
            return
        if self.scope.policy in ("package", "connected"):
            raise ScopeError("; ".join(problems))
        for problem in problems:
            op.warnings.append(EditWarning("scope", problem))

    def _rollback(self, journal: list[JournalEntry]) -> None:
        for table, key, before in reversed(journal):
            if self.working.get(table, key) is not None:
                self.working.remove(table, key)
            if before is not None:
                self.working.add(_clone(before))

    def undo(self) -> LoggedOp:
        if not self._done:
            raise InvalidOperationError("nothing to undo")
        done = self._done.pop()
        self._rollback(done.journal)
        undone = {id(w) for w in done.warnings}
        self.warnings = [w for w in self.warnings if id(w) not in undone]
        return self.log.pop()

    # --- queries (read the working copy; not operations, so not logged) ---

    def get(self, identifier: str) -> dict:
        return query.get(self, identifier)

    def list(self, package: str | None = None, recursive: bool = True) -> list[dict]:
        return query.list_(self, package, recursive)

    def tree(self, package: str | None = None) -> str:
        return query.tree(self, package)

    def search(self, text: str, stereotype: str | None = None, type: str | None = None) -> list[dict]:
        return query.search(self, text, stereotype, type)

    def find_connectors(
        self,
        source: str | None = None,
        target: str | None = None,
        type: str | None = None,
        stereotype: str | None = None,
    ) -> list[dict]:
        return query.find_connectors(self, source, target, type, stereotype)

    # --- results ---

    def changes(self) -> ChangeSet:
        return diff(self.original, self.working)

    def _new_issues(self) -> list[Issue]:
        if self._baseline_issues is None:
            self._baseline_issues = {_issue_id(i) for i in check(self.original)}
        return [i for i in check(self.working) if _issue_id(i) not in self._baseline_issues]

    def _package_name(self, rs: RecordSet, ref: Ref) -> str:
        package = rs.owner_package(ref)
        return resolve.qualified_name(rs, package) if package is not None else REPOSITORY

    def preview(self) -> Preview:
        changes = self.changes()
        touched: dict[str, int] = {}
        outside: dict[str, None] = {}
        inside = self.scope.focus_packages(self.original, self.working) if self.scope.focus else None
        for change in [*changes.inserts, *changes.updates, *changes.deletes]:
            if isinstance(change, Insert):
                rs, ref = self.working, Ref(change.record.table, change.record.key)
            else:
                rs = self.original if isinstance(change, Delete) else self.working
                ref = Ref(change.table, change.key)
            name = self._package_name(rs, ref)
            touched[name] = touched.get(name, 0) + 1
            package = rs.owner_package(ref)
            if inside is not None and (package is None or package.key not in inside):
                outside[name] = None
        return Preview(
            changes,
            render_text(changes, self.original, self.working),
            self._new_issues(),
            list(self.warnings),
            touched,
            list(outside),
        )

    def commit(self) -> ChangeSet:
        changes = self.changes()
        problems = self.scope.violations(changes, self.original, self.working)
        if problems and self.scope.policy in ("package", "connected"):
            raise ScopeError("; ".join(problems))
        errors = [i for i in self._new_issues() if i.severity == "error"]
        if errors:
            raise CommitRefusedError(errors)
        self.backend.apply(changes)
        self.original = self.working.copy()
        self._baseline_issues = None
        self._done.clear()
        self.log.clear()
        self.warnings.clear()
        return changes
