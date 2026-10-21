import re

from eaedit.mcp import diagram_text, explore
from eaedit.mcp.workspace import Config, Workspace

L7 = "{0BA44FD3-F22C-4f9a-AC35-3BDB736B3C80}"
P6 = "{EB2441A2-EE65-42fe-A5FD-350317D3216F}"
MSG = "Model::core::message"


def _session(path, tmp_path):
    return Workspace(Config(path, out_dir=tmp_path / "out")).snapshot()


def _kinds(text):
    return [line.split(" ", 1)[0] for line in text.splitlines()]


def test_l7_lists_objects_links_and_note(nafv4_path, tmp_path):
    text = diagram_text.diagram_text(_session(nafv4_path, tmp_path), L7)
    lines = text.splitlines()
    assert re.match(r"diagram Model::.*L7 \{[0-9A-Fa-f-]+\}  type=.+  page=\d+x\d+$", lines[0])
    assert _kinds(text).count("obj") == 3
    assert _kinds(text).count("link") == 4
    assert _kinds(text).count("note") == 1
    obj = next(x for x in lines if x.startswith(f"obj {MSG}::Message "))
    assert re.search(r"\{[0-9A-Fa-f-]+\} duid=[0-9A-F]{8} rect=\d+,\d+,\d+,\d+ z=\d+$", obj)
    note = next(x for x in lines if x.startswith("note "))
    assert re.match(r'note \{[0-9A-Fa-f-]+\} duid=\S+ rect=\d+,\d+,\d+,\d+ z=\d+ ".*"$', note)
    link = next(x for x in lines if x.startswith("link NoteLink"))
    assert re.search(r"-> \{[0-9A-Fa-f-]+\} \{", link)
    link = next(x for x in lines if x.startswith("link Generalization"))
    assert " -> " in link and re.search(r"\{[0-9A-Fa-f-]+\}( hidden)?$", link)


def test_place_shows_the_new_object_with_its_rect(nafv4_path, tmp_path):
    ws = Workspace(Config(nafv4_path, out_dir=tmp_path / "out"))
    ws.open_session()
    ws.run("create_element", {"package": MSG, "name": "Fresh"})
    ws.run("place", {"diagram": L7, "element": f"{MSG}::Fresh", "rect": [500, 40, 600, 100]})
    text = diagram_text.diagram_text(ws.session, L7)
    assert re.search(rf"^obj {MSG}::Fresh .* rect=500,40,600,100 z=\d+$", text, re.M)
    assert f"obj {MSG}::Fresh" not in diagram_text.diagram_text(ws.snapshot(), L7)


def test_p6_messages_in_seqno_order(nafv4_path, tmp_path):
    text = diagram_text.diagram_text(_session(nafv4_path, tmp_path), P6)
    msgs = [x for x in text.splitlines() if x.startswith("msg ")]
    assert msgs
    numbers = [int(x.split()[1]) for x in msgs]
    assert numbers == sorted(numbers)
    assert all(re.search(r"\{[0-9A-Fa-f-]+\} offset=-?\d*$", x) for x in msgs)
    assert any(x.startswith("readonly duid=") for x in text.splitlines())


def test_large_diagram_pages(nafv4_path, tmp_path):
    ws = Workspace(Config(nafv4_path, out_dir=tmp_path / "out"))
    ws.open_session()
    ws.run("create_diagram", {"owner": MSG, "name": "Big"})
    for i in range(200):
        ws.run("create_element", {"package": MSG, "name": f"E{i:03}"})
        ws.run("place", {"diagram": f"{MSG}::Big", "element": f"{MSG}::E{i:03}"})
    first = diagram_text.diagram_text(ws.session, f"{MSG}::Big").splitlines()
    assert first[0].startswith("diagram") and len(first) == 41
    assert re.fullmatch(r"… \d+ more \(page=2\)", first[-1])
    last = diagram_text.diagram_text(ws.session, f"{MSG}::Big", page=6).splitlines()
    assert not last[-1].startswith("…")


def test_describe_of_a_diagram_is_its_text(nafv4_path, tmp_path):
    session = _session(nafv4_path, tmp_path)
    assert explore.describe(session, L7) == diagram_text.diagram_text(session, L7)
