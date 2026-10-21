"""IDL diff of a session's staged changes: eaidl's IDL generated from the model as it is and with the changes applied."""

from __future__ import annotations

import difflib
import logging
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from eacore.backends.sql import SqlBackend
from eacore.changes import Delete, Insert
from eacore.records import RecordSet, Ref
from eaedit import resolve
from eaidl.config import Configuration
from eaidl.generate import generate
from eaidl.load import ModelParser
from eaidl.utils import load_config


@dataclass
class IdlDiff:
    name: str
    diff: str = ""
    error: str | None = None
    outside_roots: list[str] = field(default_factory=list)

    def text(self) -> str:
        parts = []
        if self.error:
            parts.append(f"IDL generation failed: {self.error}")
        elif self.diff:
            parts.append(self.diff.rstrip("\n"))
        else:
            parts.append("No IDL differences.")
        if self.outside_roots:
            parts.append("changes outside the IDL roots: " + ", ".join(self.outside_roots))
        return "\n".join(parts)


def _generate(config: Configuration, path: Path) -> str:
    config = config.model_copy(update={"database_url": f"sqlite:///{path.as_posix()}"})
    # eaidl logs progress and warnings; keep them out of the caller's output.
    previous = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    try:
        return generate(config, ModelParser(config).load())
    finally:
        logging.disable(previous)


def _root_keys(rs: RecordSet, roots: list[str]) -> set[str]:
    """Keys of the packages eaidl takes as roots: matched by GUID when written ``{...}``, else by name."""
    found = set()
    for package in rs.records("t_package"):
        guid, name = package.key, package.values.get("attr_name")
        if any(root == guid if root.startswith("{") else root == name for root in roots):
            found.add(package.key)
    return found


def _under(rs: RecordSet, package: Ref, roots: set[str]) -> bool:
    seen = set()
    record = rs.resolve(package)
    while record is not None and record.key not in seen:
        if record.key in roots:
            return True
        seen.add(record.key)
        parent = record.values.get("attr_parent_id")
        record = rs.resolve(parent) if isinstance(parent, Ref) else None
    return False


REPOSITORY_WIDE = "(repository-wide)"


def _outside_roots(session, changes, roots: list[str]) -> list[str]:
    keys = _root_keys(session.working, roots) | _root_keys(session.original, roots)
    outside: dict[str, None] = {}
    repository_wide = False
    for change in [*changes.inserts, *changes.updates, *changes.deletes]:
        if isinstance(change, Insert):
            rs, table, key = session.working, change.record.table, change.record.key
        elif isinstance(change, Delete):
            rs, table, key = session.original, change.table, change.key
        else:
            rs, table, key = session.working, change.table, change.key
        row = rs.get(table, key)
        if table == "t_object" and row is not None and row.values.get("attr_object_type") == "Package":
            continue  # a package's element row: its t_package row says the same, and it sits in the parent
        package = rs.owner_package(Ref(table, key))
        if package is None:
            repository_wide = True
        elif not _under(rs, package, keys):
            outside[resolve.qualified_name(rs, package)] = None
    return [*sorted(outside), *([REPOSITORY_WIDE] if repository_wide else [])]


def _copy_model(path: Path, directory: str) -> Path:
    copy = Path(directory) / path.name
    shutil.copyfile(path, copy)
    # A model EA has open may be in WAL mode: its latest pages are in the -wal file.
    for suffix in ("-wal", "-shm"):
        side = path.with_name(path.name + suffix)
        if side.exists():
            shutil.copyfile(side, copy.with_name(copy.name + suffix))
    return copy


def idl_diff(session, config_path: Path) -> IdlDiff:
    """Unified diff of the IDL for ``config_path`` before and after the session's staged changes.

    Never raises: every failure comes back as ``error``. The model file is only copied, never opened by eaidl.
    """
    name = Path(session.path).stem
    result = IdlDiff(name)
    try:
        config = load_config(config_path)
        changes = session.changes()
        result.outside_roots = _outside_roots(session, changes, list(config.root_packages))
        with (
            tempfile.TemporaryDirectory(prefix="eaedit-idl-") as before_dir,
            tempfile.TemporaryDirectory(prefix="eaedit-idl-") as after_dir,
        ):
            before = _generate(config, _copy_model(session.path, before_dir))
            copy = _copy_model(session.path, after_dir)
            if not changes.is_empty():
                backend = SqlBackend.for_file(copy)
                try:
                    backend.load()
                    backend.apply(changes)
                finally:
                    backend.close()
            after = _generate(config, copy)
    except Exception as error:  # eaidl raises whatever it likes on a model it cannot generate from
        message = " ".join(str(error).split()) or type(error).__name__
        cause = error.__cause__
        if cause is not None:
            message += f" ({type(cause).__name__}: {' '.join(str(cause).split())})"
        result.error = f"{type(error).__name__}: {message}"
        return result
    result.diff = "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            f"before/{name}.idl",
            f"after/{name}.idl",
        )
    )
    return result
