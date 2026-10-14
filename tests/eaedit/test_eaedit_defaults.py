import re
from collections import Counter
from datetime import datetime

import pytest

from eacore.backends.sql import load_file
from eacore.records import Ref, TextRefs
from eaedit import InvalidOperationError
from eaedit.defaults import DEFAULTS, EA_KINDS, TYPE_COLUMNS, apply_fields, defaults_for, kind_for, new_guid, timestamp

#: Verified kinds whose type value nafv4.qea does not contain: name -> why they are verified anyway.
VERIFIED_ELSEWHERE: dict[str, str] = {}

#: Varies per project (code generation language), so EA-made rows are no evidence against a default.
PROJECT_SETTINGS = {"attr_gentype"}


@pytest.fixture(scope="module")
def nafv4():
    from pathlib import Path

    return load_file(Path(__file__).resolve().parents[1] / "data" / "nafv4.qea")


def _rows(rs, table, type_value):
    column = TYPE_COLUMNS.get(table)
    rows = [r.values for r in rs.records(table)]
    if type_value != "*":
        rows = [r for r in rows if r.get(column) == type_value]
    return rows


def test_verified_defaults_match_ea_rows(nafv4):
    for (table, type_value), entry in DEFAULTS.items():
        if not entry.verified:
            continue
        rows = _rows(nafv4, table, type_value)
        assert rows, f"no evidence: no EA-made {table} rows of type {type_value!r}"
        for column, value in entry.values.items():
            if column in PROJECT_SETTINGS:
                continue
            common, _ = Counter(r.get(column) for r in rows).most_common(1)[0]
            assert value == common, f"{table}/{type_value} {column}: default {value!r}, EA mostly {common!r}"


#: Columns an operation sets per row, so a constant among EA's rows is no default.
SET_BY_OPERATION = {
    "attr_object_type",
    "attr_connector_type",
    "attr_name",
    "attr_createddate",
    "attr_modifieddate",
    "attr_author",
    "attr_ea_guid",
    "attr_xrefid",
    "attr_tpos",
    "attr_pos",
    "attr_note",
    "attr_notes",
    "attr_description",
    "attr_type",
    "attr_client",
    "attr_stereotype",
    "attr_property",
    "attr_value",
    # Label text derived from the connector's stereotype ("«abstraction» «Implements»" on both EA Abstractions).
    "attr_btm_mid_label",
}


def test_verified_defaults_complete(nafv4):
    for (table, type_value), entry in DEFAULTS.items():
        rows = _rows(nafv4, table, type_value)
        if not entry.verified or len(rows) < 2:
            continue
        for column in rows[0]:
            values = {r.get(column) for r in rows}
            if column in SET_BY_OPERATION or column in PROJECT_SETTINGS or len(values) != 1 or None in values:
                continue
            if isinstance(next(iter(values)), (Ref, TextRefs)):
                continue
            assert column in entry.values, f"{table}/{type_value} {column}: EA always writes {values}, no default"


def test_verified_kinds_seen_in_model(nafv4):
    for name, kind in EA_KINDS.items():
        if not kind.verified or name in VERIFIED_ELSEWHERE:
            continue
        seen = {r.values.get(kind.type_column) for r in nafv4.records(kind.table)}
        assert kind.type_value in seen, f"{name}: {kind.table} has no {kind.type_value!r} row"


def test_kind_for_known_and_unknown():
    kind, known = kind_for("Composition")
    assert known and (kind.table, kind.type_value, kind.extra) == (
        "t_connector",
        "Aggregation",
        {"attr_subtype": "Strong"},
    )
    kind, known = kind_for("Gizmo")
    assert not known and (kind.table, kind.type_column, kind.type_value) == ("t_object", "attr_object_type", "Gizmo")
    kind, known = kind_for("Trace")
    assert not known and (kind.table, kind.type_column) == ("t_connector", "attr_connector_type")


def test_defaults_for_falls_back():
    assert defaults_for("t_object", "Class") is DEFAULTS[("t_object", "Class")]
    assert defaults_for("t_object", "Gizmo") is DEFAULTS[("t_object", "*")]
    missing = defaults_for("t_nothing", "X")
    assert missing.values == {} and not missing.verified


def test_new_guid_format():
    guid = new_guid()
    assert re.fullmatch(r"\{[0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12}\}", guid)
    assert new_guid() != guid


def test_timestamp_format():
    assert timestamp(datetime(2026, 1, 2, 3, 4, 5, 678)) == "2026-01-02 03:04:05"


def test_apply_fields_maps_and_converts():
    values = apply_fields("t_object", {"attr_name": "A"}, {"name": "B", "abstract": True, "keywords": "k"})
    assert values == {"attr_name": "B", "attr_abstract": "1", "attr_pdata5": "k"}
    assert apply_fields("t_attribute", {}, {"static": False, "lower": "0"}) == {
        "attr_isstatic": 0,
        "attr_lowerbound": "0",
    }


def test_apply_fields_rejects_unknown_and_stereotype():
    with pytest.raises(InvalidOperationError, match="allowed: .*name"):
        apply_fields("t_object", {}, {"colour": "red"})
    with pytest.raises(InvalidOperationError, match="add_stereotype"):
        apply_fields("t_object", {}, {"stereotype": "X"})


def test_verified_unset_values_seen_in_model(nafv4):
    from eaedit.defaults import UNSET

    for (table, column, type_value), (value, verified) in UNSET.items():
        if not verified:
            continue
        seen = [r[column] for r in _rows(nafv4, table, type_value)]
        assert value in seen, f"{table}.{column} ({type_value}): EA-made rows never hold {value!r}"
