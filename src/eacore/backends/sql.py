"""SQLAlchemy Core backend: load an EA repository into records and apply change sets."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import sqlalchemy as sa

from eacore.changes import ChangeSet
from eacore.naming import column_key
from eacore.records import Key, LoadIssue, Record, RecordSet, key_str
from eacore.tablemap import EA_TABLEMAP, ContentKey, GuidKey, Row, TableMap
from eacore.translate import IdMaps, RidMaps, candidate_key, decode_row, encode_value


class NotAnEaRepositoryError(ValueError):
    """The database has no EA tables."""


class ConcurrentModificationError(RuntimeError):
    """The file changed on disk since ``load()``; nothing was written."""


class RepositoryLockedError(RuntimeError):
    """Another program (usually EA) holds a lock on the repository; nothing was written."""


@dataclass
class _TableInfo:
    table: sa.Table
    #: column key -> real column name
    columns: dict[str, str]
    #: column key of the single integer primary key, if any
    surrogate: str | None


def _write_engine(url: str) -> sa.Engine:
    engine = sa.create_engine(url, connect_args={"timeout": 1.0} if url.startswith("sqlite") else {})
    if engine.dialect.name == "sqlite":

        @sa.event.listens_for(engine, "connect")
        def _no_implicit_transactions(dbapi_connection, _record):
            dbapi_connection.isolation_level = None

        @sa.event.listens_for(engine, "begin")
        def _begin_immediate(connection):
            connection.exec_driver_sql("BEGIN IMMEDIATE")

    return engine


class SqlBackend:
    def __init__(self, url: str, tablemap: TableMap = EA_TABLEMAP) -> None:
        self.url = url
        self.tablemap = tablemap
        self._sa_url = sa.engine.make_url(url)
        if self.path is not None and not self.path.is_file():
            raise FileNotFoundError(self.path)
        self._read_engine = sa.create_engine(url)
        self._write_engine = _write_engine(url)
        self._schema: dict[str, _TableInfo] = {}
        self._rids: RidMaps = {}
        self._hash: str | None = None

    @classmethod
    def for_file(cls, path: str | Path, tablemap: TableMap = EA_TABLEMAP) -> SqlBackend:
        return cls(f"sqlite+pysqlite:///{Path(path).resolve().as_posix()}", tablemap)

    @property
    def path(self) -> Path | None:
        if self._sa_url.get_backend_name() != "sqlite" or not self._sa_url.database:
            return None
        return Path(self._sa_url.database)

    def _file_hash(self) -> str | None:
        return hashlib.sha256(self.path.read_bytes()).hexdigest() if self.path else None

    def _reflect(self) -> None:
        metadata = sa.MetaData()
        metadata.reflect(bind=self._read_engine)
        self._schema = {}
        for name, table in metadata.tables.items():
            if self.tablemap.is_system(name):
                continue
            pk = list(table.primary_key.columns)
            surrogate = column_key(pk[0].name) if len(pk) == 1 and isinstance(pk[0].type, sa.Integer) else None
            self._schema[name] = _TableInfo(table, {column_key(c.name): c.name for c in table.columns}, surrogate)
        if "t_object" not in self._schema:
            raise NotAnEaRepositoryError(f"{self.url}: no t_object table")

    def _rid_column(self, info: _TableInfo):
        if info.surrogate:
            return info.table.c[info.columns[info.surrogate]]
        return sa.literal_column("rowid")

    def _read_sequences(self, conn) -> dict[str, int]:
        if self._read_engine.dialect.name != "sqlite":
            return {}
        return {name: seq for name, seq in conn.execute(sa.text("select name, seq from sqlite_sequence"))}

    def load(self) -> RecordSet:
        self._hash = self._file_hash()
        self._reflect()
        raw: dict[str, list[tuple[int, Row]]] = {}
        with self._read_engine.connect() as conn:
            for name, info in self._schema.items():
                query = sa.select(self._rid_column(info).label("__rid__"), *info.table.columns)
                raw[name] = [
                    (row["__rid__"], {column_key(c.name): row[c.name] for c in info.table.columns})
                    for row in conn.execute(query).mappings()
                ]
            sequences = self._read_sequences(conn)

        rs = RecordSet(self.tablemap)
        idmaps: IdMaps = {}
        guid_keys: dict[str, list[Key]] = {}
        # Pass 1: GUID-keyed tables first; integer references can only point at those.
        for name, rows in raw.items():
            spec = self.tablemap.spec(name)
            if isinstance(spec.key, GuidKey):
                candidates = [(rid, row.get(spec.key.column) or None) for rid, row in rows]
                guid_keys[name] = self._unique_keys(rs, name, candidates)
                if self._schema[name].surrogate:
                    idmaps[name] = {rid: key for (rid, _), key in zip(rows, guid_keys[name])}
        # Pass 2: translate references, then key the remaining tables from translated values.
        self._rids = {}
        for name, rows in raw.items():
            spec = self.tablemap.spec(name)
            info = self._schema[name]
            decoded = []
            for rid, row in rows:
                values, problems = decode_row(spec, row, idmaps)
                if info.surrogate:
                    values.pop(info.surrogate, None)
                decoded.append((rid, values, problems))
            if name in guid_keys:
                keys = guid_keys[name]
            else:
                keys = self._unique_keys(rs, name, [(rid, candidate_key(spec, values)) for rid, values, _ in decoded])
            for (rid, values, problems), key in zip(decoded, keys):
                rs.add(Record(name, key, values, rid))
                self._rids.setdefault(name, {})[key] = rid
                for p in problems:
                    rs.issues.append(LoadIssue(p.kind, name, key, p.column, p.value, p.message))

        rs.meta["sequences"] = sequences
        rs.meta["max_ids"] = {
            name: max(rid for rid, _ in rows) for name, rows in raw.items() if rows and self._schema[name].surrogate
        }
        rs.meta["unmapped_tables"] = sorted(
            name for name, rows in raw.items() if rows and not self.tablemap.is_mapped(name)
        )
        return rs

    def _info(self, table: str) -> _TableInfo:
        try:
            return self._schema[table]
        except KeyError:
            raise ValueError(f"{self.url}: table {table} does not exist") from None

    def _column(self, info: _TableInfo, key: str) -> str:
        try:
            return info.columns[key]
        except KeyError:
            raise ValueError(f"{info.table.name} has no column for {key}") from None

    def _next_id(self, conn, info: _TableInfo, sequences: dict[str, int]) -> int:
        column = info.table.c[info.columns[info.surrogate]]
        current = conn.execute(sa.select(sa.func.max(column))).scalar() or 0
        return max(current, sequences.get(info.table.name, 0)) + 1

    def apply(self, changes: ChangeSet) -> None:
        """Write ``changes`` in one transaction, touching only affected rows and columns.

        Refuses if the file changed since ``load()`` or another program holds a lock.
        IDs for new rows are allocated before anything is written, so references between new
        rows resolve; EA's schema has no foreign keys, so statement order does not matter.
        """
        if not self._schema:
            raise RuntimeError("call load() before apply()")
        if changes.is_empty():
            return
        if self._file_hash() != self._hash:
            raise ConcurrentModificationError(f"{self.path} changed since it was loaded")
        ridmaps: RidMaps = {table: dict(rids) for table, rids in self._rids.items()}
        try:
            with self._write_engine.begin() as conn:
                sequences = self._read_sequences(conn)
                next_ids: dict[str, int] = {}
                for insert in changes.inserts:
                    record = insert.record
                    info = self._info(record.table)
                    if info.surrogate:
                        new_id = next_ids.get(record.table) or self._next_id(conn, info, sequences)
                        ridmaps.setdefault(record.table, {})[record.key] = new_id
                        next_ids[record.table] = new_id + 1
                for delete in changes.deletes:
                    info = self._info(delete.table)
                    rid = self._rids[delete.table][delete.key]
                    conn.execute(sa.delete(info.table).where(self._rid_column(info) == rid))
                    ridmaps[delete.table].pop(delete.key, None)
                for update in changes.updates:
                    info = self._info(update.table)
                    spec = self.tablemap.spec(update.table)
                    values = {
                        self._column(info, column): encode_value(spec, column, new, ridmaps)
                        for column, (_old, new) in update.changes.items()
                    }
                    rid = self._rids[update.table][update.key]
                    conn.execute(sa.update(info.table).where(self._rid_column(info) == rid).values(values))
                for insert in changes.inserts:
                    record = insert.record
                    info = self._info(record.table)
                    spec = self.tablemap.spec(record.table)
                    values = {
                        self._column(info, column): encode_value(spec, column, value, ridmaps)
                        for column, value in record.values.items()
                    }
                    if info.surrogate:
                        values[info.columns[info.surrogate]] = ridmaps[record.table][record.key]
                    result = conn.execute(sa.insert(info.table).values(values))
                    if not info.surrogate:
                        ridmaps.setdefault(record.table, {})[record.key] = result.lastrowid
        except sa.exc.OperationalError as exc:
            if "locked" in str(exc).lower() or "busy" in str(exc).lower():
                raise RepositoryLockedError(f"{self.path} is locked by another program") from exc
            raise
        self._rids = ridmaps
        self._hash = self._file_hash()

    def _unique_keys(self, rs: RecordSet, table: str, candidates: list[tuple[int, Key | None]]) -> list[Key]:
        """Make keys unique: missing GUIDs and duplicates get a suffix and are reported."""
        spec = self.tablemap.spec(table)
        seen: dict[Key, int] = {}
        keys: list[Key] = []
        for rid, key in candidates:
            if key is None:
                rs.issues.append(LoadIssue("missing_guid", table, None, None, None, f"row {rid} has no GUID"))
                key = ("#no-guid", rid)
            count = seen.get(key, 0)
            seen[key] = count + 1
            if count:
                legitimate = isinstance(spec.key, ContentKey) or (isinstance(key, tuple) and key[-1] == "#no-duid")
                if not legitimate:
                    rs.issues.append(
                        LoadIssue("duplicate_key", table, key, None, None, f"{count + 1} rows share key {key_str(key)}")
                    )
                key = (key, "#dup", count)
            keys.append(key)
        return keys


def load_file(path: str | Path) -> RecordSet:
    """Load a ``.qea``/``.qeax`` file."""
    return SqlBackend.for_file(path).load()
