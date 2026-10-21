"""Workspace: one model file, a reloadable read-only snapshot, and at most one editing session.

The snapshot serves exploration. It is keyed by the file's SHA-256 (database plus ``-wal``, as eacore hashes it),
so it reloads whenever EA, git or a commit changes the file. The editing session saves its whole operation log to
``<out_dir>/working.yaml`` after every operation, so a restart can resume it with ``open_session(resume=True)``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from eacore.backends.sql import SqlBackend
from eaedit import changefile
from eaedit.errors import EaeditError
from eaedit.session import OpResult, Session

WORKING_FILE = "working.yaml"


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


def file_hash(path: Path) -> str:
    """eacore's hash of the model file (including its ``-wal``)."""
    backend = SqlBackend.for_file(path)
    try:
        digest = backend._file_hash()
    finally:
        backend.close()
    assert digest is not None
    return digest


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
        if self._session is not None:
            raise EaeditError("a session is already open; discard or commit first")
        focus = self.config.focus if focus is None else focus
        policy = policy or self.config.policy
        digest = file_hash(self.config.model)
        session = self._open(focus, policy)
        result = OpenResult("session opened")
        if resume and self.working_file.is_file():
            result = self._resume(session)
        self._session, self._session_hash = session, digest
        if session.log or self.working_file.is_file():
            self._save()
        return result

    def _resume(self, session: Session) -> OpenResult:
        ops = changefile.load(self.working_file)
        for index, op in enumerate(ops, 1):
            try:
                changefile.replay(session, [op])
            except Exception as exc:
                # run() rolled the failing operation back; it and the later ones are dropped
                msg = f"resumed {index - 1} of {len(ops)}; op {index} ({op.name}) failed: {exc}"
                return OpenResult(msg, index - 1, len(ops))
        return OpenResult(f"resumed {len(ops)} of {len(ops)}", len(ops), len(ops))

    def _require(self) -> Session:
        if self._session is None:
            raise EaeditError("no session is open; call open_session first")
        return self._session

    def _save(self) -> None:
        self.config.out_dir.mkdir(parents=True, exist_ok=True)
        changefile.save(self._require(), self.working_file)

    def run(self, op: str, args: dict) -> OpResult:
        result = self._require().run(op, **args)
        self._save()
        return result

    def undo(self) -> str:
        undone = self._require().undo()
        self._save()
        return undone.name

    def stale(self) -> bool:
        """The model file differs from what it was when the session opened."""
        return self._session is not None and file_hash(self.config.model) != self._session_hash

    def _close(self) -> None:
        if self._session is not None:
            self._session.backend.close()
        self._session = self._session_hash = None
        self.working_file.unlink(missing_ok=True)

    def discard(self) -> None:
        self._close()

    def commit(self):
        session = self._require()
        if self.stale():
            raise EaeditError("the model changed since the session opened; discard or open_session(resume=True)")
        changes = session.commit()
        self._close()
        return changes
