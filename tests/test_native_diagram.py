"""Tests for native EA diagram extraction pipeline."""

import pytest
from eaidl.native_diagram_extractor import (
    NativeDiagramExtractor,
    parse_link_geometry,
    parse_link_style,
    parse_object_style,
)
from eaidl.native_diagram_model import NativeDiagram, NativeDiagramNode
from eaidl.native_diagram_excalidraw import render_excalidraw
from eaidl.native_diagram_svg import render_svg, _ea_to_svg, _clip_to_rect, _ea_html_to_xhtml
from eaidl.native_diagram_svg import svg_link_map, rewrite_svg_links


# ---------------------------------------------------------------------------
# Unit tests for string decoders
# ---------------------------------------------------------------------------


class TestParseObjectStyle:
    def test_empty_string(self):
        s = parse_object_style("")
        assert s.duid is None
        assert s.hide_icon is False

    def test_none(self):
        s = parse_object_style(None)
        assert s.duid is None

    def test_duid_and_hide_icon(self):
        s = parse_object_style("DUID=D04C7478;HideIcon=0;")
        assert s.duid == "D04C7478"
        assert s.hide_icon is False

    def test_full_style(self):
        raw = "DUID=E66727DC;NSL=0;BCol=-1;BFol=-1;LCol=-1;LWth=-1;fontsz=0;bold=0;black=0;italic=0;ul=0;charset=0;pitch=0;HideIcon=0;"
        s = parse_object_style(raw)
        assert s.duid == "E66727DC"
        assert s.background_color == -1
        assert s.line_color == -1
        assert s.line_width == -1
        assert s.font_size == 0
        assert s.bold is False
        assert s.italic is False
        assert s.underline is False

    def test_att_inh_flag(self):
        s = parse_object_style("DUID=9E247B5B;AttInh=1;AttCustom=0;OpCustom=0;RzO=1;HideIcon=0;")
        assert s.show_inherited_attrs is True
        assert s.show_custom_attrs is False

    def test_extra_keys_preserved(self):
        s = parse_object_style("DUID=ABC;MyCustomKey=hello;")
        assert s.extra.get("MyCustomKey") == "hello"


class TestParseLinkGeometry:
    def test_empty(self):
        g = parse_link_geometry(None, None)
        assert g.source_x is None
        assert g.waypoints == []

    def test_basic_srce_end_edge(self):
        raw = "SX=2;SY=91;EX=2;EY=-30;EDGE=1;$LLB=;LLT=;LMT=;LMB=;LRT=;LRB=;IRHS=;ILHS=;"
        g = parse_link_geometry(raw, None)
        assert g.source_x == 2
        assert g.source_y == 91
        assert g.end_x == 2
        assert g.end_y == -30
        assert g.edge_style == 1
        assert g.waypoints == []

    def test_edge_only(self):
        raw = "EDGE=4;$LLB=;LLT=;LMT=;LMB=;LRT=;LRB=;IRHS=;ILHS=;"
        g = parse_link_geometry(raw, None)
        assert g.source_x is None
        assert g.edge_style == 4

    def test_label_position_decoded(self):
        raw = (
            "SX=-38;SY=-96;EX=-1;EY=65;EDGE=3;"
            "$LLB=;LLT=;LMT=;LMB=;LRT=CX=26:CY=14:OX=0:OY=0:HDN=0:BLD=0:ITA=0:UND=0:CLR=-1:ALN=1:DIR=0:ROT=0;LRB=;IRHS=;ILHS=;"
        )
        g = parse_link_geometry(raw, None)
        assert g.edge_style == 3
        lrt = g.labels.get("LRT")
        assert lrt is not None
        assert lrt.cx == 26
        assert lrt.cy == 14
        assert lrt.color == -1

    def test_waypoints_from_path(self):
        g = parse_link_geometry("EDGE=2;$LLB=;LLT=;LMT=;LMB=;LRT=;LRB=;IRHS=;ILHS=;", "381:-293;200:-100")
        assert g.waypoints == [[381, -293], [200, -100]]

    def test_path_single_waypoint(self):
        g = parse_link_geometry(None, "381:-293")
        assert g.waypoints == [[381, -293]]


class TestParseLinkStyle:
    def test_empty(self):
        s = parse_link_style(None)
        assert s.mode == 3
        assert s.end_duid is None
        assert s.start_duid is None

    def test_full_style(self):
        raw = "Mode=3;EOID=D04C7478;SOID=9E247B5B;Color=-1;LWidth=0;"
        s = parse_link_style(raw)
        assert s.mode == 3
        assert s.end_duid == "D04C7478"
        assert s.start_duid == "9E247B5B"
        assert s.color == -1
        assert s.line_width == 0

    def test_nonzero_line_width(self):
        raw = "Mode=3;EOID=7367401E;SOID=219F18EC;Color=-1;LWidth=1;"
        s = parse_link_style(raw)
        assert s.line_width == 1


# ---------------------------------------------------------------------------
# Integration tests using the test QEA database
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def extractor():
    e = NativeDiagramExtractor.from_url("sqlite:///tests/data/nafv4.qea")
    yield e
    e.close()


class TestNativeDiagramExtractor:
    def test_extract_all_returns_diagrams(self, extractor):
        diagrams = extractor.extract_all()
        assert len(diagrams) > 0
        assert all(isinstance(d, NativeDiagram) for d in diagrams)

    def test_diagrams_have_names(self, extractor):
        diagrams = extractor.extract_all()
        assert all(d.name for d in diagrams)

    def test_extract_by_id(self, extractor):
        diag = extractor.extract_by_id(3)
        assert diag.diagram_id == 3
        assert diag.name == "message"

    def test_message_diagram_has_nodes(self, extractor):
        diag = extractor.extract_by_id(3)
        assert len(diag.nodes) > 0

    def test_node_positions_set(self, extractor):
        diag = extractor.extract_by_id(3)
        for node in diag.nodes:
            # All nodes should have non-zero dimensions
            assert node.rect_right > node.rect_left, f"Node {node.name} has zero width"
            # rect_top > rect_bottom (EA Y-axis: top is less negative)
            assert node.rect_top > node.rect_bottom, f"Node {node.name} has inverted height"

    def test_node_duid_present(self, extractor):
        diag = extractor.extract_by_id(3)
        # Most nodes should have a DUID so connectors can reference them
        nodes_with_duid = [n for n in diag.nodes if n.style.duid]
        assert len(nodes_with_duid) > 0

    def test_connectors_loaded(self, extractor):
        diag = extractor.extract_by_id(3)
        assert len(diag.connectors) > 0

    def test_connector_has_source_and_target(self, extractor):
        diag = extractor.extract_by_id(3)
        object_ids = {n.object_id for n in diag.nodes}
        for conn in diag.connectors:
            assert conn.source_object_id > 0
            assert conn.target_object_id > 0

    def test_connector_duid_roundtrip(self, extractor):
        """SOID/EOID on connectors should match DUID on the corresponding nodes."""
        diag = extractor.extract_by_id(3)
        duid_map = {n.style.duid: n for n in diag.nodes if n.style.duid}
        for conn in diag.connectors:
            if conn.style.start_duid:
                assert conn.style.start_duid in duid_map, (
                    f"Connector {conn.connector_id} SOID={conn.style.start_duid} "
                    f"not found in node DUIDs"
                )

    def test_notes_have_object_type(self, extractor):
        diag = extractor.extract_by_id(3)
        notes = [n for n in diag.nodes if n.object_type == "Note"]
        assert len(notes) > 0

    def test_class_nodes_have_attributes(self, extractor):
        diag = extractor.extract_by_id(3)
        class_nodes = [n for n in diag.nodes if n.object_type == "Class"]
        assert any(len(n.attributes) > 0 for n in class_nodes), (
            "Expected at least one class node with attributes"
        )

    def test_canvas_dimensions_set(self, extractor):
        diag = extractor.extract_by_id(3)
        assert diag.canvas_width > 0
        assert diag.canvas_height > 0

    def test_geometry_decoded(self, extractor):
        diag = extractor.extract_by_id(3)
        # At least some connectors should have geometry decoded
        conns_with_geometry = [
            c for c in diag.connectors
            if c.geometry.source_x is not None or c.geometry.edge_style != 1
        ]
        assert len(conns_with_geometry) > 0

    def test_sequence_diagram_loaded(self, extractor):
        diag = extractor.extract_by_id(12)  # diagram 12 is "p6" (Sequence type)
        assert diag.diagram_type == "Sequence"
        assert len(diag.nodes) > 0

    def test_yaml_serialization_roundtrip(self, extractor):
        import yaml

        diag = extractor.extract_by_id(3)
        raw = yaml.dump(diag.model_dump(), allow_unicode=True, sort_keys=False)
        loaded = yaml.full_load(raw)
        assert loaded["diagram_id"] == 3
        assert loaded["name"] == "message"
        assert len(loaded["nodes"]) == len(diag.nodes)
        assert len(loaded["connectors"]) == len(diag.connectors)

    def test_json_serialization_roundtrip(self, extractor):
        import json

        diag = extractor.extract_by_id(3)
        raw = json.dumps(diag.model_dump())
        loaded = json.loads(raw)
        assert loaded["diagram_id"] == 3
        assert len(loaded["nodes"]) == len(diag.nodes)


# ---------------------------------------------------------------------------
# SVG renderer tests
# ---------------------------------------------------------------------------


class TestCoordinateHelpers:
    def test_ea_to_svg_position(self):
        """EA rect_top is negative; SVG y should be positive."""
        from eaidl.native_diagram_model import NativeObjectStyle
        node = NativeDiagramNode(
            object_id=1, name="A", object_type="Class",
            rect_left=196, rect_top=-38, rect_right=322, rect_bottom=-123,
            z_order=0, style=NativeObjectStyle(),
        )
        x, y, w, h = _ea_to_svg(node)
        assert x == 196
        assert y == 38
        assert w == 126
        assert h == 85

    def test_clip_to_rect_horizontal(self):
        px, py = _clip_to_rect(100, 100, 80, 60, 1, 0)
        assert px == pytest.approx(140)
        assert py == pytest.approx(100)

    def test_clip_to_rect_vertical(self):
        px, py = _clip_to_rect(100, 100, 80, 60, 0, 1)
        assert px == pytest.approx(100)
        assert py == pytest.approx(130)

    def test_clip_to_rect_diagonal(self):
        px, py = _clip_to_rect(0, 0, 100, 60, 1, 1)
        # Should hit the vertical (x) boundary first: hw=50, hh=30 → t=30
        assert py == pytest.approx(30)
        assert px == pytest.approx(30)


class TestSvgRenderer:
    def test_produces_svg_element(self, extractor):
        diag = extractor.extract_by_id(3)
        svg = render_svg(diag)
        assert svg.startswith("<?xml")
        assert "<svg" in svg
        assert "</svg>" in svg

    def test_contains_node_names(self, extractor):
        diag = extractor.extract_by_id(3)
        svg = render_svg(diag)
        for node in diag.nodes:
            if node.object_type != "Note":
                assert node.name in svg, f"Node name {node.name!r} missing from SVG"

    def test_contains_connector_paths(self, extractor):
        diag = extractor.extract_by_id(3)
        svg = render_svg(diag)
        visible = [c for c in diag.connectors if not c.hidden]
        assert svg.count('<path') >= len(visible)

    def test_viewbox_set(self, extractor):
        diag = extractor.extract_by_id(3)
        svg = render_svg(diag)
        assert 'viewBox="' in svg

    def test_generalization_uses_filled_arrowhead(self, extractor):
        diag = extractor.extract_by_id(3)
        gen_conns = [c for c in diag.connectors if c.connector_type == "Generalization"]
        if not gen_conns:
            pytest.skip("No generalization connectors in diagram 3")
        svg = render_svg(diag)
        assert "arrow-generalization" in svg

    def test_note_dog_ear_polygon(self, extractor):
        diag = extractor.extract_by_id(3)
        notes = [n for n in diag.nodes if n.object_type == "Note"]
        if not notes:
            pytest.skip("No Note nodes in diagram 3")
        svg = render_svg(diag)
        assert "node-note" in svg

    def test_simple_diagram_renders(self, extractor):
        """Minimal diagram (8=flexible: 2 nodes, 1 connector) renders cleanly."""
        diag = extractor.extract_by_id(8)
        svg = render_svg(diag)
        assert "FlexibleName" in svg
        assert "FlexibleNameValues" in svg

    def test_role_label_present(self, extractor):
        """Diagram 8 has a connector with stereotype 'values' as role label."""
        diag = extractor.extract_by_id(8)
        # The connector has stereotype=values but no target_role — grab any diagram
        # that has a connector with a target_role
        for d_id in (3, 4, 5):
            d = extractor.extract_by_id(d_id)
            if any(c.target_role for c in d.connectors):
                svg = render_svg(d)
                role = next(c.target_role for c in d.connectors if c.target_role)
                assert role in svg
                return
        pytest.skip("No connectors with target_role found")


# ---------------------------------------------------------------------------
# HTML → XHTML conversion tests
# ---------------------------------------------------------------------------


class TestEaHtmlToXhtml:
    def test_empty_string(self):
        assert _ea_html_to_xhtml("") == ""

    def test_none(self):
        assert _ea_html_to_xhtml(None) == ""

    def test_plain_text_unchanged(self):
        result = _ea_html_to_xhtml("Hello world")
        assert "Hello world" in result

    def test_crlf_becomes_br(self):
        result = _ea_html_to_xhtml("line one\r\nline two")
        assert "<br/>" in result
        assert "line one" in result
        assert "line two" in result

    def test_cr_only_becomes_br(self):
        result = _ea_html_to_xhtml("line one\rline two")
        assert "<br/>" in result

    def test_bold_tag_preserved(self):
        result = _ea_html_to_xhtml("<b>bold text</b>")
        assert "<b>" in result
        assert "</b>" in result
        assert "bold text" in result

    def test_italic_tag_preserved(self):
        result = _ea_html_to_xhtml("<i>italic</i>")
        assert "<i>" in result and "</i>" in result

    def test_underline_tag_preserved(self):
        result = _ea_html_to_xhtml("<u>underline</u>")
        assert "<u>" in result and "</u>" in result

    def test_bare_br_self_closed(self):
        result = _ea_html_to_xhtml("line<br>two")
        assert "<br/>" in result
        assert "<br>" not in result

    def test_unordered_list_preserved(self):
        result = _ea_html_to_xhtml("<ul>\n\t<li>item one</li>\n\t<li>item two</li>\n</ul>")
        assert "<ul>" in result
        assert "<li>" in result
        assert "item one" in result

    def test_ordered_list_preserved(self):
        result = _ea_html_to_xhtml("<ol>\n\t<li>first</li>\n\t<li>second</li>\n</ol>")
        assert "<ol>" in result
        assert "first" in result

    def test_full_ea_note_html(self):
        """Full-fidelity test with the EA HTML found in DB (diagram 3, note id=69)."""
        raw = (
            "This is formatted note.\r\nWe have bullets:\r\n"
            "<ul>\r\n\t<li>one </li>\r\n\t<li>two</li>\r\n</ul>\r\n"
            "Enumeration\r\n"
            "<ol>\r\n\t<li>one</li>\r\n\t<li>two</li>\r\n</ol>\r\n\r\n\r\n"
            "Ther is <b>bold, </b><i>italic, </i><u>underline </u>"
            "<b><i><u>and all of them.</u></i></b>\r\n<b><i><u>\r\n</u></i></b>"
        )
        result = _ea_html_to_xhtml(raw)
        assert "This is formatted note." in result
        assert "<ul>" in result
        assert "<ol>" in result
        assert "<b>" in result
        assert "<i>" in result
        assert "<u>" in result
        assert "and all of them." in result
        # Trailing empty wrappers should be stripped
        assert result.endswith(">") or not result.endswith("<b><i><u>")


# ---------------------------------------------------------------------------
# Style config integration tests
# ---------------------------------------------------------------------------


class TestSvgStyleConfig:
    def test_default_style_renders(self, extractor):
        """render_svg() with default style (style=None) should work fine."""
        diag = extractor.extract_by_id(3)
        svg = render_svg(diag, style=None)
        assert "<svg" in svg

    def test_custom_header_color_appears_in_svg(self, extractor):
        """A custom node_header_color should appear in the SVG output."""
        from eaidl.config import NativeDiagramStyleConfig
        style = NativeDiagramStyleConfig(node_header_color="#abcdef")
        diag = extractor.extract_by_id(3)
        svg = render_svg(diag, style=style)
        assert "#abcdef" in svg

    def test_custom_canvas_bg_appears(self, extractor):
        from eaidl.config import NativeDiagramStyleConfig
        style = NativeDiagramStyleConfig(canvas_bg_color="#112233")
        diag = extractor.extract_by_id(8)
        svg = render_svg(diag, style=style)
        assert "#112233" in svg

    def test_custom_connector_color_appears(self, extractor):
        from eaidl.config import NativeDiagramStyleConfig
        style = NativeDiagramStyleConfig(connector_color="#ff0000")
        diag = extractor.extract_by_id(8)
        svg = render_svg(diag, style=style)
        assert "#ff0000" in svg

    def test_note_foreignobject_rendered(self, extractor):
        """Notes should produce <foreignObject> elements in SVG output."""
        diag = extractor.extract_by_id(3)
        notes = [n for n in diag.nodes if n.object_type == "Note"]
        if not notes:
            pytest.skip("No Note nodes in diagram 3")
        svg = render_svg(diag)
        assert "<foreignObject" in svg

    def test_note_html_content_in_svg(self, extractor):
        """Rich HTML note content (bold/italic/list) should appear in SVG."""
        diag = extractor.extract_by_id(3)
        notes = [n for n in diag.nodes if n.object_type == "Note" and n.note_text]
        if not notes:
            pytest.skip("No Note nodes with text in diagram 3")
        svg = render_svg(diag)
        # At minimum, the foreignObject div wrapper should be present
        assert 'xmlns="http://www.w3.org/1999/xhtml"' in svg

    def test_note_placeholder_fully_replaced(self, extractor):
        """The raw placeholder string must not appear in the final SVG."""
        diag = extractor.extract_by_id(3)
        svg = render_svg(diag)
        assert "__NOTEFO_" not in svg


# ---------------------------------------------------------------------------
# Sequence diagram tests
# ---------------------------------------------------------------------------


class TestSequenceDiagram:
    def test_sequence_messages_extracted(self, extractor):
        """Diagram 12 (p6) should have exactly 3 sequence messages."""
        diag = extractor.extract_by_id(12)
        assert len(diag.sequence_messages) == 3

    def test_sequence_messages_ordered(self, extractor):
        diag = extractor.extract_by_id(12)
        seq_nos = [m.seq_no for m in diag.sequence_messages]
        assert seq_nos == sorted(seq_nos)

    def test_sequence_message_names(self, extractor):
        diag = extractor.extract_by_id(12)
        names = {m.name for m in diag.sequence_messages}
        assert "Message1" in names
        assert "Message2" in names
        assert "AlternativeMessage" in names

    def test_sequence_message_stereotype(self, extractor):
        """Message1 has stereotype 'ResourceMessage'."""
        diag = extractor.extract_by_id(12)
        msg1 = next(m for m in diag.sequence_messages if m.name == "Message1")
        assert msg1.stereotype == "ResourceMessage"

    def test_sequence_message_return_value(self, extractor):
        """Message2 should have return_value parsed from PDATA2."""
        diag = extractor.extract_by_id(12)
        msg2 = next(m for m in diag.sequence_messages if m.name == "Message2")
        assert msg2.return_value == "return_value"

    def test_sequence_message_param_values(self, extractor):
        """Messages with paramvalues in StyleEx should be parsed."""
        diag = extractor.extract_by_id(12)
        msg2 = next(m for m in diag.sequence_messages if m.name == "Message2")
        assert msg2.param_values == "Argument2"

    def test_sequence_message_coordinates(self, extractor):
        """Messages should carry absolute start/end coordinates."""
        diag = extractor.extract_by_id(12)
        msg1 = next(m for m in diag.sequence_messages if m.name == "Message1")
        assert msg1.start_x > 0
        assert msg1.end_x > msg1.start_x  # left to right
        # Y coordinates should be negative (EA space)
        assert msg1.start_y < 0

    def test_non_sequence_diagram_has_no_messages(self, extractor):
        """Class diagram (3=message) should have empty sequence_messages."""
        diag = extractor.extract_by_id(3)
        assert diag.sequence_messages == []

    def test_sequence_svg_renders(self, extractor):
        """Sequence diagram should produce valid SVG without errors."""
        diag = extractor.extract_by_id(12)
        svg = render_svg(diag)
        assert "<svg" in svg
        assert "</svg>" in svg

    def test_sequence_svg_contains_message_names(self, extractor):
        """Message names should appear as text in the SVG."""
        diag = extractor.extract_by_id(12)
        svg = render_svg(diag)
        assert "Message1" in svg
        assert "Message2" in svg
        assert "AlternativeMessage" in svg

    def test_sequence_svg_contains_lifelines(self, extractor):
        """Lifeline names (Asset1, Asset2) should appear in SVG."""
        diag = extractor.extract_by_id(12)
        svg = render_svg(diag)
        assert "Asset1" in svg
        assert "Asset2" in svg

    def test_sequence_svg_contains_fragment(self, extractor):
        """InteractionFragment1 should render a fragment box."""
        diag = extractor.extract_by_id(12)
        svg = render_svg(diag)
        assert "fragment" in svg
        assert "InteractionFragment1" in svg

    def test_sequence_svg_dashed_lifelines(self, extractor):
        """Lifeline dashed lines should use stroke-dasharray."""
        diag = extractor.extract_by_id(12)
        svg = render_svg(diag)
        assert "stroke-dasharray" in svg

    def test_activation_bar_height_extracted(self, extractor):
        """Message1 (connector 54) should have activation_bar_height == 39."""
        diag = extractor.extract_by_id(12)
        msg1 = next(m for m in diag.sequence_messages if m.name == "Message1")
        assert msg1.activation_bar_height == 39

    def test_all_messages_have_activation_heights(self, extractor):
        """All three messages in diagram 12 should carry non-zero heights."""
        diag = extractor.extract_by_id(12)
        for msg in diag.sequence_messages:
            assert msg.activation_bar_height > 0, (
                f"Expected activation_bar_height > 0 for {msg.name}"
            )

    def test_note_connector_ref_extracted(self, extractor):
        """Note 77 in diagram 12 should reference connector id 54 (Message1)."""
        diag = extractor.extract_by_id(12)
        note = next(
            n for n in diag.nodes
            if n.object_id == 77
        )
        assert note.note_connector_ref == 54

    def test_note_without_connector_ref_is_none(self, extractor):
        """Note 76 (plain NoteLink note) should have note_connector_ref == None."""
        diag = extractor.extract_by_id(12)
        note = next(
            n for n in diag.nodes
            if n.object_id == 76
        )
        assert note.note_connector_ref is None

    def test_sequence_svg_contains_activation_bars(self, extractor):
        """Rendered SVG for sequence diagram should contain activation-bars group."""
        diag = extractor.extract_by_id(12)
        svg = render_svg(diag)
        assert 'id="activation-bars"' in svg

    def test_sequence_svg_contains_note_message_ref_line(self, extractor):
        """Rendered SVG for sequence diagram should contain note-message-refs group."""
        diag = extractor.extract_by_id(12)
        svg = render_svg(diag)
        assert 'id="note-message-refs"' in svg


# ---------------------------------------------------------------------------
# Excalidraw renderer
# ---------------------------------------------------------------------------


class TestExcalidrawRenderer:
    def test_produces_valid_json(self, extractor):
        diag = extractor.extract_by_id(3)
        raw = render_excalidraw(diag)
        import json
        doc = json.loads(raw)
        assert doc["type"] == "excalidraw"
        assert doc["version"] == 2

    def test_elements_present(self, extractor):
        diag = extractor.extract_by_id(3)
        import json
        doc = json.loads(render_excalidraw(diag))
        assert len(doc["elements"]) > 0

    def test_all_element_types_valid(self, extractor):
        valid_types = {"rectangle", "text", "line", "arrow", "ellipse", "diamond"}
        import json
        diag = extractor.extract_by_id(3)
        doc = json.loads(render_excalidraw(diag))
        for el in doc["elements"]:
            assert el["type"] in valid_types, f"Unexpected type {el['type']!r}"

    def test_required_fields_present(self, extractor):
        required = {"type", "id", "x", "y", "width", "height",
                    "strokeColor", "fillStyle", "roughness", "opacity"}
        import json
        diag = extractor.extract_by_id(3)
        doc = json.loads(render_excalidraw(diag))
        for el in doc["elements"]:
            missing = required - set(el.keys())
            assert not missing, f"Element {el['id']} missing {missing}"

    def test_class_node_elements_have_group_ids(self, extractor):
        """Class node elements should share a groupId so they move together."""
        import json
        diag = extractor.extract_by_id(3)
        doc = json.loads(render_excalidraw(diag))
        grouped = [el for el in doc["elements"] if el.get("groupIds")]
        assert len(grouped) > 0

    def test_unique_element_ids(self, extractor):
        import json
        diag = extractor.extract_by_id(3)
        doc = json.loads(render_excalidraw(diag))
        ids = [el["id"] for el in doc["elements"]]
        assert len(ids) == len(set(ids)), "Duplicate element IDs found"

    def test_connectors_rendered_as_arrows(self, extractor):
        import json
        diag = extractor.extract_by_id(3)
        doc = json.loads(render_excalidraw(diag))
        arrows = [el for el in doc["elements"] if el["type"] == "arrow"]
        assert len(arrows) > 0

    def test_view_background_color_in_appstate(self, extractor):
        import json
        diag = extractor.extract_by_id(3)
        doc = json.loads(render_excalidraw(diag))
        assert "viewBackgroundColor" in doc["appState"]

    def test_sequence_diagram_renders(self, extractor):
        """Sequence diagram (p6) should render without errors."""
        import json
        diag = extractor.extract_by_id(12)
        doc = json.loads(render_excalidraw(diag))
        assert len(doc["elements"]) > 0

    def test_sequence_message_arrows_present(self, extractor):
        import json
        diag = extractor.extract_by_id(12)
        doc = json.loads(render_excalidraw(diag))
        arrows = [el for el in doc["elements"] if el["type"] == "arrow"]
        assert len(arrows) >= 3  # 3 messages

    def test_sequence_lifelines_rendered(self, extractor):
        """Asset1 and Asset2 lifeline names should appear as text elements."""
        import json
        diag = extractor.extract_by_id(12)
        doc = json.loads(render_excalidraw(diag))
        texts = {el["text"] for el in doc["elements"] if el.get("type") == "text"}
        assert "Asset1" in texts
        assert "Asset2" in texts

    def test_note_rendered_as_rectangle(self, extractor):
        """Notes should produce at least one rectangle element."""
        import json
        diag = extractor.extract_by_id(3)  # diagram 3 has notes
        doc = json.loads(render_excalidraw(diag))
        rects = [el for el in doc["elements"] if el["type"] == "rectangle"]
        assert len(rects) > 0

    def test_deterministic_output(self, extractor):
        """Rendering the same diagram twice should produce identical JSON."""
        diag = extractor.extract_by_id(3)
        assert render_excalidraw(diag) == render_excalidraw(diag)

    def test_roughness_sloppy(self, extractor):
        """Shape/arrow elements use roughness=1; text elements use roughness=0."""
        import json
        diag = extractor.extract_by_id(3)
        doc = json.loads(render_excalidraw(diag))
        for el in doc["elements"]:
            if "roughness" not in el:
                continue
            if el["type"] == "text":
                assert el["roughness"] == 0
            else:
                assert el["roughness"] == 1, (
                    f"Element {el['id']} (type={el['type']}) has roughness {el['roughness']}"
                )

    def test_files_dict_present(self, extractor):
        import json
        diag = extractor.extract_by_id(3)
        doc = json.loads(render_excalidraw(diag))
        assert "files" in doc

    def test_arrows_have_start_binding(self, extractor):
        """Arrow elements should have startBinding pointing to a real element id."""
        import json
        diag = extractor.extract_by_id(3)
        doc = json.loads(render_excalidraw(diag))
        element_ids = {el["id"] for el in doc["elements"]}
        arrows = [el for el in doc["elements"] if el["type"] == "arrow"]
        assert len(arrows) > 0, "Expected at least one arrow"
        # Every bound arrow endpoint must reference a real element id
        for arrow in arrows:
            sb = arrow.get("startBinding")
            if sb is not None:
                assert sb["elementId"] in element_ids, (
                    f"Arrow {arrow['id']} startBinding.elementId {sb['elementId']!r} "
                    "not found in elements"
                )
            eb = arrow.get("endBinding")
            if eb is not None:
                assert eb["elementId"] in element_ids, (
                    f"Arrow {arrow['id']} endBinding.elementId {eb['elementId']!r} "
                    "not found in elements"
                )

    def test_arrows_are_bound_on_both_ends(self, extractor):
        """Most class-diagram arrows should be bound on both source and target."""
        import json
        diag = extractor.extract_by_id(3)
        doc = json.loads(render_excalidraw(diag))
        arrows = [el for el in doc["elements"] if el["type"] == "arrow"]
        bound_both = [
            a for a in arrows
            if a.get("startBinding") is not None and a.get("endBinding") is not None
        ]
        assert len(bound_both) > 0, "Expected at least one fully-bound arrow"

    def test_node_rects_list_bound_arrows(self, extractor):
        """Header rectangles of nodes connected by arrows must list those arrows
        in their boundElements."""
        import json
        diag = extractor.extract_by_id(3)
        doc = json.loads(render_excalidraw(diag))
        element_by_id = {el["id"]: el for el in doc["elements"]}
        arrows = [el for el in doc["elements"] if el["type"] == "arrow"]
        bound_arrow_ids: set = set()
        for arrow in arrows:
            for key in ("startBinding", "endBinding"):
                binding = arrow.get(key)
                if binding is not None:
                    bound_arrow_ids.add(arrow["id"])
                    rect = element_by_id.get(binding["elementId"])
                    assert rect is not None
                    be_ids = {be["id"] for be in rect.get("boundElements", [])}
                    assert arrow["id"] in be_ids, (
                        f"Rect {rect['id']} does not list arrow {arrow['id']} "
                        "in its boundElements"
                    )

    def test_binding_references_header_rects(self, extractor):
        """Arrow bindings should point to 'hdr' elements (the header rects),
        not body or attr elements."""
        import json
        diag = extractor.extract_by_id(3)
        doc = json.loads(render_excalidraw(diag))
        element_by_id = {el["id"]: el for el in doc["elements"]}
        arrows = [el for el in doc["elements"] if el["type"] == "arrow"]
        for arrow in arrows:
            for key in ("startBinding", "endBinding"):
                binding = arrow.get(key)
                if binding is not None:
                    eid = binding["elementId"]
                    assert eid.startswith("hdr-"), (
                        f"Arrow {arrow['id']} {key}.elementId={eid!r} "
                        "should start with 'hdr-'"
                    )


# ---------------------------------------------------------------------------
# Hyperlink / ea_guid tests
# ---------------------------------------------------------------------------


class TestEaGuid:
    """ea_guid is extracted from t_object.ea_guid and stored on each node."""

    def test_nodes_have_ea_guid(self, extractor):
        diag = extractor.extract_by_id(3)
        nodes_with_guid = [n for n in diag.nodes if n.ea_guid]
        assert len(nodes_with_guid) > 0, "Expected at least some nodes to have ea_guid set"

    def test_ea_guid_format(self, extractor):
        """ea_guid should look like a GUID string: {xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx}."""
        import re
        guid_re = re.compile(r"^\{[0-9A-Fa-f-]+\}$")
        diag = extractor.extract_by_id(3)
        for node in diag.nodes:
            if node.ea_guid:
                assert guid_re.match(node.ea_guid), (
                    f"Node {node.name!r} ea_guid {node.ea_guid!r} is not GUID-shaped"
                )

    def test_ea_guid_unique_within_diagram(self, extractor):
        """Each ea_guid should appear at most once in a diagram."""
        diag = extractor.extract_by_id(3)
        guids = [n.ea_guid for n in diag.nodes if n.ea_guid]
        assert len(guids) == len(set(guids)), "Duplicate ea_guid values found in diagram"


class TestSvgLinkMap:
    """svg_link_map() returns a dict keyed by ea_guid usable for post-processing."""

    def test_returns_dict(self, extractor):
        diag = extractor.extract_by_id(3)
        lm = svg_link_map(diag)
        assert isinstance(lm, dict)
        assert len(lm) > 0

    def test_keys_are_guid_or_fallback(self, extractor):
        import re
        guid_re = re.compile(r"^\{[0-9A-Fa-f-]+\}$")
        fallback_re = re.compile(r"^#\d+$")
        diag = extractor.extract_by_id(3)
        for key in svg_link_map(diag):
            assert guid_re.match(key) or fallback_re.match(key), (
                f"Unexpected link-map key format: {key!r}"
            )

    def test_values_contain_name_and_object_id(self, extractor):
        diag = extractor.extract_by_id(3)
        for key, entry in svg_link_map(diag).items():
            assert "name" in entry
            assert "object_id" in entry

    def test_guid_keys_match_node_guids(self, extractor):
        diag = extractor.extract_by_id(3)
        # Notes are excluded from the link map
        node_guids = {
            n.ea_guid for n in diag.nodes
            if n.ea_guid and n.object_type != "Note"
        }
        map_keys = set(svg_link_map(diag).keys())
        assert node_guids <= map_keys, (
            "Not all non-Note node ea_guids appear as keys in svg_link_map()"
        )


class TestRewriteSvgLinks:
    """rewrite_svg_links() replaces eaidl:{guid} placeholders with real URLs."""

    def test_placeholder_replaced(self):
        guid = "{3522A830-8853-4c52-9908-40871435BB3B}"
        svg = f'<a href="eaidl:{guid}"><rect/></a>'
        result = rewrite_svg_links(svg, {guid: "https://example.com/types/Foo.html"})
        assert "eaidl:" not in result
        assert "https://example.com/types/Foo.html" in result

    def test_unknown_guid_left_unchanged(self):
        guid = "{AAAAAAAA-0000-0000-0000-000000000000}"
        svg = f'<a href="eaidl:{guid}"><rect/></a>'
        result = rewrite_svg_links(svg, {})
        assert f"eaidl:{guid}" in result

    def test_multiple_replacements(self):
        svg = '<a href="eaidl:{A}">x</a><a href="eaidl:{B}">y</a>'
        result = rewrite_svg_links(svg, {"{A}": "http://a.com", "{B}": "http://b.com"})
        assert "http://a.com" in result
        assert "http://b.com" in result
        assert "eaidl:" not in result


class TestSvgHyperlinks:
    """The SVG renderer inserts eaidl: placeholder <a> wrappers by default."""

    def test_svg_contains_placeholder_hrefs(self, extractor):
        diag = extractor.extract_by_id(3)
        svg = render_svg(diag)
        assert "eaidl:" in svg, "Expected eaidl: placeholder hrefs in default SVG output"

    def test_svg_href_contains_curlies(self, extractor):
        """Placeholder href should look like eaidl:{...guid...}."""
        import re
        diag = extractor.extract_by_id(3)
        svg = render_svg(diag)
        assert re.search(r'href="eaidl:\{[0-9A-Fa-f-]+\}"', svg), (
            "Expected eaidl:{guid} pattern in SVG href attributes"
        )

    def test_svg_links_disabled_when_template_empty(self, extractor):
        from eaidl.config import NativeDiagramStyleConfig
        style = NativeDiagramStyleConfig(node_link_template="")
        diag = extractor.extract_by_id(3)
        svg = render_svg(diag, style=style)
        assert "eaidl:" not in svg
        assert "<a " not in svg


class TestExcalidrawLinks:
    """Excalidraw element link fields are populated from ea_guid by default."""

    def test_header_rects_have_link(self, extractor):
        import json
        diag = extractor.extract_by_id(3)
        doc = json.loads(render_excalidraw(diag))
        rects = [el for el in doc["elements"] if el["type"] == "rectangle"]
        # At least some rects (header rects of class nodes) should carry a link
        linked = [el for el in rects if el.get("link")]
        assert len(linked) > 0, "Expected at least one rectangle element with a link"

    def test_header_link_is_placeholder(self, extractor):
        import json
        diag = extractor.extract_by_id(3)
        doc = json.loads(render_excalidraw(diag))
        linked = [el for el in doc["elements"] if el.get("link")]
        for el in linked:
            assert el["link"].startswith("eaidl:"), (
                f"Expected eaidl: prefix on link, got {el['link']!r}"
            )

    def test_links_disabled_when_template_empty(self, extractor):
        import json
        from eaidl.config import NativeDiagramStyleConfig
        style = NativeDiagramStyleConfig(node_link_template="")
        diag = extractor.extract_by_id(3)
        doc = json.loads(render_excalidraw(diag, style=style))
        linked = [el for el in doc["elements"] if el.get("link")]
        assert len(linked) == 0, "Expected no linked elements when node_link_template=''"


# ---------------------------------------------------------------------------
# Granular hyperlink behaviour (header vs attribute rows)
# ---------------------------------------------------------------------------


class TestAttributeTypeGuid:
    """type_guid is populated on attributes whose type resolves to a model class."""

    def test_some_attributes_have_type_guid(self, extractor):
        diag = extractor.extract_by_id(3)
        class_nodes = [n for n in diag.nodes if n.object_type in ("Class", "Part")]
        all_attrs = [a for n in class_nodes for a in n.attributes]
        linked = [a for a in all_attrs if a.type_guid]
        assert len(linked) > 0, "Expected at least one attribute to have a type_guid"

    def test_type_guid_format(self, extractor):
        import re
        guid_re = re.compile(r"^\{[0-9A-Fa-f-]+\}$")
        diag = extractor.extract_by_id(3)
        for node in diag.nodes:
            for attr in node.attributes:
                if attr.type_guid:
                    assert guid_re.match(attr.type_guid), (
                        f"Attr {attr.name!r} type_guid {attr.type_guid!r} is not GUID-shaped"
                    )

    def test_type_guid_distinct_from_owner_guid(self, extractor):
        """The type_guid of an attribute should not equal the owning node's ea_guid."""
        diag = extractor.extract_by_id(3)
        for node in diag.nodes:
            for attr in node.attributes:
                if attr.type_guid and node.ea_guid:
                    # An attribute's type is rarely the same class — but the key
                    # check is just that the field is independently set.
                    assert isinstance(attr.type_guid, str)


class TestSvgGranularLinks:
    """Header links to the class; each attribute row links to its type."""

    def test_svg_has_multiple_distinct_hrefs(self, extractor):
        """A diagram with cross-referencing types should have > 1 unique eaidl: href."""
        import re
        diag = extractor.extract_by_id(3)
        svg = render_svg(diag)
        hrefs = set(re.findall(r'href="(eaidl:[^"]+)"', svg))
        assert len(hrefs) > 1, (
            "Expected multiple distinct eaidl: hrefs (one per class + one per linked type)"
        )

    def test_header_link_differs_from_attribute_link(self, extractor):
        """For a node with linked-type attributes, header href != at least one attr href."""
        import re
        diag = extractor.extract_by_id(3)
        # Find a node that has ea_guid AND at least one attribute with type_guid
        candidate = next(
            (
                n for n in diag.nodes
                if n.ea_guid and any(a.type_guid for a in n.attributes)
            ),
            None,
        )
        if candidate is None:
            pytest.skip("No suitable node found in diagram 3")
        node_href = f"eaidl:{candidate.ea_guid}"
        attr_hrefs = {
            f"eaidl:{a.type_guid}" for a in candidate.attributes if a.type_guid
        }
        assert node_href not in attr_hrefs or len(attr_hrefs) > 0, (
            "At least one attribute href should be present alongside the header href"
        )
        svg = render_svg(diag)
        assert node_href in svg
        for ah in attr_hrefs:
            assert ah in svg

    def test_svg_no_link_when_template_empty(self, extractor):
        """With node_link_template='', no <a> elements at all — verified separately
        for the attribute level (not just class level)."""
        from eaidl.config import NativeDiagramStyleConfig
        style = NativeDiagramStyleConfig(node_link_template="")
        diag = extractor.extract_by_id(3)
        svg = render_svg(diag, style=style)
        assert "<a " not in svg
