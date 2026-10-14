"""Focus and write policy: which packages a change may touch."""

from __future__ import annotations

from typing import Callable, Iterable, Mapping

from eacore.changes import ChangeSet
from eacore.records import Key, Record, RecordSet, Ref, key_str
from eacore.tablemap import EA_TABLEMAP
from eaedit.errors import InvalidOperationError
from eaedit.resolve import qualified_name

POLICIES = ("package", "connected", "advisory", "off")

Lookup = Callable[[Ref], Record | None]
ByGuid = Callable[[str], list[Ref]]


class Scope:
    def __init__(self, focus: Iterable[Ref], policy: str) -> None:
        if policy not in POLICIES:
            raise InvalidOperationError(f"unknown policy {policy!r}; expected one of {', '.join(POLICIES)}")
        self.focus = tuple(focus)
        self.policy = policy

    def focus_packages(self, *sets: RecordSet) -> set:
        """``t_package`` keys in the focus subtrees of any of the sets."""
        result: set = set()
        for rs in sets:
            children: dict[Key, list[Key]] = {}
            for pkg in rs.records("t_package"):
                parent = pkg.values.get("attr_parent_id")
                if isinstance(parent, Ref):
                    children.setdefault(parent.key, []).append(pkg.key)
            todo = [ref.key for ref in self.focus if rs.get("t_package", ref.key) is not None]
            reached: set = set()
            while todo:
                key = todo.pop()
                if key in reached:
                    continue
                reached.add(key)
                todo.extend(children.get(key, []))
            result |= reached
        return result

    def contains(self, package_key, *sets: RecordSet) -> bool:
        return package_key in self.focus_packages(*sets)

    def _package_of(self, record: Record | None, lookup: Lookup, by_guid: ByGuid):
        """Mirror of ``RecordSet.owner_package`` over callables; None when unresolvable."""
        seen: set[tuple[str, Key]] = set()
        while record is not None and (record.table, record.key) not in seen:
            seen.add((record.table, record.key))
            if record.table == "t_package":
                return record.key
            spec = EA_TABLEMAP.spec(record.table)
            if spec.owner is None:
                return None
            value = record.values.get(spec.owner)
            if isinstance(value, Ref):
                record = lookup(value)
            elif spec.owner_is_guid and isinstance(value, str):
                found = by_guid(value)
                target = next((c for c in found if c.table == "t_package"), found[0] if found else None)
                record = lookup(target) if target else None
            else:
                return None
        return None

    def owners(self, table: str, record: Record, lookup: Lookup, by_guid: ByGuid) -> tuple[set, bool]:
        """``(t_package keys owning the row, reached through a connector)``."""
        if table == "t_package":
            return {record.key}, False
        if table == "t_object" and record.values.get("attr_object_type") == "Package":
            twin = record.values.get("attr_pdata1")
            if isinstance(twin, Ref) and twin.table == "t_package":
                return {twin.key}, False
        seen: set[tuple[str, Key]] = set()
        current: Record | None = record
        while current is not None and (current.table, current.key) not in seen:
            seen.add((current.table, current.key))
            if current.table == "t_package":
                return {current.key}, False
            if current.table == "t_connector":
                ends = set()
                for column in ("attr_start_object_id", "attr_end_object_id"):
                    end = current.values.get(column)
                    key = self._package_of(lookup(end) if isinstance(end, Ref) else None, lookup, by_guid)
                    if key is not None:
                        ends.add(key)
                return (ends, True) if ends else (set(), False)
            spec = EA_TABLEMAP.spec(current.table)
            if spec.owner is None:
                return set(), False
            value = current.values.get(spec.owner)
            if isinstance(value, Ref):
                current = lookup(value)
            elif spec.owner_is_guid and isinstance(value, str):
                found = by_guid(value)
                target = next((c for c in found if c.table == "t_package"), found[0] if found else None)
                current = lookup(target) if target else None
            else:
                return set(), False
        return set(), False

    def _allowed(self, owners: set, via_connector: bool, inside: set) -> bool:
        if not self.focus:
            return True
        if not owners:
            return False
        if via_connector and self.policy != "package":
            return any(o in inside for o in owners)
        return all(o in inside for o in owners)

    def violations(
        self,
        changes: ChangeSet,
        before: RecordSet,
        after: RecordSet,
        extra_before: Mapping[tuple[str, Key], Record] = {},
    ) -> list[str]:
        if self.policy == "off" or not self.focus:
            return []
        inside = self.focus_packages(before, after)

        def from_before(ref: Ref) -> Record | None:
            return before.resolve(ref) or extra_before.get((ref.table, ref.key))

        def from_after(ref: Ref) -> Record | None:
            return after.resolve(ref) or from_before(ref)

        def guids(*sets: RecordSet) -> ByGuid:
            def lookup(guid: str) -> list[Ref]:
                return [ref for rs in sets for ref in rs.by_guid(guid)]

            return lookup

        def names(keys: set) -> str:
            out = []
            for key in sorted(keys, key=key_str):
                ref = Ref("t_package", key)
                rs = after if after.get("t_package", key) else before
                out.append(qualified_name(rs, ref) if rs.get("t_package", key) else key_str(key))
            return ", ".join(out) or "no package"

        problems: list[str] = []

        def check(verb: str, table: str, key: Key, record: Record | None, lookup: Lookup, by_guid: ByGuid, side=""):
            owners, via = self.owners(table, record, lookup, by_guid) if record else (set(), False)
            if not self._allowed(owners, via, inside):
                problems.append(f"{verb} {table} {key_str(key)} {side}owned by {names(owners)} is outside the focus")

        for ins in changes.inserts:
            rec = after.get(ins.record.table, ins.record.key) or ins.record
            check("insert", rec.table, rec.key, rec, from_after, guids(after, before))
        for upd in changes.updates:
            old, new = before.get(upd.table, upd.key), after.get(upd.table, upd.key)
            if old is not None:
                check("update", upd.table, upd.key, old, from_before, guids(before), "(before) ")
            if new is not None:
                check("update", upd.table, upd.key, new, from_after, guids(after, before), "(after) ")
        for dele in changes.deletes:
            rec = dele.record or before.get(dele.table, dele.key) or extra_before.get((dele.table, dele.key))
            check("delete", dele.table, dele.key, rec, from_after, guids(after, before))
        return problems
