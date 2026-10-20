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


#: Style columns holding per-diagram parts (MDGDgm is set by the operation; EA regenerates SaveTag on every save).
STYLE_COLUMNS = {"attr_styleex"}


def _plain_style(text):
    return re.sub(r"(MDGDgm|SaveTag)=[^;]*;", "", text)


def test_verified_defaults_match_ea_rows(nafv4):
    for (table, type_value), entry in DEFAULTS.items():
        if not entry.verified:
            continue
        rows = _rows(nafv4, table, type_value)
        assert rows, f"no evidence: no EA-made {table} rows of type {type_value!r}"
        for column, value in entry.values.items():
            if column in PROJECT_SETTINGS:
                continue
            seen = (_plain_style(r.get(column)) if column in STYLE_COLUMNS else r.get(column) for r in rows)
            common, _ = Counter(seen).most_common(1)[0]
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
    "attr_diagram_type",
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


def test_diagram_defaults_match_the_hand_made_rows(nafv4):
    # Column by column against the hand-made rows (the Custom page size is the majority value, cx 776 x cy 1126).
    for type_value in ("Custom", "Sequence"):
        rows = _rows(nafv4, "t_diagram", type_value)
        entry = defaults_for("t_diagram", type_value)
        assert entry.verified and entry.values["attr_styleex"].count("MDGDgm") == 0
        for column, value in entry.values.items():
            seen = {_plain_style(r[column]) if column in STYLE_COLUMNS else r[column] for r in rows}
            assert value in seen, f"t_diagram/{type_value} {column}: {value!r} not in EA rows {seen}"
    assert defaults_for("t_diagram", "Custom").values["attr_cx"] == 776
    assert (
        defaults_for("t_diagram", "Class") is DEFAULTS[("t_diagram", "*")] and not DEFAULTS[("t_diagram", "*")].verified
    )


def test_diagram_object_and_link_defaults_and_styles():
    from eaedit.defaults import OBJECT_STYLES, link_geometry, link_style

    assert defaults_for("t_diagramobjects", "*").verified and defaults_for("t_diagramobjects", "*").values == {}
    assert defaults_for("t_diagramlinks", "*").values == {"attr_hidden": 0}
    assert OBJECT_STYLES["Note"] == "" and OBJECT_STYLES["Part"] == OBJECT_STYLES["*"] == "HideIcon=0;"
    assert OBJECT_STYLES["Lifeline"].startswith("NSL=0;BCol=-1;") and OBJECT_STYLES["Lifeline"].endswith("HideIcon=0;")
    assert link_style("AAAA1111", "BBBB2222") == "Mode=3;EOID=BBBB2222;SOID=AAAA1111;Color=-1;LWidth=0;"
    assert link_geometry(2) == "SX=0;SY=0;EX=0;EY=0;EDGE=2;$LLB=;LLT=;LMT=;LMB=;LRT=;LRB=;IRHS=;ILHS=;"


def test_new_row_keys_diagram_object_and_link(nafv4_path, qea_copy):
    from eaedit import Session
    from eaedit.defaults import new_row
    from eaedit.ops import OPERATIONS

    session = Session.open(qea_copy(nafv4_path))
    diagram = Ref("t_diagram", "{11111111-0000-0000-0000-000000000001}")
    element = Ref("t_object", "{22222222-0000-0000-0000-000000000002}")
    made = {}

    def op(s):
        made["obj"] = new_row(
            s,
            "t_diagramobjects",
            {"attr_diagram_id": diagram, "attr_object_id": element, "attr_objectstyle": "DUID=0A1B2C3D;HideIcon=0;"},
        )
        made["link"] = new_row(s, "t_diagramlinks", {"attr_diagramid": diagram, "attr_connectorid": 7})

    OPERATIONS["_test_new_row"] = op
    try:
        session.run("_test_new_row")
    finally:
        OPERATIONS.pop("_test_new_row")
    assert made["obj"].key == (diagram, "0A1B2C3D")
    assert made["obj"].values["attr_objectstyle"] == "DUID=0A1B2C3D;HideIcon=0;"
    assert made["link"].values["attr_hidden"] == 0 and made["link"].values["attr_geometry"] is None


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
