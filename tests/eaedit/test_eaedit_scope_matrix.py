"""Every scope policy against inside, outside and crossing edits, with the focus on Model::core::message."""

import pytest

from eaedit import ScopeError, Session

MESSAGE = "{3522A830-8853-4c52-9908-40871435BB3B}"  # Model::core::message (the focus)
IN = "Model::core::message"
OUT = "Model::core::data"  # sibling of the focus

# Each action: (operation, arguments). Fixture facts from nafv4.qea that decide the delete rows:
# - MessageTypeEnum is referenced from nothing outside the focus;
# - AbstractMessageHeader has a connector to Model::core::common::types (one end outside);
# - Message is also shown on a Model::L7 diagram, so deleting it clears rows owned outside the focus;
# - MeasurementTypeEnum lives in OUT.
ACTIONS = {
    "create inside": ("create_element", {"package": IN, "name": "New"}),
    "create outside": ("create_element", {"package": OUT, "name": "New"}),
    "connect inside": ("connect", {"source": f"{IN}::MessageHeader", "target": f"{IN}::MessageTypeEnum"}),
    "connect crossing": ("connect", {"source": f"{IN}::Message", "target": f"{OUT}::Measurement"}),
    "connect outside": ("connect", {"source": f"{OUT}::Measurement", "target": f"{OUT}::MeasurementTypeEnum"}),
    "move out": ("move_element", {"el": f"{IN}::MessageTypeEnum", "package": OUT}),
    "move in": ("move_element", {"el": f"{OUT}::MeasurementTypeEnum", "package": IN}),
    "delete inside": ("delete_element", {"el": f"{IN}::MessageTypeEnum"}),
    "delete inside, crossing connector": ("delete_element", {"el": f"{IN}::AbstractMessageHeader"}),
    "delete inside, shown outside": ("delete_element", {"el": f"{IN}::Message"}),
    "delete outside": ("delete_element", {"el": f"{OUT}::MeasurementTypeEnum"}),
}

POLICIES = ("package", "connected", "advisory", "off")

# advisory warns wherever package refuses; only connected allows a connector with one end outside.

# fmt: off
EXPECTED = {
    #                                       package  connected  advisory  off
    "create inside":                      ("ok",    "ok",      "ok",     "ok"),
    "create outside":                     ("scope", "scope",   "warn",   "ok"),
    "connect inside":                     ("ok",    "ok",      "ok",     "ok"),
    "connect crossing":                   ("scope", "ok",      "warn",   "ok"),
    "connect outside":                    ("scope", "scope",   "warn",   "ok"),
    "move out":                           ("scope", "scope",   "warn",   "ok"),
    "move in":                            ("scope", "scope",   "warn",   "ok"),
    "delete inside":                      ("ok",    "ok",      "ok",     "ok"),
    "delete inside, crossing connector":  ("scope", "ok",      "warn",   "ok"),
    "delete inside, shown outside":       ("scope", "scope",   "warn",   "ok"),
    "delete outside":                     ("scope", "scope",   "warn",   "ok"),
}
# fmt: on

CELLS = [(action, policy, EXPECTED[action][i]) for action in ACTIONS for i, policy in enumerate(POLICIES)]


@pytest.mark.parametrize("action,policy,expected", CELLS, ids=[f"{a}-{p}" for a, p, _ in CELLS])
def test_scope_matrix(nafv4_path, qea_copy, action, policy, expected):
    session = Session.open(qea_copy(nafv4_path), focus=[MESSAGE], policy=policy, author="tester")
    name, args = ACTIONS[action]
    if expected == "scope":
        with pytest.raises(ScopeError, match="outside the focus"):
            session.run(name, **args)
        assert session.changes().is_empty() and session.log == []  # rolled back
        return
    result = session.run(name, **args)
    scope_warnings = [w for w in result.warnings if w.code == "scope"]
    assert bool(scope_warnings) == (expected == "warn")
    assert not session.changes().is_empty()
