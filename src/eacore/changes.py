"""Change sets: the unit of writing, and the result of diff."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from eacore.records import Key, Record


@dataclass
class Insert:
    record: Record


@dataclass
class Update:
    table: str
    key: Key
    #: column key -> (old value, new value)
    changes: dict[str, tuple[Any, Any]]


@dataclass
class Delete:
    table: str
    key: Key
    #: The deleted record, when known (used for reporting).
    record: Record | None = None


@dataclass
class ChangeSet:
    inserts: list[Insert] = field(default_factory=list)
    updates: list[Update] = field(default_factory=list)
    deletes: list[Delete] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not (self.inserts or self.updates or self.deletes)

    def __len__(self) -> int:
        return len(self.inserts) + len(self.updates) + len(self.deletes)

    def without_columns(self, columns: frozenset[tuple[str, str]]) -> ChangeSet:
        """Copy without changes to the given (table, column) pairs, e.g. volatile columns."""
        updates = []
        for update in self.updates:
            kept = {c: v for c, v in update.changes.items() if (update.table, c) not in columns}
            if kept:
                updates.append(Update(update.table, update.key, kept))
        return ChangeSet(list(self.inserts), updates, list(self.deletes))
