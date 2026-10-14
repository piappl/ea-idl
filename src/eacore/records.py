"""Lossless, GUID-keyed record model of an EA repository."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Iterator

if TYPE_CHECKING:
    from eacore.tablemap import TableMap

#: Record identity: a GUID string, or a tuple (natural, DUID and content keys).
Key = str | tuple


@dataclass(frozen=True)
class Ref:
    """Reference to another record; replaces a file-local integer ID."""

    table: str
    key: Key


@dataclass(frozen=True)
class TextRefs:
    """Integer IDs embedded in text, e.g. ``idref1=54;``.

    ``template`` is the original text with each ID replaced by ``{0}``, ``{1}``, ... and literal
    braces doubled, so ``template.format(*ids)`` rebuilds the text.
    """

    template: str
    refs: tuple[Ref, ...]


@dataclass
class Record:
    table: str
    key: Key
    #: Every column (by column key). References are ``Ref``/``TextRefs``; all else is raw.
    values: dict[str, Any]
    #: Backend-private row id (surrogate ID or SQLite rowid); never part of equality.
    rid: int | None = field(default=None, compare=False)


@dataclass(frozen=True)
class LoadIssue:
    """Something the loader could not translate; surfaced by the integrity checker."""

    kind: str  # "dangling" | "unexplained" | "duplicate_key" | "missing_guid"
    table: str
    key: Key | None
    column: str | None
    value: Any
    message: str


def key_str(key: Any) -> str:
    """Stable, human-readable form of a key, used for sorting and output."""
    if isinstance(key, Ref):
        return f"{key.table}:{key_str(key.key)}"
    if isinstance(key, tuple):
        return "(" + ", ".join(key_str(part) for part in key) + ")"
    return str(key)


class RecordSet:
    """All records of one repository, by table and key."""

    def __init__(self, tablemap: TableMap | None = None) -> None:
        self.tablemap = tablemap
        self.issues: list[LoadIssue] = []
        self.meta: dict[str, Any] = {}
        self._tables: dict[str, dict[Key, Record]] = {}
        self._guid_index: dict[str, list[Ref]] | None = None

    def add(self, record: Record) -> None:
        rows = self._tables.setdefault(record.table, {})
        if record.key in rows:
            raise KeyError(f"duplicate key {key_str(record.key)} in {record.table}")
        rows[record.key] = record
        self._guid_index = None

    def remove(self, table: str, key: Key) -> Record:
        record = self._tables[table].pop(key)
        self._guid_index = None
        return record

    def get(self, table: str, key: Key) -> Record | None:
        return self._tables.get(table, {}).get(key)

    def resolve(self, ref: Ref) -> Record | None:
        return self.get(ref.table, ref.key)

    def tables(self) -> list[str]:
        return sorted(name for name, rows in self._tables.items() if rows)

    def records(self, table: str) -> Iterator[Record]:
        return iter(list(self._tables.get(table, {}).values()))

    def keys(self, table: str) -> set[Key]:
        return set(self._tables.get(table, {}))

    def __len__(self) -> int:
        return sum(len(rows) for rows in self._tables.values())

    def same_records(self, other: RecordSet) -> bool:
        """True if both hold equal records in every table (row ids ignored)."""
        mine = {name: rows for name, rows in self._tables.items() if rows}
        theirs = {name: rows for name, rows in other._tables.items() if rows}
        return mine == theirs

    def by_guid(self, guid: str) -> list[Ref]:
        """Records whose ``ea_guid`` value or GUID key equals ``guid``."""
        if self._guid_index is None:
            index: dict[str, list[Ref]] = {}
            for name, rows in self._tables.items():
                for key, record in rows.items():
                    guids = {record.values.get("attr_ea_guid")}
                    if isinstance(key, str):
                        guids.add(key)
                    for guid_value in guids - {None}:
                        index.setdefault(guid_value, []).append(Ref(name, key))
            self._guid_index = index
        return self._guid_index.get(guid, [])
