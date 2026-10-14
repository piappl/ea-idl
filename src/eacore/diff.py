"""Semantic diff between two record sets."""

from eacore.changes import ChangeSet, Delete, Insert, Update
from eacore.records import RecordSet, key_str


def diff(a: RecordSet, b: RecordSet) -> ChangeSet:
    """Changes that turn ``a`` into ``b``. Records match by (table, key), so renumbering is invisible."""
    changes = ChangeSet()
    for table in sorted(set(a.tables()) | set(b.tables())):
        keys_a, keys_b = a.keys(table), b.keys(table)
        for key in sorted(keys_a - keys_b, key=key_str):
            changes.deletes.append(Delete(table, key, a.get(table, key)))
        for key in sorted(keys_b - keys_a, key=key_str):
            changes.inserts.append(Insert(b.get(table, key)))
        for key in sorted(keys_a & keys_b, key=key_str):
            old, new = a.get(table, key).values, b.get(table, key).values
            changed = {c: (old.get(c), new.get(c)) for c in sorted(old.keys() | new.keys()) if old.get(c) != new.get(c)}
            if changed:
                changes.updates.append(Update(table, key, changed))
    return changes
