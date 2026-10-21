from eacore.records import RecordSet
from eaedit.mcp.words import agent_words

G = "{00000000-0000-0000-0000-000000000001}"
D = "{00000000-0000-0000-0000-000000000002}"


def test_unresolved_keys_keep_their_guids():
    rs = RecordSet()
    assert agent_words(f"attr_object_id -> missing t_object:{G}", rs) == f"object id -> missing element {G}"
    assert (
        agent_words(f"delete t_diagramobjects (t_diagram:{D}, 219F18EC)", rs)
        == f"delete object 219F18EC on diagram {D}"
    )
    assert (
        agent_words(f"t_diagramlinks (t_diagram:{D}, t_connector:{G})", rs) == f"link of connector {G} on diagram {D}"
    )
    assert (
        agent_words("t_secpolicies: sequence 3 < max ID 4; attr_destrole", rs)
        == "model data: sequence 3 < max ID 4; target_role"
    )


def test_plain_text_is_unchanged():
    assert agent_words("first_name of Model::Thing", RecordSet()) == "first_name of Model::Thing"


def test_quoted_input_and_qualified_names_are_kept():
    rs = RecordSet()
    text = "nothing matches 't_object'; note \"see attr_name\" on Model::attr_x::t_user (t_object)"
    assert (
        agent_words(text, rs) == "nothing matches 't_object'; note \"see attr_name\" on Model::attr_x::t_user (element)"
    )
