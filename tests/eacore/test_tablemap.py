import sqlite3
from pathlib import Path

from eacore.naming import column_key
from eacore.tablemap import EA_TABLEMAP, RefRule, TableMap

DATA = Path(__file__).resolve().parents[1] / "data"


def _schema(path):
    with sqlite3.connect(path) as con:
        tables = [r[0] for r in con.execute("select name from sqlite_master where type='table'")]
        return {t: {column_key(r[1]) for r in con.execute(f"pragma table_info('{t}')")} for t in tables}


def test_every_nonempty_table_is_mapped():
    with sqlite3.connect(DATA / "nafv4.qea") as con:
        tables = [r[0] for r in con.execute("select name from sqlite_master where type='table'")]
        nonempty = [t for t in tables if con.execute(f"select count(*) from '{t}'").fetchone()[0]]
    unmapped = [t for t in nonempty if not TableMap.is_system(t) and not EA_TABLEMAP.is_mapped(t)]
    assert unmapped == []


def test_rule_columns_exist_in_schema():
    schema = _schema(DATA / "nafv4.qea")
    missing = []
    for table in schema:
        spec = EA_TABLEMAP.spec(table)
        for rule in spec.rules:
            if rule.column not in schema[table]:
                missing.append(f"{table}.{rule.column}")
        if spec.owner and spec.owner not in schema[table]:
            missing.append(f"{table}.{spec.owner} (owner)")
        for column in getattr(spec.key, "columns", ()):
            if column not in schema[table]:
                missing.append(f"{table}.{column} (key)")
    assert missing == []


def test_volatile_columns_exist():
    schema = _schema(DATA / "nafv4.qea")
    assert [f"{t}.{c}" for t, c in EA_TABLEMAP.volatile if c not in schema.get(t, set())] == []


def test_ref_targets_are_mapped_tables():
    for table in ("t_object", "t_connector", "t_attribute"):
        for rule in EA_TABLEMAP.spec(table).rules:
            if isinstance(rule, RefRule):
                assert EA_TABLEMAP.is_mapped(rule.target)
