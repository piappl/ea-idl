from datetime import datetime

import pytest

from eaedit import InvalidOperationError, Session

FIXED = datetime(2026, 1, 2, 3, 4, 5)
P6 = "{EB2441A2-EE65-42fe-A5FD-350317D3216F}"
L7 = "{0BA44FD3-F22C-4f9a-AC35-3BDB736B3C80}"
MSG1 = "{DFC8864D-8C70-4576-9254-D5FE6F86143E}"  # Message1 on p6, SeqNo 1
MSG2 = "{CC7B66A2-F6F1-4738-93D3-5AD79EFF2C39}"
MSG3 = "{D0DF914E-4850-404c-98F5-D518EDDF0EFF}"
NOTELINK = "{1A8E6850-BEC6-4e48-A4F6-4FBF3309A4B4}"  # the p6 NoteLink
ASSET1 = "{787820BD-43DC-424c-81C3-BA7A076C417C}"  # the two lifelines of p6
ASSET2 = "{45EF1F2C-6C51-49c0-8EFE-2E4CED2BC1CF}"
MESSAGE = "{B2CA2761-3F36-4cf0-BACA-64B20F260AA0}"  # on L7, not on p6


def _open(path):
    return Session.open(path, policy="off", clock=lambda: FIXED, author="tester")


def _conn(session, guid):
    return session.working.resolve(session.find(guid, kinds=("connector",)))


def test_show_and_order_messages(nafv4_path, qea_copy):
    session = _open(qea_copy(nafv4_path))
    new = session.connect(ASSET1, ASSET2, type="Message", name="New").guid
    before = {r.key: dict(r.values) for r in session.working.records("t_connector")}
    session.show_message(P6, new)
    row = _conn(session, new)
    assert session.working.resolve(row.values["attr_diagramid"]).values["attr_ea_guid"] == P6
    assert row.values["attr_seqno"] == 4
    changed = {
        c
        for r in session.working.records("t_connector")
        for c in r.values
        if r.key in before and r.values[c] != before[r.key][c]
    }
    assert changed <= {"attr_diagramid", "attr_seqno", "attr_pdata5"}
    session.set_message_order(P6, [new, MSG3, MSG2, MSG1])
    assert [_conn(session, g).values["attr_seqno"] for g in (new, MSG3, MSG2, MSG1)] == [1, 2, 3, 4]
    assert not [r for r in session.working.records("t_diagramlinks") if r.values["attr_connectorid"].key == row.key]


def test_offset_keeps_other_pdata5_keys(nafv4_path, qea_copy):
    session = _open(qea_copy(nafv4_path))
    before = _conn(session, MSG1).values["attr_pdata5"]
    session.show_message(P6, MSG1, offset=-100)
    after = _conn(session, MSG1).values["attr_pdata5"]
    assert after == before.replace("SY=-39", "SY=-100")


def test_show_message_rejects_non_lifelines(nafv4_path, qea_copy):
    session = _open(qea_copy(nafv4_path))
    with pytest.raises(InvalidOperationError):
        session.show_message(L7, MSG1)  # not a Sequence diagram
    with pytest.raises(InvalidOperationError):
        session.show_message(P6, NOTELINK)  # not a message
    other = session.connect(MESSAGE, ASSET2, type="Message").guid
    with pytest.raises(InvalidOperationError):
        session.show_message(P6, other)  # one end not on the diagram
