import re
import sqlite3
from datetime import datetime

import pytest

from eacore.backends.sql import ConcurrentModificationError, SqlBackend
from eacore.diff import diff
from eacore.records import Record, Ref
from eaedit import CommitRefusedError, InvalidOperationError, ScopeError, Session
from eaedit.ops import OPERATIONS, operation

MESSAGE = "{3522A830-8853-4c52-9908-40871435BB3B}"  # Model::core::message
DATA = "{B68C47BB-5B85-42e7-8FD5-131C7126DCFB}"  # Model::core::data, sibling of message
IN_MESSAGE = "{308FD88F-3514-4a20-942B-5CF2F35B042F}"  # Message class
IN_DATA = "{360F4F18-9BCE-4efe-A337-2958FE3DCA3C}"  # Measurement class
NEW = "{11111111-0000-0000-0000-000000000001}"
FIXED = datetime(2026, 1, 2, 3, 4, 5)


@pytest.fixture(autouse=True)
def test_ops():
    @operation("_test_rename")
    def rename(session, target, name):
        rec = session.working.resolve(session.find(target, kinds=("element",)))
        session.put(Record(rec.table, rec.key, {**rec.values, "attr_name": name}, rec.rid))
        return rec.key

    @operation("_test_fail")
    def fail(session, target):
        rec = session.working.resolve(session.find(target, kinds=("element",)))
        session.put(Record(rec.table, rec.key, {**rec.values, "attr_name": "Broken"}, rec.rid))
        raise InvalidOperationError("nope")

    @operation("_test_dangling")
    def dangling(session, target):
        rec = session.working.resolve(session.find(target, kinds=("element",)))
        missing = Ref("t_package", "{00000000-0000-0000-0000-000000000000}")
        session.put(Record("t_object", NEW, {**rec.values, "attr_ea_guid": NEW, "attr_package_id": missing}))
        session.created(NEW)
        return NEW

    yield
    for name in ("_test_rename", "_test_fail", "_test_dangling"):
        OPERATIONS.pop(name, None)


@pytest.fixture
def path(nafv4_path, qea_copy):
    return qea_copy(nafv4_path)


def _open(path, **kwargs):
    return Session.open(path, clock=lambda: FIXED, **kwargs)


def test_open_and_noop_preview(path):
    session = _open(path)
    preview = session.preview()
    assert preview.changes.is_empty()
    assert preview.new_issues == []
    assert preview.warnings == [] and preview.outside_focus == []


def test_run_changes_working_not_original(path):
    session = _open(path)
    result = session.run("_test_rename", target=IN_MESSAGE, name="Renamed")
    assert result.guid == IN_MESSAGE and result.warnings == []
    assert session.working.get("t_object", IN_MESSAGE).values["attr_name"] == "Renamed"
    assert session.original.get("t_object", IN_MESSAGE).values["attr_name"] == "Message"
    [logged] = session.log
    assert (logged.name, logged.args, logged.at) == ("_test_rename", {"target": IN_MESSAGE, "name": "Renamed"}, FIXED)
    preview = session.preview()
    assert len(preview.changes.updates) == 1
    assert preview.touched == {"Model::core::message": 1}
    assert "Renamed" in preview.report


def test_getattr_dispatches_to_operations(path):
    session = _open(path)
    assert session._test_rename(target=IN_MESSAGE, name="X").guid == IN_MESSAGE
    with pytest.raises(AttributeError):
        session.no_such_thing


def test_undo_restores_exactly(path):
    session = _open(path)
    session.run("_test_rename", target=IN_MESSAGE, name="Renamed")
    session.run("_test_rename", target=IN_MESSAGE, name="Again")
    session.run("_test_dangling", target=IN_MESSAGE)
    assert "guid" not in session.log[-1].args  # the op takes no guid, so none is logged
    assert session.undo().name == "_test_dangling"
    assert session.working.get("t_object", IN_MESSAGE).values["attr_name"] == "Again"
    session.undo()
    session.undo()
    assert session.working.same_records(session.original)
    assert session.log == []
    with pytest.raises(InvalidOperationError):
        session.undo()


def test_failed_operation_rolls_back(path):
    session = _open(path)
    with pytest.raises(InvalidOperationError, match="nope"):
        session.run("_test_fail", target=IN_MESSAGE)
    assert session.working.same_records(session.original)
    assert session.log == []


def test_commit_roundtrip(path):
    session = _open(path)
    session.run("_test_rename", target=IN_MESSAGE, name="Renamed")
    committed = session.commit()
    assert len(committed.updates) == 1
    reloaded = SqlBackend.for_file(path).load()
    assert diff(reloaded, session.working).is_empty()
    assert session.changes().is_empty()
    assert session.log == []


def test_commit_after_external_change_refuses(path):
    session = _open(path)
    session.run("_test_rename", target=IN_MESSAGE, name="Renamed")
    with sqlite3.connect(path) as conn:
        conn.execute("update t_object set Name = 'External' where ea_guid = ?", (IN_DATA,))
    with pytest.raises(ConcurrentModificationError):
        session.commit()
    with sqlite3.connect(path) as conn:
        assert conn.execute("select Name from t_object where ea_guid = ?", (IN_DATA,)).fetchone() == ("External",)
        assert conn.execute("select Name from t_object where ea_guid = ?", (IN_MESSAGE,)).fetchone() == ("Message",)


def test_scope_violation_raises_and_rolls_back(path):
    session = _open(path, focus=["Model::core::message"], policy="package")
    session.run("_test_rename", target=IN_MESSAGE, name="Inside")
    with pytest.raises(ScopeError, match="Model::core::data"):
        session.run("_test_rename", target=IN_DATA, name="Outside")
    assert session.working.get("t_object", IN_DATA).values["attr_name"] == "Measurement"
    assert len(session.log) == 1


def test_advisory_scope_warns(path):
    session = _open(path, focus=[MESSAGE], policy="advisory")
    result = session.run("_test_rename", target=IN_DATA, name="Outside")
    # An update is judged on both sides, so it can warn twice.
    assert result.warnings and {w.code for w in result.warnings} == {"scope"}
    assert session.working.get("t_object", IN_DATA).values["attr_name"] == "Outside"
    preview = session.preview()
    assert preview.warnings == result.warnings
    assert preview.outside_focus == ["Model::core::data"]
    session.undo()
    assert session.warnings == []


def test_commit_refused_on_new_integrity_error(path):
    session = _open(path)
    before = path.read_bytes()
    session.run("_test_dangling", target=IN_MESSAGE)
    assert any(i.rule == "dangling-reference" for i in session.preview().new_issues)
    with pytest.raises(CommitRefusedError) as info:
        session.commit()
    assert info.value.issues and all(i.severity == "error" for i in info.value.issues)
    assert path.read_bytes() == before


def test_unknown_operation(path):
    session = _open(path)
    with pytest.raises(InvalidOperationError):
        session.run("no_such_operation")


def test_open_validates_policy_and_focus(path):
    with pytest.raises(InvalidOperationError):
        _open(path, policy="sometimes")
    assert _open(path, focus=[DATA]).scope.focus == (Ref("t_package", DATA),)


def test_new_guid_logs_every_minted_guid_and_uses_the_queue(path):
    @operation("_test_mint")
    def mint(session):
        return [session.new_guid(), session.new_guid()][0]

    try:
        session = _open(path)
        session.run("_test_mint")
        [logged] = session.log
        assert len(logged.created) == 2 and len(set(logged.created)) == 2
        assert "guid" not in logged.args  # no guid parameter: replay reproduces it from the queue

        @operation("_test_mint_guid")
        def mint_guid(session, guid=None):
            return guid or [session.new_guid(), session.new_guid()][0]

        session.run("_test_mint_guid")
        assert session.log[-1].args["guid"] == session.log[-1].created[0]

        g1, g2 = "{11111111-0000-0000-0000-00000000000A}", "{11111111-0000-0000-0000-00000000000B}"
        session.queue_guids([g1, g2, "{11111111-0000-0000-0000-00000000000C}"])
        assert session.run("_test_mint").guid == g1
        assert session.log[-1].created == [g1, g2]
        assert session._guid_queue == []  # cleared after each run, leftovers included
    finally:
        OPERATIONS.pop("_test_mint", None)
        OPERATIONS.pop("_test_mint_guid", None)


def test_new_duid_shape_and_replay(path):
    @operation("_test_duid")
    def mint(session):
        return session.new_duid()

    try:
        session = _open(path)
        assert re.fullmatch(r"[0-9A-F]{8}", session.run("_test_duid").guid)
        session.queue_guids(["{12345678-AAAA-BBBB-CCCC-DDDDEEEEFFFF}"])
        assert session.run("_test_duid").guid == "12345678"
        assert session.log[-1].created == ["{12345678-AAAA-BBBB-CCCC-DDDDEEEEFFFF}"]
    finally:
        OPERATIONS.pop("_test_duid", None)


def test_failed_dispatch_clears_the_guid_queue(path):
    session = _open(path)
    session.queue_guids(["{11111111-0000-0000-0000-00000000000D}"])
    with pytest.raises(InvalidOperationError):
        session.run("no_such_operation")
    assert session._guid_queue == []


def test_commit_clears_warnings(path):
    session = _open(path, focus=[MESSAGE], policy="advisory")
    session.run("_test_rename", target=IN_DATA, name="Outside")
    assert session.warnings
    session.commit()
    assert session.warnings == [] and session.preview().warnings == []


def test_operation_wrappers_accept_positional_arguments(path):
    session = _open(path)
    result = session._test_rename(IN_MESSAGE, "Positional")
    assert result.guid == IN_MESSAGE
    assert session.working.get("t_object", IN_MESSAGE).values["attr_name"] == "Positional"
    # Logged by parameter name, so the change file replays as if called with keywords.
    assert session.log[-1].args == {"target": IN_MESSAGE, "name": "Positional"}
    session._test_rename(IN_MESSAGE, name="Mixed")
    assert session.log[-1].args == {"target": IN_MESSAGE, "name": "Mixed"}
    with pytest.raises(InvalidOperationError, match="_test_rename"):
        session._test_rename(IN_MESSAGE, "a", "too many")


def test_timezone_writes_that_zones_local_time(path):
    # EA stores naive local time of the machine running it; a UTC container must still match a Warsaw EA.
    from zoneinfo import ZoneInfo

    session = Session.open(path, timezone="Europe/Warsaw")
    expected = datetime.now(ZoneInfo("Europe/Warsaw")).replace(tzinfo=None)
    written = datetime.strptime(
        session.working.get("t_package", session.create_package("Model", "Clocked").guid).values["attr_createddate"],
        "%Y-%m-%d %H:%M:%S",
    )
    assert abs((written - expected).total_seconds()) < 60


def test_timezone_rejects_unknown_and_clock_combination(path):
    with pytest.raises(InvalidOperationError, match="unknown timezone"):
        Session.open(path, timezone="Mars/Olympus")
    with pytest.raises(InvalidOperationError, match="either clock or timezone"):
        Session.open(path, timezone="Europe/Warsaw", clock=lambda: FIXED)
