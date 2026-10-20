from datetime import datetime

import pytest

from eacore.integrity import check
from eacore.records import Ref
from eaedit import InvalidOperationError, Session

FIXED = datetime(2026, 1, 2, 3, 4, 5)
L7 = "{0BA44FD3-F22C-4f9a-AC35-3BDB736B3C80}"
MESSAGE = "{308FD88F-3514-4a20-942B-5CF2F35B042F}"  # Model::core::message::Message, on L7
MSG1 = "{DFC8864D-8C70-4576-9254-D5FE6F86143E}"  # a message on p6


def _issues(rs):
    return {(i.severity, i.rule, i.ref, i.message) for i in check(rs)}


def _open(path):
    return Session.open(path, policy="off", clock=lambda: FIXED, author="tester")


def _rec(session, table, guid):
    return session.working.resolve(session.find(guid, kinds=("element", "connector", "diagram")))


def _shown(session, element):
    ref = Ref("t_object", element)
    return [r for r in session.working.records("t_diagramobjects") if r.values["attr_object_id"] == ref]


def test_add_and_link_note(nafv4_path, qea_copy):
    session = _open(qea_copy(nafv4_path))
    baseline = _issues(session.working)
    note = session.add_note(L7, "About messages").guid
    row = _rec(session, "t_object", note)
    assert row.values["attr_object_type"] == "Note" and row.values["attr_note"] == "About messages"
    assert len(_shown(session, row.key)) == 1
    link = session.link_note(note, MESSAGE).guid
    conn = _rec(session, "t_connector", link)
    assert conn.values["attr_connector_type"] == "NoteLink"
    # Start = the annotated element, End = the Note, as on all hand-made NoteLinks.
    assert conn.values["attr_start_object_id"] == Ref("t_object", _rec(session, "t_object", MESSAGE).key)
    assert conn.values["attr_end_object_id"] == Ref("t_object", row.key)
    rows = [
        r
        for r in session.working.records("t_diagramlinks")
        if r.values["attr_connectorid"] == Ref("t_connector", conn.key)
    ]
    assert len(rows) == 1
    assert _issues(session.working) == baseline


def test_note_text_non_ascii(nafv4_path, qea_copy):
    session = _open(qea_copy(nafv4_path))
    note = session.add_note(L7, "x").guid
    session.set_note_text(note, "Zażółć gęślą jaźń")
    assert _rec(session, "t_object", note).values["attr_note"] == "Zażółć gęślą jaźń"


def test_set_note_text_rejects_non_note(nafv4_path, qea_copy):
    session = _open(qea_copy(nafv4_path))
    with pytest.raises(InvalidOperationError):
        session.set_note_text(MESSAGE, "x")


def test_delete_element_keeps_notes(nafv4_path, qea_copy):
    session = _open(qea_copy(nafv4_path))
    note = session.add_note(L7, "keep me").guid
    link = session.link_note(note, MESSAGE).guid
    session.delete_element(MESSAGE)
    assert _rec(session, "t_object", note).values["attr_note"] == "keep me"
    assert not [r for r in session.working.records("t_connector") if r.values.get("attr_ea_guid") == link]
    note_key = _rec(session, "t_object", note).key
    assert len(_shown(session, note_key)) == 1
    assert not [
        r
        for r in session.working.records("t_diagramlinks")
        if r.values["attr_connectorid"] is not None
        and session.working.get("t_connector", r.values["attr_connectorid"].key) is None
    ]


def test_note_on_message_writes_pdata4(nafv4_path, qea_copy):
    session = _open(qea_copy(nafv4_path))
    p6 = "{EB2441A2-EE65-42fe-A5FD-350317D3216F}"
    note = session.add_note(p6, "on message").guid
    before = len(list(session.working.records("t_connector")))
    session.link_note(note, MSG1)
    assert len(list(session.working.records("t_connector"))) == before
    value = _rec(session, "t_object", note).values["attr_pdata4"]
    assert value.template == "idref1={0};" and value.refs[0] == Ref(
        "t_connector", _rec(session, "t_connector", MSG1).key
    )
