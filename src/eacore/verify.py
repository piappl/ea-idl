"""Verification helpers shared by tests and ``eacore history``."""

import shutil
import sqlite3
from contextlib import closing
from pathlib import Path

from eacore.backends.sql import SqlBackend, load_file
from eacore.diff import diff
from eacore.records import RecordSet
from eacore.tablemap import TableMap


def clear_template(template: Path, dest: Path, id_offset: int = 100000) -> Path:
    """Copy an EA template, delete every data row and push all ID sequences up by ``id_offset``.

    Rows written into the result therefore get integer IDs unlike the source's, which proves
    identity is carried by GUIDs and keys, not by integer IDs.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(template, dest)
    with closing(sqlite3.connect(dest)) as con:
        tables = [r[0] for r in con.execute("select name from sqlite_master where type='table'")]
        for table in tables:
            if not TableMap.is_system(table):
                con.execute(f'DELETE FROM "{table}"')
        con.execute(
            "INSERT INTO sqlite_sequence(name, seq) SELECT name, 0 FROM sqlite_master "
            "WHERE type='table' AND sql LIKE '%AUTOINCREMENT%' AND name NOT IN (SELECT name FROM sqlite_sequence)"
        )
        con.execute("UPDATE sqlite_sequence SET seq = seq + ?", (id_offset,))
        con.commit()
    return dest


def roundtrip(source: Path, template: Path, workdir: Path) -> tuple[RecordSet, RecordSet]:
    """Write every record of ``source`` into a cleared template; return (source, reloaded)."""
    original = load_file(source)
    target_path = clear_template(template, workdir / "roundtrip.qea")
    target = SqlBackend.for_file(target_path)
    target.apply(diff(target.load(), original))
    return original, load_file(target_path)


def diff_apply(a: Path, b: Path, workdir: Path) -> tuple[RecordSet, RecordSet]:
    """Apply diff(a, b) to a copy of ``a``; return (records of b, records of the patched copy)."""
    workdir.mkdir(parents=True, exist_ok=True)
    patched = workdir / "patched.qea"
    shutil.copyfile(a, patched)
    expected = load_file(b)
    backend = SqlBackend.for_file(patched)
    backend.apply(diff(backend.load(), expected))
    return expected, load_file(patched)
