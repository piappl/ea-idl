"""Every scope policy against inside, outside and crossing edits, with the focus on Model::core::message."""

import pytest

from eaedit import NotFoundError, ScopeError, Session

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


# The focus root itself: renaming, moving or deleting it changes its parent's contents, which is outside the focus.
ROOT_ACTIONS = {
    "rename focus root": ("update_package", {"pkg": IN, "name": "Renamed"}),
    "move focus root": ("move_package", {"pkg": IN, "new_parent": OUT}),
    "delete focus root": ("delete_package", {"pkg": IN, "recursive": True}),
}
ROOT_EXPECTED = {"package": "scope", "connected": "scope", "advisory": "warn", "off": "ok"}
ROOT_CELLS = [(action, policy) for action in ROOT_ACTIONS for policy in POLICIES]


@pytest.mark.parametrize("action,policy", ROOT_CELLS, ids=[f"{a}-{p}" for a, p in ROOT_CELLS])
def test_focus_root_itself(nafv4_path, qea_copy, action, policy):
    session = Session.open(qea_copy(nafv4_path), focus=[MESSAGE], policy=policy, author="tester")
    name, args = ROOT_ACTIONS[action]
    expected = ROOT_EXPECTED[policy]
    if expected == "scope":
        with pytest.raises(ScopeError, match="outside the focus"):
            session.run(name, **args)
        assert session.changes().is_empty()
        return
    result = session.run(name, **args)
    assert bool([w for w in result.warnings if w.code == "scope"]) == (expected == "warn")


def test_focus_root_rows_owned_by_parent_only_for_the_root(nafv4_path, qea_copy):
    # A sub-package of the focus is renamed and deleted freely.
    session = Session.open(qea_copy(nafv4_path), focus=[MESSAGE], policy="package", author="tester")
    session.create_package(parent=IN, name="Sub")
    session.update_package(pkg=f"{IN}::Sub", name="Sub2")
    session.delete_package(pkg=f"{IN}::Sub2")
    assert session.changes().is_empty()


@pytest.mark.parametrize("policy", ["package", "connected"])
def test_deletes_inside_a_package_created_in_the_session(nafv4_path, qea_copy, policy):
    path = qea_copy(nafv4_path)
    session = Session.open(path, focus=["Model::core"], policy=policy, author="tester")
    session.create_package(parent="Model::core", name="N")
    element = session.create_element(package="Model::core::N", name="E").guid
    attribute = session.add_attribute(el=element, name="a").guid
    session.delete_attribute(attr=attribute)
    session.delete_element(el=element)
    # An existing element moved into the new package, then its attribute deleted (judged at commit too).
    moved = session.create_element(package="Model::core", name="M").guid
    other = session.add_attribute(el=moved, name="b").guid
    session.commit()
    session.create_package(parent="Model::core", name="N2")
    session.move_element(el=moved, package="Model::core::N2")
    session.delete_attribute(attr=other)
    session.commit()
    session.create_element(package="Model::core::N2", name="E2")
    session.delete_package(pkg="Model::core::N", recursive=True)
    session.delete_package(pkg="Model::core::N2", recursive=True)
    session.commit()
    reopened = Session.open(path, infer=False)
    for name in ("Model::core::N", "Model::core::N2", "Model::core::M"):
        with pytest.raises(NotFoundError):
            reopened.find(name)
