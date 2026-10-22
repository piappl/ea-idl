"""Workspace: one model file, a reloadable read-only snapshot, and at most one editing session.

The snapshot serves exploration. It is keyed by the file's SHA-256 (database plus ``-wal``, as eacore hashes it),
so it reloads whenever EA, git or a commit changes the file. The editing session saves its whole operation log to
``<out_dir>/working.yaml`` after every operation, with its focus (package GUIDs) and policy, so a restart can resume
it with ``open_session(resume=True)``. A resume that stops at a failing operation keeps the full log beside it in
``working.rejected.yaml``.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from eacore.backends.sql import file_hash
from eacore.changes import ChangeSet
from eaedit import changefile
from eaedit.errors import EaeditError, InvalidOperationError
from eaedit.resolve import guid_of
from eaedit.session import LoggedOp, OpResult, Session

WORKING_FILE = "working.yaml"
#: The full log of a resume that stopped at a failing operation (working.yaml then holds the replayed prefix).
REJECTED_FILE = "working.rejected.yaml"
#: Longest shown call of a failing operation.
_CALL_LIMIT = 300
#: Why a stale session cannot commit, and the two ways on.
STALE = "the model changed on disk: open_session(resume=True) replays your edits onto it, or discard()"
#: Why a read-only model refuses to edit.
READ_ONLY = "the model is opened read-only; open it again without read_only to edit"


@dataclass
class Config:
    model: Path
    catalogues: list[Path] = field(default_factory=list)
    idl_configs: list[Path] = field(default_factory=list)
    author: str | None = None
    timezone: str | None = None
    focus: list[str] = field(default_factory=list)
    policy: str = "connected"
    out_dir: Path | None = None  # default: <model dir>/eaedit-out
    read_only: bool = False

    def __post_init__(self) -> None:
        self.model = Path(self.model)
        if self.out_dir is None:
            self.out_dir = self.model.parent / "eaedit-out"
        self.out_dir = Path(self.out_dir)


@dataclass
class OpenResult:
    """What ``open_session`` reports: a message for the agent, and how many logged operations were replayed.

    ``resumed`` is the number of operations now in the session, ``total`` the number found in the working file
    (both 0 for a fresh session).
    """

    message: str
    resumed: int = 0
    total: int = 0


class Workspace:
    def __init__(self, config: Config) -> None:
        self.config = config
        self._snapshot: Session | None = None
        self._snapshot_hash: str | None = None
        self._session: Session | None = None
        self._session_hash: str | None = None

    @property
    def working_file(self) -> Path:
        return self.config.out_dir / WORKING_FILE

    @property
    def rejected_file(self) -> Path:
        return self.config.out_dir / REJECTED_FILE

    @property
    def session(self) -> Session | None:
        return self._session

    def _open(self, focus: list[str], policy: str) -> Session:
        c = self.config
        return Session.open(
            c.model, focus=focus, policy=policy, catalogues=c.catalogues, author=c.author, timezone=c.timezone
        )

    def snapshot(self) -> Session:
        """A read-only session (policy "off", never run on) over the file as it is now."""
        current = file_hash(self.config.model)
        if self._snapshot is None or current != self._snapshot_hash:
            if self._snapshot is not None:
                self._snapshot.backend.close()
            self._snapshot = self._open([], "off")
            self._snapshot_hash = current
        return self._snapshot

    def open_session(
        self, focus: list[str] | None = None, policy: str | None = None, resume: bool = False
    ) -> OpenResult:
        self._writable()
        if self._session is not None:
            if not (resume and self.stale()):
                raise EaeditError("a session is already open; discard or commit first")
            # rebase: the working file already holds every operation, so close and replay it onto the new file
            self._close(keep_working_file=True)
        saved = self.working_file.is_file()
        if saved and not resume and self.saved_ops():
            raise EaeditError("a saved session exists: open_session(resume=True) or discard() first")
        # A resumed session keeps the focus and policy it was saved with, unless new ones are given.
        stored = self._saved_header() if resume and saved else {}
        if focus is None:
            focus = stored["focus"] if isinstance(stored.get("focus"), list) else self.config.focus
        policy = policy or stored.get("policy") or self.config.policy
        digest = file_hash(self.config.model)
        session = self._open(focus, policy)
        result = OpenResult("session opened")
        if resume and saved:
            try:
                result = self._resume(session)
            except BaseException:
                session.backend.close()
                raise
        self._session, self._session_hash = session, digest
        if resume and saved:
            self.save()
        return result

    def saved_ops(self) -> list:
        """The operations in the working file; an unreadable file is an error that says to discard it."""
        try:
            return changefile.load(self.working_file)
        except (yaml.YAMLError, InvalidOperationError) as exc:
            raise _unreadable(self.working_file, exc) from None

    def _saved_header(self) -> dict:
        try:
            return changefile.header(self.working_file)
        except (yaml.YAMLError, InvalidOperationError) as exc:
            raise _unreadable(self.working_file, exc) from None

    def _resume(self, session: Session) -> OpenResult:
        ops = self.saved_ops()
        for index, op in enumerate(ops, 1):
            try:
                changefile.replay(session, [op])
            except Exception as exc:
                # run() rolled the failing operation back; the session keeps the prefix, the full log is kept aside
                shutil.copyfile(self.working_file, self.rejected_file)
                later = len(ops) - index
                msg = (
                    f"resumed {index - 1} of {len(ops)}; op {index} {_call(op)} failed: {exc}; "
                    f"{later} later operation(s) not replayed; the full log is kept in {self.rejected_file}"
                )
                return OpenResult(msg, index - 1, len(ops))
        return OpenResult(f"resumed {len(ops)} of {len(ops)}", len(ops), len(ops))

    def _writable(self) -> None:
        if self.config.read_only:
            raise EaeditError(READ_ONLY)

    def require_session(self) -> Session:
        self._writable()
        if self._session is None:
            raise EaeditError("no session is open; call open_session first")
        return self._session

    def save(self) -> None:
        session = self.require_session()
        self.config.out_dir.mkdir(parents=True, exist_ok=True)
        focus = []
        for ref in session.scope.focus:
            record = session.original.resolve(ref) or session.working.resolve(ref)
            if record is not None and guid_of(record):
                focus.append(guid_of(record))
        changefile.save(session, self.working_file, extra={"focus": focus, "policy": session.scope.policy})

    def run(self, op: str, args: dict) -> OpResult:
        result = self.require_session().run(op, **args)
        self.save()
        return result

    def undo(self) -> str:
        undone = self.require_session().undo()
        self.save()
        return undone.name

    def stale(self) -> bool:
        """The model file differs from what it was when the session opened."""
        return self._session is not None and file_hash(self.config.model) != self._session_hash

    def _close(self, keep_working_file: bool = False) -> None:
        if self._session is not None:
            self._session.backend.close()
        self._session = self._session_hash = None
        if not keep_working_file:
            self.working_file.unlink(missing_ok=True)

    def discard(self) -> None:
        self._writable()
        self._close()

    def close(self) -> None:
        """Let go of the model file; the working file stays, so open_session(resume=True) brings the edits back."""
        self._close(keep_working_file=True)
        if self._snapshot is not None:
            self._snapshot.backend.close()
        self._snapshot = self._snapshot_hash = None

    def commit(self) -> ChangeSet:
        session = self.require_session()
        if self.stale():
            raise EaeditError(STALE)
        changes = session.commit()
        self._close()
        return changes


def _call(op: LoggedOp) -> str:
    """``name(arg=value, ...)`` of a logged operation, cut to a readable length."""
    text = f"{op.name}({', '.join(f'{k}={v!r}' for k, v in op.args.items())})"
    return text if len(text) <= _CALL_LIMIT else text[: _CALL_LIMIT - 2] + "…)"


def _unreadable(path: Path, exc: Exception) -> EaeditError:
    reason = " ".join(str(exc).split())  # one line: YAML errors span several
    return EaeditError(f"{path} is unreadable ({reason}); discard() it")
