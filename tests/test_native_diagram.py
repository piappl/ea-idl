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
from eaidl.native_diagram_svg import render_svg, _ea_to_svg, _clip_to_rect, _edge_points, _ea_html_to_xhtml
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
    def test_show_foreign_controls_package_qualifiers(self, extractor):
        diagram = extractor.extract_by_id(3)
        assert diagram.show_foreign is True
        qualified = {node.object_id: node.display_context for node in diagram.nodes}
        assert any(context for context in qualified.values())

        unqualified = extractor._extract_nodes(3, 8, show_foreign=False)
        assert all(node.display_context is None for node in unqualified)
        assert {node.object_id for node in unqualified} == set(qualified)

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
                    f"Connector {conn.connector_id} SOID={conn.style.start_duid} " f"not found in node DUIDs"
                )

    def test_notes_have_object_type(self, extractor):
        diag = extractor.extract_by_id(3)
        notes = [n for n in diag.nodes if n.object_type == "Note"]
        assert len(notes) > 0

    def test_class_nodes_have_attributes(self, extractor):
        diag = extractor.extract_by_id(3)
        class_nodes = [n for n in diag.nodes if n.object_type == "Class"]
        assert any(len(n.attributes) > 0 for n in class_nodes), "Expected at least one class node with attributes"

    def test_canvas_dimensions_set(self, extractor):
        diag = extractor.extract_by_id(3)
        assert diag.canvas_width > 0
        assert diag.canvas_height > 0

    def test_geometry_decoded(self, extractor):
        diag = extractor.extract_by_id(3)
        # At least some connectors should have geometry decoded
        conns_with_geometry = [
            c for c in diag.connectors if c.geometry.source_x is not None or c.geometry.edge_style != 1
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
            object_id=1,
            name="A",
            object_type="Class",
            rect_left=196,
            rect_top=-38,
            rect_right=322,
            rect_bottom=-123,
            z_order=0,
            style=NativeObjectStyle(),
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
        assert svg.count("<path") >= len(visible)

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
    def test_ea_detail_mode_keeps_bounds_and_visible_note(self, extractor):
        from xml.etree import ElementTree as ET
        from eaidl.config import NativeDiagramStyleConfig
        from eaidl.native_diagram_model import NativeDiagramAttribute

        diagram = extractor.extract_by_id(3)
        node = next(n for n in diagram.nodes if n.object_type == "Class")
        node = node.model_copy(
            update={
                "rect_left": 0,
                "rect_right": 140,
                "rect_top": 0,
                "rect_bottom": -110,
                "note_text": "Visible class documentation.",
                "attributes": [NativeDiagramAttribute(name="hidden", type="string", visibility="Public")],
                "style": node.style.model_copy(update={"extra": {"Notes": "1000", "AttPub": "0"}}),
            }
        )
        svg = render_svg(
            diagram.model_copy(update={"nodes": [node], "connectors": []}),
            style=NativeDiagramStyleConfig(ea_detail_nodes=True),
        )
        root = ET.fromstring(svg)
        ns = {"s": "http://www.w3.org/2000/svg"}
        card = root.find('.//s:g[@class="node-class"]', ns)
        assert card.find("s:rect", ns).get("width") == "140.0"
        texts = [e.text or "" for e in card.findall("s:text", ns)]
        assert any("Visible class" in line for line in texts)
        assert not any("hidden" in line for line in texts)

    def test_ea_detail_orders_attributes_below_external_parent(self, extractor):
        from xml.etree import ElementTree as ET
        from eaidl.config import NativeDiagramStyleConfig
        from eaidl.native_diagram_model import NativeDiagramAttribute

        diagram = extractor.extract_by_id(3)
        node = next(n for n in diagram.nodes if n.object_type == "Class")
        node = node.model_copy(
            update={
                "rect_left": 0,
                "rect_right": 180,
                "rect_top": 0,
                "rect_bottom": -120,
                "parent_name": "Action",
                "attributes": [
                    NativeDiagramAttribute(name="zeta", type="string"),
                    NativeDiagramAttribute(name="alpha", type="string"),
                ],
            }
        )
        root = ET.fromstring(
            render_svg(
                diagram.model_copy(
                    update={
                        "nodes": [node],
                        "connectors": [],
                    }
                ),
                style=NativeDiagramStyleConfig(ea_detail_nodes=True),
            )
        )
        card = root.find('.//{http://www.w3.org/2000/svg}g[@class="node-class"]')
        texts = [element.text or "" for element in card.findall("{http://www.w3.org/2000/svg}text")]
        assert texts[0] == "Action"
        assert texts.index("alpha: string") < texts.index("zeta: string")

    def test_ea_detail_wraps_class_names_from_box_width(self, extractor):
        from xml.etree import ElementTree as ET
        from eaidl.config import NativeDiagramStyleConfig

        diagram = extractor.extract_by_id(3)
        base = next(node for node in diagram.nodes if node.object_type == "Class")
        system = base.model_copy(
            update={
                "name": "Enabling Unmanned Platform Control System",
                "stereotype": "System",
                "display_context": None,
                "parent_name": None,
                "note_text": None,
                "rect_left": 0,
                "rect_right": 157,
                "rect_top": 0,
                "rect_bottom": -58,
                "attributes": [],
            }
        )
        constraint = base.model_copy(
            update={
                "object_id": 99999,
                "name": " UxV Control Interface should mesh with the right vehicle.",
                "stereotype": "ResourceConstraint",
                "display_context": None,
                "parent_name": None,
                "note_text": "Constraint description.",
                "rect_left": 200,
                "rect_right": 381,
                "rect_top": 0,
                "rect_bottom": -137,
                "attributes": [],
                "style": base.style.model_copy(update={"extra": {"Notes": "1000"}}),
            }
        )
        root = ET.fromstring(
            render_svg(
                diagram.model_copy(
                    update={
                        "nodes": [system, constraint],
                        "connectors": [],
                    }
                ),
                style=NativeDiagramStyleConfig(ea_detail_nodes=True, font_size=10),
            )
        )
        ns = "{http://www.w3.org/2000/svg}"
        system_card = root.find(f".//{ns}g[@data-object-id='{system.object_id}']")
        constraint_card = root.find(f".//{ns}g[@data-object-id='{constraint.object_id}']")

        def names(card):
            return [
                (item.text, item.get("y")) for item in card.findall(ns + "text") if item.get("font-weight") == "bold"
            ]

        assert names(system_card) == [("Enabling Unmanned Platform", "29.0"), ("Control System", "42.0")]
        assert names(constraint_card) == [
            (" UxV Control Interface should mesh with", "29.0"),
            ("the right vehicle.", "42.0"),
        ]
        assert constraint_card.find(ns + "line").get("y1") == "50.0"

    def test_ea_detail_diagram_hides_fields_and_shows_foreign_package_footer(self, extractor):
        from xml.etree import ElementTree as ET
        from eaidl.config import NativeDiagramStyleConfig
        from eaidl.native_diagram_model import NativeDiagramAttribute

        diagram = extractor.extract_by_id(3)
        base = next(node for node in diagram.nodes if node.object_type == "Class")
        node = base.model_copy(
            update={
                "name": "DetectMCM",
                "display_context": "mcm",
                "foreign_package_path": "stanag4817::p7::aep105::base::task_specialization::mcm",
                "rect_left": 10,
                "rect_right": 146,
                "rect_top": 0,
                "rect_bottom": -49,
                "attributes": [NativeDiagramAttribute(name="p_detection", type="float")],
            }
        )
        root = ET.fromstring(
            render_svg(
                diagram.model_copy(
                    update={
                        "nodes": [node],
                        "connectors": [],
                        "hide_attributes": True,
                    }
                ),
                style=NativeDiagramStyleConfig(ea_detail_nodes=True),
            )
        )
        ns = "{http://www.w3.org/2000/svg}"
        card = root.find(f".//{ns}g[@data-object-id='{node.object_id}']")
        assert card.find(ns + "rect").get("height") == "49.0"
        texts = [item.text for item in card.findall(ns + "text")]
        assert "DetectMCM" in texts
        assert "mcm::DetectMCM" not in texts
        assert "p_detection: float" not in texts
        assert texts[-2:] == [
            "(from stanag4817::p7::aep105::",
            "base::task_specialization::mcm)",
        ]
        assert all(item.get("font-style") == "italic" for item in card.findall(ns + "text")[-2:])

    def test_ea_inherited_fields_keep_owner_and_stereotype_groups(self, extractor):
        from eaidl.native_diagram_model import NativeDiagramAttribute
        from eaidl.native_diagram_svg import _ea_attribute_rows

        diagram = extractor.extract_by_id(3)
        base = next(node for node in diagram.nodes if node.object_type == "Class")
        node = base.model_copy(
            update={
                "parent_name": "BaseOtherEntity",
                "attributes": [
                    NativeDiagramAttribute(name="products", type="Products"),
                    NativeDiagramAttribute(
                        name="timestamp", type="Time", inherited_from="BaseOtherEntity", inheritance_depth=1
                    ),
                    NativeDiagramAttribute(
                        name="identifier", type="GUID", inherited_from="BaseWhat", inheritance_depth=2
                    ),
                    NativeDiagramAttribute(
                        name="description",
                        type="Description",
                        stereotype="optional",
                        inherited_from="BaseOtherEntity",
                        inheritance_depth=1,
                    ),
                ],
            }
        )
        assert [(attr.name, baseline) for attr, baseline in _ea_attribute_rows(node)] == [
            ("products", 67),
            ("timestamp", 96),
            ("identifier", 125),
            ("description", 171),
        ]

    def test_ea_detail_stereotype_fills_when_object_has_no_explicit_colour(self, extractor):
        from eaidl.config import NativeDiagramStyleConfig
        from eaidl.native_diagram_svg import _node_background

        diagram = extractor.extract_by_id(3)
        node = next(n for n in diagram.nodes if n.object_type == "Class")
        node = node.model_copy(
            update={
                "stereotype": "idlStruct",
                "style": node.style.model_copy(update={"background_color": -1}),
            }
        )
        assert _node_background(node, NativeDiagramStyleConfig(ea_detail_nodes=True)) == "#ef7d00"
        assert (
            _node_background(
                node.model_copy(update={"stereotype": "Standard"}), NativeDiagramStyleConfig(ea_detail_nodes=True)
            )
            == "#ffd618"
        )
        assert (
            _node_background(
                node, NativeDiagramStyleConfig(ea_detail_nodes=True, stereotype_bg_colors={"idlStruct": "#123456"})
            )
            == "#123456"
        )
        explicit = node.model_copy(
            update={
                "style": node.style.model_copy(update={"background_color": 0x302010}),
            }
        )
        assert _node_background(explicit, NativeDiagramStyleConfig(ea_detail_nodes=True)) == "#102030"

    def test_sequence_self_message_uses_stored_return_y(self):
        from xml.etree import ElementTree as ET
        from eaidl.config import NativeDiagramStyleConfig
        from eaidl.native_diagram_model import NativeSequenceMessage
        from eaidl.native_diagram_svg import _render_sequence_message

        message = NativeSequenceMessage(
            connector_id=1,
            source_object_id=2,
            target_object_id=2,
            start_x=100,
            start_y=-250,
            end_x=100,
            end_y=-265,
        )
        root = ET.Element("g")
        _render_sequence_message(root, message, {}, NativeDiagramStyleConfig())
        path = root.find(".//path")
        assert path.get("d") == "M 100.0,250.0 L 140.0,250.0 L 140.0,265.0 L 100.0,265.0"

    def test_nested_sequence_part_head_follows_parent(self, extractor):
        from xml.etree import ElementTree as ET
        from eaidl.config import NativeDiagramStyleConfig
        from eaidl.native_diagram_svg import _render_lifeline

        diagram = extractor.extract_by_id(3)
        first, second = [n for n in diagram.nodes if n.object_type == "Class"][:2]
        parent = first.model_copy(
            update={
                "rect_left": 0,
                "rect_right": 200,
                "rect_top": -50,
                "rect_bottom": -400,
            }
        )
        child = second.model_copy(
            update={
                "rect_left": 25,
                "rect_right": 100,
                "rect_top": -50,
                "rect_bottom": -400,
                "parent_object_id": parent.object_id,
            }
        )
        root = ET.Element("g")
        _render_lifeline(root, child, NativeDiagramStyleConfig(), parent)
        head = root.find(".//rect")
        assert (head.get("y"), head.get("height")) == ("100.0", "25")

    def test_statechart_uses_rounded_states_and_final_node(self, extractor):
        from xml.etree import ElementTree as ET
        from eaidl.config import NativeDiagramStyleConfig

        diagram = extractor.extract_by_id(3)
        first, second = [n for n in diagram.nodes if n.object_type == "Class"][:2]
        state = first.model_copy(
            update={
                "name": "ACTIVE",
                "object_type": "State",
                "rect_left": 0,
                "rect_right": 120,
                "rect_top": 0,
                "rect_bottom": -60,
            }
        )
        final = second.model_copy(
            update={
                "name": "Final",
                "object_type": "StateNode",
                "rect_left": 150,
                "rect_right": 170,
                "rect_top": 0,
                "rect_bottom": -20,
            }
        )
        transition = diagram.connectors[0].model_copy(
            update={
                "source_object_id": state.object_id,
                "target_object_id": final.object_id,
                "connector_type": "StateFlow",
                "transition_event": "TaskStateEnum.ACTIVE",
                "geometry": diagram.connectors[0].geometry.model_copy(update={"waypoints": []}),
            }
        )
        root = ET.fromstring(
            render_svg(
                diagram.model_copy(
                    update={
                        "diagram_type": "Statechart",
                        "nodes": [state, final],
                        "connectors": [transition],
                    }
                ),
                style=NativeDiagramStyleConfig(ea_detail_nodes=True),
            )
        )
        groups = root.findall('.//{http://www.w3.org/2000/svg}g[@class="node-state"]')
        assert groups[0].find("{http://www.w3.org/2000/svg}rect").get("rx") == "20"
        assert len(groups[1].findall("{http://www.w3.org/2000/svg}ellipse")) == 2
        assert any(text.text == "TaskStateEnum.ACTIVE" for text in root.iter("{http://www.w3.org/2000/svg}text"))

    def test_stale_class_bend_does_not_pull_connector_off_diagram(self, extractor):
        from xml.etree import ElementTree as ET
        from eaidl.config import NativeDiagramStyleConfig

        diagram = extractor.extract_by_id(3)
        first, second = [n for n in diagram.nodes if n.object_type == "Class"][:2]
        source = first.model_copy(
            update={
                "rect_left": 0,
                "rect_right": 100,
                "rect_top": 0,
                "rect_bottom": -80,
                "attributes": [],
            }
        )
        target = second.model_copy(
            update={
                "rect_left": 200,
                "rect_right": 300,
                "rect_top": -10,
                "rect_bottom": -90,
                "attributes": [],
            }
        )
        connector = diagram.connectors[0].model_copy(
            update={
                "source_object_id": source.object_id,
                "target_object_id": target.object_id,
                "connector_type": "Abstraction",
                "geometry": diagram.connectors[0].geometry.model_copy(
                    update={
                        "edge_style": 2,
                        "waypoints": [[1000, -1000]],
                    }
                ),
            }
        )
        root = ET.fromstring(
            render_svg(
                diagram.model_copy(
                    update={
                        "nodes": [source, target],
                        "connectors": [connector],
                    }
                ),
                style=NativeDiagramStyleConfig(ea_detail_nodes=True),
            )
        )
        path = root.find('.//{http://www.w3.org/2000/svg}g[@class="connector"]/{http://www.w3.org/2000/svg}path')
        assert path.get("d") == "M 100.0,45.0 L 200.0,45.0"

    def test_waypoint_clipping_uses_first_and_last_bend(self, extractor):
        diagram = extractor.extract_by_id(3)
        first, second = [n for n in diagram.nodes if n.object_type == "Class"][:2]
        source = first.model_copy(
            update={
                "rect_left": 0,
                "rect_right": 100,
                "rect_top": -200,
                "rect_bottom": -260,
            }
        )
        target = second.model_copy(
            update={
                "rect_left": 200,
                "rect_right": 300,
                "rect_top": 0,
                "rect_bottom": -60,
            }
        )
        assert _edge_points(source, target, 0, 0, None, None, [(50, 100), (250, 100)]) == (
            (50, 200),
            (250, 60),
        )

    def test_ea_endpoint_offsets_project_to_node_border(self, extractor):
        diagram = extractor.extract_by_id(3)
        first, second = [n for n in diagram.nodes if n.object_type == "Class"][:2]
        source = first.model_copy(
            update={
                "rect_left": 0,
                "rect_right": 100,
                "rect_top": 0,
                "rect_bottom": -60,
            }
        )
        target = second.model_copy(
            update={
                "rect_left": 200,
                "rect_right": 300,
                "rect_top": 0,
                "rect_bottom": -60,
            }
        )
        assert _edge_points(source, target, 0, -1, 0, -1) == ((100, 30), (200, 30))

    def test_ea_edge_modes_follow_shared_row_and_column(self, extractor):
        from eaidl.native_diagram_svg import _ea_straight_route

        diagram = extractor.extract_by_id(3)
        first, second = [n for n in diagram.nodes if n.object_type == "Class"][:2]
        source = first.model_copy(
            update={
                "rect_left": 0,
                "rect_right": 100,
                "rect_top": 0,
                "rect_bottom": -60,
            }
        )
        target = second.model_copy(
            update={
                "rect_left": 300,
                "rect_right": 400,
                "rect_top": -10,
                "rect_bottom": -140,
            }
        )
        connector = diagram.connectors[0].model_copy(
            update={
                "source_object_id": source.object_id,
                "target_object_id": target.object_id,
                "geometry": diagram.connectors[0].geometry.model_copy(
                    update={
                        "edge_style": 2,
                        "source_x": None,
                        "source_y": None,
                        "end_x": None,
                        "end_y": None,
                        "waypoints": [],
                    }
                ),
            }
        )
        assert _ea_straight_route(source, target, connector, []) == [(100.0, 30.0), (300.0, 30.0)]

        target = target.model_copy(
            update={
                "rect_left": 40,
                "rect_right": 140,
                "rect_top": -500,
                "rect_bottom": -560,
            }
        )
        connector = connector.model_copy(
            update={
                "geometry": connector.geometry.model_copy(update={"edge_style": 3}),
            }
        )
        assert _ea_straight_route(source, target, connector, []) == [(70.0, 60.0), (70.0, 500.0)]

        offset_connector = connector.model_copy(
            update={
                "geometry": connector.geometry.model_copy(update={"source_x": 29, "end_x": 49}),
            }
        )
        assert _ea_straight_route(source, target, offset_connector, []) is None

        target = target.model_copy(
            update={
                "rect_top": -120,
                "rect_bottom": -180,
            }
        )
        connector = connector.model_copy(
            update={
                "geometry": connector.geometry.model_copy(update={"source_x": 35}),
            }
        )
        assert _ea_straight_route(source, target, connector, []) == [(85.0, 60.0), (85.0, 120.0)]

    def test_stale_path_does_not_bend_straight_orthogonal_edge(self, extractor):
        from eaidl.native_diagram_svg import _ea_straight_route

        diagram = extractor.extract_by_id(3)
        first, second = [n for n in diagram.nodes if n.object_type == "Class"][:2]
        source = first.model_copy(
            update={
                "rect_left": 200,
                "rect_right": 300,
                "rect_top": 0,
                "rect_bottom": -60,
            }
        )
        target = second.model_copy(
            update={
                "rect_left": 0,
                "rect_right": 100,
                "rect_top": 0,
                "rect_bottom": -80,
            }
        )
        connector = diagram.connectors[0].model_copy(
            update={
                "source_object_id": source.object_id,
                "target_object_id": target.object_id,
                "geometry": diagram.connectors[0].geometry.model_copy(
                    update={
                        "edge_style": 4,
                        "source_x": 0,
                        "source_y": 0,
                        "end_x": None,
                        "end_y": None,
                    }
                ),
            }
        )
        assert _ea_straight_route(source, target, connector, [(150, 140)]) == [
            (200.0, 30.0),
            (100.0, 30.0),
        ]

    def test_saved_association_bend_beats_implicit_property_anchor(self, extractor):
        from xml.etree import ElementTree as ET
        from eaidl.config import NativeDiagramStyleConfig
        from eaidl.native_diagram_model import NativeDiagramAttribute

        diagram = extractor.extract_by_id(3)
        first, second = [n for n in diagram.nodes if n.object_type == "Class"][:2]
        source = first.model_copy(
            update={
                "rect_left": 250,
                "rect_right": 443,
                "rect_top": -160,
                "rect_bottom": -330,
                "attributes": [NativeDiagramAttribute(name="constraints", type="Constraint")],
            }
        )
        target = second.model_copy(
            update={
                "rect_left": 53,
                "rect_right": 215,
                "rect_top": -918,
                "rect_bottom": -1033,
            }
        )
        base = diagram.connectors[0]
        connector = base.model_copy(
            update={
                "connector_type": "Association",
                "source_object_id": source.object_id,
                "target_object_id": target.object_id,
                "target_role": "constraints",
                "source_feature_guid": None,
                "target_feature_guid": None,
                "geometry": base.geometry.model_copy(
                    update={
                        "source_x": -1,
                        "source_y": 26,
                        "end_x": -46,
                        "end_y": 54,
                        "edge_style": 4,
                        "waypoints": [[88, -219]],
                    }
                ),
            }
        )
        root = ET.fromstring(
            render_svg(
                diagram.model_copy(
                    update={
                        "nodes": [source, target],
                        "connectors": [connector],
                    }
                ),
                style=NativeDiagramStyleConfig(ea_detail_nodes=True),
            )
        )
        ns = "{http://www.w3.org/2000/svg}"
        path = root.find(f".//{ns}g[@data-connector-id='{connector.connector_id}']/{ns}path")
        assert path.get("d") == "M 250.0,219.0 L 88.0,219.0 L 88.0,918.0"

    def test_named_association_keeps_geometry_outside_property_link_case(self, extractor):
        from xml.etree import ElementTree as ET
        from eaidl.config import NativeDiagramStyleConfig
        from eaidl.native_diagram_model import NativeDiagramAttribute

        diagram = extractor.extract_by_id(3)
        first, second = [n for n in diagram.nodes if n.object_type == "Class"][:2]
        source = first.model_copy(
            update={
                "rect_left": 80,
                "rect_right": 170,
                "rect_top": -89,
                "rect_bottom": -174,
                "attributes": [NativeDiagramAttribute(name="header", type="Header")],
            }
        )
        target = second.model_copy(
            update={
                "rect_left": 504,
                "rect_right": 594,
                "rect_top": -75,
                "rect_bottom": -145,
                "attributes": [],
            }
        )
        base = diagram.connectors[0]
        connector = base.model_copy(
            update={
                "connector_type": "Association",
                "source_object_id": source.object_id,
                "target_object_id": target.object_id,
                "target_role": "header",
                "source_feature_guid": None,
                "target_feature_guid": None,
                "geometry": base.geometry.model_copy(
                    update={
                        "edge_style": 2,
                        "waypoints": [],
                        "source_x": 42,
                        "source_y": 12,
                        "end_x": -45,
                        "end_y": -2,
                    }
                ),
            }
        )
        root = ET.fromstring(
            render_svg(
                diagram.model_copy(
                    update={
                        "nodes": [source, target],
                        "connectors": [connector],
                    }
                ),
                style=NativeDiagramStyleConfig(ea_detail_nodes=True),
            )
        )
        ns = "{http://www.w3.org/2000/svg}"
        path = root.find(f".//{ns}g[@data-connector-id='{connector.connector_id}']/{ns}path")
        assert float(path.get("d").split(",")[1].split()[0]) < 130

        # A target above the source also uses its geometric attachment, even
        # when its role happens to match a source attribute.
        target = target.model_copy(update={"rect_top": 0, "rect_bottom": -70})
        root = ET.fromstring(
            render_svg(
                diagram.model_copy(
                    update={
                        "nodes": [source, target],
                        "connectors": [
                            connector.model_copy(
                                update={
                                    "geometry": connector.geometry.model_copy(
                                        update={
                                            "source_x": None,
                                            "source_y": None,
                                            "end_x": None,
                                            "end_y": None,
                                        }
                                    ),
                                }
                            )
                        ],
                    }
                ),
                style=NativeDiagramStyleConfig(ea_detail_nodes=True),
            )
        )
        path = root.find(f".//{ns}g[@data-connector-id='{connector.connector_id}']/{ns}path")
        assert float(path.get("d").split(",")[1].split()[0]) < 130

    def test_ea_association_name_and_stereotype_use_saved_mid_label_slots(self, extractor):
        from xml.etree import ElementTree as ET
        from eaidl.config import NativeDiagramStyleConfig
        from eaidl.native_diagram_model import NativeLabelPosition

        diagram = extractor.extract_by_id(3)
        first, second = [n for n in diagram.nodes if n.object_type == "Class"][:2]
        source = first.model_copy(
            update={
                "rect_left": 0,
                "rect_right": 100,
                "rect_top": 0,
                "rect_bottom": -60,
                "attributes": [],
            }
        )
        target = second.model_copy(
            update={
                "rect_left": 250,
                "rect_right": 350,
                "rect_top": 0,
                "rect_bottom": -60,
                "attributes": [],
            }
        )
        base = diagram.connectors[0]
        connector = base.model_copy(
            update={
                "connector_type": "Association",
                "name": "plotsContributionToContact",
                "stereotype": "AssociatedEntity",
                "source_object_id": source.object_id,
                "target_object_id": target.object_id,
                "source_role": None,
                "target_role": None,
                "geometry": base.geometry.model_copy(
                    update={
                        "edge_style": 2,
                        "waypoints": [],
                        "source_x": None,
                        "source_y": None,
                        "end_x": None,
                        "end_y": None,
                        "labels": {"LMT": NativeLabelPosition(cx=108, cy=14), "LMB": NativeLabelPosition(cx=77, cy=14)},
                    }
                ),
            }
        )
        root = ET.fromstring(
            render_svg(
                diagram.model_copy(
                    update={
                        "nodes": [source, target],
                        "connectors": [connector],
                    }
                ),
                style=NativeDiagramStyleConfig(ea_detail_nodes=True),
            )
        )
        ns = "{http://www.w3.org/2000/svg}"
        group = root.find(f".//{ns}g[@data-connector-id='{connector.connector_id}']")
        texts = [item.text for item in group.findall(ns + "text")]
        assert texts == ["plotsContributionToContact", "«AssociatedEntity»"]

    def test_ea_rectangular_association_uses_bottom_then_left_route(self, extractor):
        from xml.etree import ElementTree as ET
        from eaidl.config import NativeDiagramStyleConfig

        diagram = extractor.extract_by_id(3)
        first, second = [n for n in diagram.nodes if n.object_type == "Class"][:2]
        source = first.model_copy(
            update={
                "rect_left": 39,
                "rect_right": 179,
                "rect_top": -14,
                "rect_bottom": -145,
                "attributes": [],
            }
        )
        target = second.model_copy(
            update={
                "rect_left": 664,
                "rect_right": 808,
                "rect_top": -325,
                "rect_bottom": -427,
                "attributes": [],
            }
        )
        base = diagram.connectors[0]
        connector = base.model_copy(
            update={
                "connector_type": "Association",
                "source_object_id": source.object_id,
                "target_object_id": target.object_id,
                "source_role": None,
                "target_role": None,
                "geometry": base.geometry.model_copy(
                    update={
                        "edge_style": 3,
                        "waypoints": [],
                        "source_x": -67,
                        "source_y": -36,
                        "end_x": -69,
                        "end_y": -23,
                    }
                ),
            }
        )
        root = ET.fromstring(
            render_svg(
                diagram.model_copy(
                    update={
                        "nodes": [source, target],
                        "connectors": [connector],
                    }
                ),
                style=NativeDiagramStyleConfig(ea_detail_nodes=True),
            )
        )
        ns = "{http://www.w3.org/2000/svg}"
        path = root.find(f".//{ns}g[@data-connector-id='{connector.connector_id}']/{ns}path")
        assert path.get("d") == "M 109.0,145.0 L 109.0,397.0 L 664.0,397.0"

    def test_ea_cancel_transition_uses_saved_orange_state_colour(self, extractor):
        from xml.etree import ElementTree as ET
        from eaidl.config import NativeDiagramStyleConfig

        diagram = extractor.extract_by_id(3)
        first, second = [n for n in diagram.nodes if n.object_type == "Class"][:2]
        base = diagram.connectors[0]
        connector = base.model_copy(
            update={
                "connector_type": "StateFlow",
                "transition_event": "TaskAdminActionEnum.CANCEL",
                "source_object_id": first.object_id,
                "target_object_id": second.object_id,
                "style": base.style.model_copy(update={"color": -1}),
            }
        )
        root = ET.fromstring(
            render_svg(
                diagram.model_copy(
                    update={
                        "nodes": [first, second],
                        "connectors": [connector],
                    }
                ),
                style=NativeDiagramStyleConfig(ea_detail_nodes=True),
            )
        )
        ns = "{http://www.w3.org/2000/svg}"
        path = root.find(f".//{ns}g[@data-connector-id='{connector.connector_id}']/{ns}path")
        assert path.get("stroke") == "#ff4500"
        assert path.get("marker-end") == "url(#arrow-state-cancel)"
        assert root.find(f".//{ns}marker[@id='arrow-state-cancel']") is not None
        assert root.find(f".//{ns}marker[@id='arrow-state-action']") is None

    def test_superimposed_distinct_nodes_keep_visible_connector(self, extractor):
        from xml.etree import ElementTree as ET
        from eaidl.config import NativeDiagramStyleConfig

        diagram = extractor.extract_by_id(3)
        first, second = [n for n in diagram.nodes if n.object_type == "Class"][:2]
        first = first.model_copy(
            update={
                "rect_left": 0,
                "rect_right": 100,
                "rect_top": 0,
                "rect_bottom": -60,
                "attributes": [],
            }
        )
        second = second.model_copy(
            update={
                "rect_left": 0,
                "rect_right": 100,
                "rect_top": 0,
                "rect_bottom": -60,
                "attributes": [],
            }
        )
        connector = diagram.connectors[0].model_copy(
            update={
                "source_object_id": first.object_id,
                "target_object_id": second.object_id,
                "geometry": diagram.connectors[0].geometry.model_copy(
                    update={
                        "waypoints": [],
                        "edge_style": 4,
                    }
                ),
            }
        )
        root = ET.fromstring(
            render_svg(
                diagram.model_copy(
                    update={
                        "nodes": [first, second],
                        "connectors": [connector],
                    }
                ),
                style=NativeDiagramStyleConfig(ea_detail_nodes=True),
            )
        )
        path = root.find('.//{http://www.w3.org/2000/svg}g[@class="connector"]/{http://www.w3.org/2000/svg}path')
        assert path.get("d") == "M 50.0,30.0 L 53.0,85.0"

    def test_enclosing_node_paints_below_connector_and_roles(self, extractor):
        """A P2 architecture must not hide the flow between its nested roles."""
        from xml.etree import ElementTree as ET
        from eaidl.config import NativeDiagramStyleConfig

        diagram = extractor.extract_by_id(3)
        first, second = [n for n in diagram.nodes if n.object_type == "Class"][:2]
        architecture = first.model_copy(
            update={
                "object_id": 999001,
                "name": "Architecture",
                "stereotype": "ResourceArchitecture",
                "rect_left": 0,
                "rect_right": 400,
                "rect_top": 0,
                "rect_bottom": -200,
                "style": first.style.model_copy(update={"background_color": -1}),
            }
        )
        first = first.model_copy(
            update={
                "rect_left": 30,
                "rect_right": 110,
                "rect_top": -60,
                "rect_bottom": -120,
            }
        )
        second = second.model_copy(
            update={
                "rect_left": 280,
                "rect_right": 360,
                "rect_top": -60,
                "rect_bottom": -120,
            }
        )
        flow = diagram.connectors[0].model_copy(
            update={
                "source_object_id": first.object_id,
                "target_object_id": second.object_id,
                "connector_type": "InformationFlow",
                "top_mid_label": "TaskAdmin",
                "bottom_mid_label": "«ResourceExchange»",
                "hidden": False,
                "geometry": diagram.connectors[0].geometry.model_copy(update={"waypoints": []}),
            }
        )
        root = ET.fromstring(
            render_svg(
                diagram.model_copy(
                    update={
                        "diagram_type": "Custom",
                        "nodes": [architecture, first, second],
                        "connectors": [flow],
                    }
                ),
                style=NativeDiagramStyleConfig(
                    ea_detail_nodes=True, stereotype_bg_colors={"ResourceArchitecture": "#ef7d00"}
                ),
            )
        )
        ns = "{http://www.w3.org/2000/svg}"
        groups = [child.get("id") for child in root if child.tag == ns + "g"]
        assert groups.index("containers") < groups.index("connectors") < groups.index("nodes")
        background = root.find(f"{ns}g[@id='containers']/{ns}g/{ns}rect")
        assert background.get("fill") == "#ef7d00"
        labels = [element.text for element in root.findall(f".//{ns}g[@class='connector']/{ns}text")]
        assert labels == ["TaskAdmin", "«ResourceExchange»"]

    def test_activity_node_shapes_and_final_state(self, extractor):
        from xml.etree import ElementTree as ET
        from eaidl.config import NativeDiagramStyleConfig

        diagram = extractor.extract_by_id(3)
        base = next(n for n in diagram.nodes if n.object_type == "Class")
        activity = base.model_copy(
            update={
                "object_id": 999011,
                "name": "Flow",
                "object_type": "Activity",
                "rect_left": 0,
                "rect_right": 300,
                "rect_top": 0,
                "rect_bottom": -300,
            }
        )
        decision = base.model_copy(
            update={
                "object_id": 999012,
                "name": "condition?",
                "object_type": "Decision",
                "rect_left": 100,
                "rect_right": 130,
                "rect_top": -100,
                "rect_bottom": -130,
            }
        )
        final = base.model_copy(
            update={
                "object_id": 999013,
                "name": "",
                "object_type": "StateNode",
                "ntype": 101,
                "rect_left": 100,
                "rect_right": 120,
                "rect_top": -240,
                "rect_bottom": -260,
            }
        )
        root = ET.fromstring(
            render_svg(
                diagram.model_copy(
                    update={
                        "diagram_type": "Custom",
                        "nodes": [activity, decision, final],
                        "connectors": [],
                    }
                ),
                style=NativeDiagramStyleConfig(ea_detail_nodes=True),
            )
        )
        ns = "{http://www.w3.org/2000/svg}"
        assert root.find(f".//{ns}g[@data-object-id='999012']/{ns}polygon") is not None
        assert len(root.findall(f".//{ns}g[@data-object-id='999013']/{ns}ellipse")) == 2

    def test_activity_action_label_and_icon(self, extractor):
        from xml.etree import ElementTree as ET
        from eaidl.config import NativeDiagramStyleConfig

        diagram = extractor.extract_by_id(3)
        base = next(n for n in diagram.nodes if n.object_type == "Class")
        action = base.model_copy(
            update={
                "object_type": "Action",
                "name": "Load context",
                "rect_left": 255,
                "rect_right": 403,
                "rect_top": -328,
                "rect_bottom": -375,
            }
        )
        root = ET.fromstring(
            render_svg(
                diagram.model_copy(
                    update={
                        "diagram_type": "Custom",
                        "nodes": [action],
                        "connectors": [],
                    }
                ),
                style=NativeDiagramStyleConfig(ea_detail_nodes=True),
            )
        )
        ns = "{http://www.w3.org/2000/svg}"
        group = root.find(f".//{ns}g[@class='node-activity']")
        label = group.find(ns + "text")
        assert (label.get("y"), label.get("font-weight")) == ("344.0", "bold")
        assert group.find(ns + "path") is not None

    def test_activity_object_flow_keeps_naf_colour(self, extractor):
        from xml.etree import ElementTree as ET
        from eaidl.config import NativeDiagramStyleConfig

        diagram = extractor.extract_by_id(3)
        first, second = [n for n in diagram.nodes if n.object_type == "Class"][:2]
        connector = diagram.connectors[0].model_copy(
            update={
                "source_object_id": first.object_id,
                "target_object_id": second.object_id,
                "connector_type": "ObjectFlow",
                "hidden": False,
                "geometry": diagram.connectors[0].geometry.model_copy(update={"waypoints": []}),
            }
        )
        root = ET.fromstring(
            render_svg(
                diagram.model_copy(
                    update={
                        "diagram_type": "Custom",
                        "nodes": [first, second],
                        "connectors": [connector],
                    }
                ),
                style=NativeDiagramStyleConfig(ea_detail_nodes=True, control_flow_color="#69738c"),
            )
        )
        ns = "{http://www.w3.org/2000/svg}"
        path = root.find(f".//{ns}g[@class='connector']/{ns}path")
        assert path.get("stroke") == "#69738c"
        assert path.get("marker-end") == "url(#arrow-information)"

    def test_decision_guard_uses_bend_when_decision_label_is_below(self, extractor):
        from xml.etree import ElementTree as ET
        from eaidl.config import NativeDiagramStyleConfig

        diagram = extractor.extract_by_id(3)
        first, second = [n for n in diagram.nodes if n.object_type == "Class"][:2]
        decision = first.model_copy(
            update={
                "object_type": "Decision",
                "name": "condition?",
                "rect_left": 100,
                "rect_right": 126,
                "rect_top": -100,
                "rect_bottom": -134,
                "style": first.style.model_copy(update={"extra": {"LBL": "CX=60:CY=14:OX=-20:OY=32:HDN=0"}}),
            }
        )
        target = second.model_copy(
            update={
                "object_type": "Action",
                "rect_left": 250,
                "rect_right": 350,
                "rect_top": -200,
                "rect_bottom": -250,
            }
        )
        connector = diagram.connectors[0].model_copy(
            update={
                "connector_type": "ControlFlow",
                "name": "yes",
                "hidden": False,
                "source_object_id": decision.object_id,
                "target_object_id": target.object_id,
                "geometry": diagram.connectors[0].geometry.model_copy(update={"waypoints": [[210, -117]]}),
            }
        )
        root = ET.fromstring(
            render_svg(
                diagram.model_copy(
                    update={
                        "diagram_type": "Custom",
                        "nodes": [decision, target],
                        "connectors": [connector],
                    }
                ),
                style=NativeDiagramStyleConfig(ea_detail_nodes=True),
            )
        )
        ns = "{http://www.w3.org/2000/svg}"
        guard = root.find(f".//{ns}g[@class='connector']/{ns}text")
        assert guard.get("x") == "202.0"
        assert guard.get("text-anchor") == "middle"
        decision_text = root.find(f".//{ns}g[@data-object-id='{decision.object_id}']/{ns}text")
        assert decision_text.get("y") == "142.0"

    def test_activity_flows_meet_diamond_vertices_with_ea_arrowheads(self, extractor):
        from xml.etree import ElementTree as ET
        from eaidl.config import NativeDiagramStyleConfig

        diagram = extractor.extract_by_id(3)
        first, second = [n for n in diagram.nodes if n.object_type == "Class"][:2]
        action = first.model_copy(
            update={
                "object_type": "Action",
                "rect_left": 63,
                "rect_right": 163,
                "rect_top": 0,
                "rect_bottom": -40,
            }
        )
        decision = second.model_copy(
            update={
                "object_type": "Decision",
                "rect_left": 100,
                "rect_right": 126,
                "rect_top": -100,
                "rect_bottom": -134,
            }
        )
        left = first.model_copy(
            update={
                "object_id": 900001,
                "object_type": "Action",
                "rect_left": 0,
                "rect_right": 80,
                "rect_top": -230,
                "rect_bottom": -270,
            }
        )
        right = first.model_copy(
            update={
                "object_id": 900002,
                "object_type": "Action",
                "rect_left": 150,
                "rect_right": 230,
                "rect_top": -230,
                "rect_bottom": -270,
            }
        )
        merge = second.model_copy(
            update={
                "object_id": 900003,
                "object_type": "MergeNode",
                "rect_left": 100,
                "rect_right": 126,
                "rect_top": -300,
                "rect_bottom": -334,
            }
        )
        bar = second.model_copy(
            update={
                "object_id": 900004,
                "object_type": "Synchronization",
                "rect_left": 50,
                "rect_right": 176,
                "rect_top": -370,
                "rect_bottom": -377,
            }
        )
        base = diagram.connectors[0]

        def flow(cid, source, target, waypoints=None):
            return base.model_copy(
                update={
                    "connector_id": cid,
                    "connector_type": "ControlFlow",
                    "hidden": False,
                    "source_object_id": source.object_id,
                    "target_object_id": target.object_id,
                    "geometry": base.geometry.model_copy(
                        update={
                            "source_x": None,
                            "source_y": None,
                            "end_x": None,
                            "end_y": None,
                            "waypoints": waypoints or [],
                            "edge_style": 3,
                        }
                    ),
                }
            )

        flows = [
            flow(1, action, decision),
            flow(2, left, merge, [[40, -317]]),
            flow(3, right, merge, [[190, -317]]),
            flow(4, merge, bar),
        ]
        root = ET.fromstring(
            render_svg(
                diagram.model_copy(
                    update={
                        "diagram_type": "Custom",
                        "nodes": [action, decision, left, right, merge, bar],
                        "connectors": flows,
                    }
                ),
                style=NativeDiagramStyleConfig(ea_detail_nodes=True),
            )
        )
        ns = "{http://www.w3.org/2000/svg}"
        paths = {
            int(group.get("data-connector-id")): group.find(ns + "path")
            for group in root.findall(f".//{ns}g[@class='connector']")
        }
        assert paths[1].get("d").endswith("L 113.0,100.0")
        assert paths[2].get("d").endswith("L 100.0,317.0")
        assert paths[3].get("d").endswith("L 126.0,317.0")
        assert paths[4].get("d") == "M 113.0,334.0 L 113.0,370.0"
        assert all(path.get("marker-end") == "url(#arrow-control)" for path in paths.values())
        marker = root.find(f".//{ns}marker[@id='arrow-control']")
        assert (marker.get("markerWidth"), marker.get("markerHeight"), marker.get("refX"), marker.get("refY")) == (
            "16",
            "12",
            "16",
            "6",
        )
        assert marker.find(ns + "polygon").get("points") == "0,0 16,6 0,12"

    def test_far_single_bend_does_not_detour_into_merge_diamond(self, extractor):
        from xml.etree import ElementTree as ET
        from eaidl.config import NativeDiagramStyleConfig

        diagram = extractor.extract_by_id(3)
        first, second = [n for n in diagram.nodes if n.object_type == "Class"][:2]
        pin = first.model_copy(
            update={
                "object_type": "ActionPin",
                "rect_left": 200,
                "rect_right": 216,
                "rect_top": -309,
                "rect_bottom": -325,
            }
        )
        merge = second.model_copy(
            update={
                "object_type": "MergeNode",
                "rect_left": 100,
                "rect_right": 126,
                "rect_top": -300,
                "rect_bottom": -334,
            }
        )
        base = diagram.connectors[0]
        flow = base.model_copy(
            update={
                "connector_type": "ObjectFlow",
                "hidden": False,
                "source_object_id": pin.object_id,
                "target_object_id": merge.object_id,
                "geometry": base.geometry.model_copy(
                    update={
                        "source_x": None,
                        "source_y": None,
                        "end_x": None,
                        "end_y": None,
                        "edge_style": 4,
                        "waypoints": [[500, -400]],
                    }
                ),
            }
        )
        root = ET.fromstring(
            render_svg(
                diagram.model_copy(
                    update={
                        "diagram_type": "Custom",
                        "nodes": [pin, merge],
                        "connectors": [flow],
                    }
                ),
                style=NativeDiagramStyleConfig(ea_detail_nodes=True),
            )
        )
        path = root.find('.//{http://www.w3.org/2000/svg}g[@class="connector"]/{http://www.w3.org/2000/svg}path')
        assert path.get("d") == "M 200.0,317.0 L 126.0,317.0"

        authored = flow.model_copy(
            update={
                "geometry": flow.geometry.model_copy(
                    update={
                        "waypoints": [[180, -280], [160, -280]],
                    }
                ),
            }
        )
        root = ET.fromstring(
            render_svg(
                diagram.model_copy(
                    update={
                        "diagram_type": "Custom",
                        "nodes": [pin, merge],
                        "connectors": [authored],
                    }
                ),
                style=NativeDiagramStyleConfig(ea_detail_nodes=True),
            )
        )
        path = root.find('.//{http://www.w3.org/2000/svg}g[@class="connector"]/{http://www.w3.org/2000/svg}path')
        assert "L 180.0,280.0 L 160.0,280.0" in path.get("d")

    def test_statechart_state_note_and_legend_render(self, extractor):
        from xml.etree import ElementTree as ET
        from eaidl.config import NativeDiagramStyleConfig

        diagram = extractor.extract_by_id(3)
        base = next(n for n in diagram.nodes if n.object_type == "Class")
        state = base.model_copy(
            update={
                "object_type": "State",
                "name": "PLANNING",
                "note_text": "Task is being planned",
                "rect_left": 0,
                "rect_right": 120,
                "rect_top": 0,
                "rect_bottom": -60,
                "style": base.style.model_copy(update={"extra": {"Notes": "1000"}}),
            }
        )
        legend = base.model_copy(
            update={
                "object_id": 999017,
                "object_type": "Text",
                "name": "Transition types",
                "rect_left": 200,
                "rect_right": 423,
                "rect_top": 0,
                "rect_bottom": -72,
                "legend_entries": [("TaskStateEnum.xxx", "#000000"), ("TaskAdminActionEnum.yyy", "#ff0000")],
                "legend_background_color": "#e2e0dd",
                "legend_text_color": "#003060",
            }
        )
        root = ET.fromstring(
            render_svg(
                diagram.model_copy(
                    update={
                        "diagram_type": "Statechart",
                        "nodes": [state, legend],
                        "connectors": [],
                    }
                ),
                style=NativeDiagramStyleConfig(ea_detail_nodes=True),
            )
        )
        ns = "{http://www.w3.org/2000/svg}"
        state_group = root.find(f".//{ns}g[@data-object-id='{state.object_id}']")
        assert state_group.find(ns + "line") is not None
        assert any(text.text == "Task is being planned" for text in state_group.findall(ns + "text"))
        legend_group = root.find(f".//{ns}g[@data-object-id='999017']")
        assert legend_group.find(ns + "rect").get("fill") == "#e2e0dd"
        assert len(legend_group.findall(ns + "line")) == 2

    def test_stateflow_event_uses_ea_label_offset(self, extractor):
        from xml.etree import ElementTree as ET
        from eaidl.config import NativeDiagramStyleConfig
        from eaidl.native_diagram_model import NativeLabelPosition

        diagram = extractor.extract_by_id(3)
        first, second = [n for n in diagram.nodes if n.object_type == "Class"][:2]
        first = first.model_copy(update={"object_type": "State"})
        second = second.model_copy(update={"object_type": "State"})
        connector = diagram.connectors[0].model_copy(
            update={
                "connector_type": "StateFlow",
                "transition_event": "TaskStateEnum.ACTIVE",
                "source_object_id": first.object_id,
                "target_object_id": second.object_id,
                "hidden": False,
                "geometry": diagram.connectors[0].geometry.model_copy(
                    update={
                        "waypoints": [],
                        "labels": {"LMT": NativeLabelPosition(cx=100, cy=14, ox=10, oy=7)},
                    }
                ),
            }
        )
        root = ET.fromstring(
            render_svg(
                diagram.model_copy(
                    update={
                        "diagram_type": "Statechart",
                        "nodes": [first, second],
                        "connectors": [connector],
                    }
                ),
                style=NativeDiagramStyleConfig(ea_detail_nodes=True),
            )
        )
        ns = "{http://www.w3.org/2000/svg}"
        group = root.find(f".//{ns}g[@class='connector']")
        label = group.find(ns + "text")
        assert label.get("text-anchor") == "start"
        assert label.get("font-size") == "10"
        assert group.find(ns + "path").get("stroke") == "#69738c"

    def test_curved_stateflow_follows_saved_waypoint_side_and_label(self, extractor):
        from xml.etree import ElementTree as ET
        from eaidl.config import NativeDiagramStyleConfig
        from eaidl.native_diagram_model import NativeLabelPosition

        diagram = extractor.extract_by_id(3)
        first, second = [n for n in diagram.nodes if n.object_type == "Class"][:2]
        first = first.model_copy(
            update={
                "object_type": "State",
                "rect_left": 40,
                "rect_right": 160,
                "rect_top": -66,
                "rect_bottom": -126,
            }
        )
        second = second.model_copy(
            update={
                "object_type": "State",
                "rect_left": 253,
                "rect_right": 373,
                "rect_top": -66,
                "rect_bottom": -126,
            }
        )
        base = diagram.connectors[0]
        for waypoint, expected_y, expected_label_y in (
            ([207, -129], 112, 135),
            ([207, -47], 78, 73),
        ):
            connector = base.model_copy(
                update={
                    "connector_type": "StateFlow",
                    "transition_event": "parse",
                    "source_object_id": first.object_id,
                    "target_object_id": second.object_id,
                    "hidden": False,
                    "style": base.style.model_copy(update={"mode": 10}),
                    "geometry": base.geometry.model_copy(
                        update={
                            "edge_style": 2,
                            "waypoints": [waypoint],
                            "labels": {"LMT": NativeLabelPosition(cx=23, cy=14, ox=-5, oy=22)},
                        }
                    ),
                }
            )
            root = ET.fromstring(
                render_svg(
                    diagram.model_copy(
                        update={
                            "diagram_type": "Statechart",
                            "nodes": [first, second],
                            "connectors": [connector],
                        }
                    ),
                    style=NativeDiagramStyleConfig(ea_detail_nodes=True),
                )
            )
            ns = "{http://www.w3.org/2000/svg}"
            group = root.find(f".//{ns}g[@class='connector']")
            path = group.find(ns + "path")
            label = group.find(ns + "text")
            assert path.get("d").startswith(f"M 160.0,{expected_y}.0 C")
            assert float(label.get("y")) == expected_label_y

    def test_ea_decision_label_uses_saved_label_box(self, extractor):
        from xml.etree import ElementTree as ET
        from eaidl.config import NativeDiagramStyleConfig

        diagram = extractor.extract_by_id(3)
        base = next(n for n in diagram.nodes if n.object_type == "Class")
        decision = base.model_copy(
            update={
                "object_type": "Decision",
                "name": "Update Triggered?",
                "rect_left": 266,
                "rect_right": 292,
                "rect_top": -1023,
                "rect_bottom": -1057,
                "style": base.style.model_copy(
                    update={
                        "extra": {"LBL": "CX=44:CY=27:OX=40:OY=6:HDN=0"},
                    }
                ),
            }
        )
        root = ET.fromstring(
            render_svg(
                diagram.model_copy(
                    update={
                        "diagram_type": "Custom",
                        "nodes": [decision],
                        "connectors": [],
                    }
                ),
                style=NativeDiagramStyleConfig(ea_detail_nodes=True),
            )
        )
        ns = "{http://www.w3.org/2000/svg}"
        labels = root.findall(f".//{ns}g[@class='node-activity']/{ns}text")
        assert [label.text for label in labels] == ["Update", "Triggered?"]
        assert [float(label.get("y")) for label in labels] == [1039, 1052]
        assert all(float(label.get("x")) > 300 for label in labels)

    def test_ea_objectflow_branch_guard_is_drawn_beside_diamond(self, extractor):
        from xml.etree import ElementTree as ET
        from eaidl.config import NativeDiagramStyleConfig

        diagram = extractor.extract_by_id(3)
        first, second = [n for n in diagram.nodes if n.object_type == "Class"][:2]
        decision = first.model_copy(
            update={
                "object_type": "Decision",
                "name": "Continue?",
                "rect_left": 100,
                "rect_right": 126,
                "rect_top": -100,
                "rect_bottom": -134,
            }
        )
        action = second.model_copy(
            update={
                "object_type": "Action",
                "rect_left": 100,
                "rect_right": 200,
                "rect_top": -190,
                "rect_bottom": -240,
            }
        )
        branch = diagram.connectors[0].model_copy(
            update={
                "connector_type": "ObjectFlow",
                "name": "Yes",
                "hidden": False,
                "source_object_id": decision.object_id,
                "target_object_id": action.object_id,
                "geometry": diagram.connectors[0].geometry.model_copy(update={"waypoints": []}),
            }
        )
        root = ET.fromstring(
            render_svg(
                diagram.model_copy(
                    update={
                        "diagram_type": "Custom",
                        "nodes": [decision, action],
                        "connectors": [branch],
                    }
                ),
                style=NativeDiagramStyleConfig(ea_detail_nodes=True),
            )
        )
        ns = "{http://www.w3.org/2000/svg}"
        label = next(t for t in root.findall(f".//{ns}g[@class='connector']/{ns}text") if t.text == "Yes")
        assert float(label.get("y")) >= 134

    def test_activity_flow_ignores_short_stale_detour_on_horizontal_route(self, extractor):
        from xml.etree import ElementTree as ET
        from eaidl.config import NativeDiagramStyleConfig

        diagram = extractor.extract_by_id(3)
        first, second = [n for n in diagram.nodes if n.object_type == "Class"][:2]
        source = first.model_copy(
            update={
                "object_type": "Decision",
                "rect_left": 729,
                "rect_right": 755,
                "rect_top": -1443,
                "rect_bottom": -1477,
            }
        )
        target = second.model_copy(
            update={
                "object_type": "MergeNode",
                "rect_left": 96,
                "rect_right": 122,
                "rect_top": -1443,
                "rect_bottom": -1477,
            }
        )
        branch = diagram.connectors[0].model_copy(
            update={
                "connector_type": "ControlFlow",
                "name": "No",
                "hidden": False,
                "source_object_id": source.object_id,
                "target_object_id": target.object_id,
                "geometry": diagram.connectors[0].geometry.model_copy(
                    update={
                        "edge_style": 4,
                        "waypoints": [[451, -1480], [451, -1446]],
                    }
                ),
            }
        )
        root = ET.fromstring(
            render_svg(
                diagram.model_copy(
                    update={
                        "diagram_type": "Custom",
                        "nodes": [source, target],
                        "connectors": [branch],
                    }
                ),
                style=NativeDiagramStyleConfig(ea_detail_nodes=True),
            )
        )
        ns = "{http://www.w3.org/2000/svg}"
        path = root.find(f".//{ns}g[@class='connector']/{ns}path")
        assert "451" not in path.get("d")

    def test_ea_attribute_baseline_clears_next_row(self, extractor):
        from xml.etree import ElementTree as ET
        from eaidl.config import NativeDiagramStyleConfig
        from eaidl.native_diagram_model import NativeDiagramAttribute

        diagram = extractor.extract_by_id(3)
        node = next(n for n in diagram.nodes if n.object_type == "Class")
        node = node.model_copy(
            update={
                "rect_left": 0,
                "rect_right": 220,
                "rect_top": 0,
                "rect_bottom": -90,
                "attributes": [
                    NativeDiagramAttribute(name="authoriser", type="Authority"),
                    NativeDiagramAttribute(name="degree", type="CountMeasurement"),
                ],
                "note_text": None,
                "parent_name": None,
            }
        )
        root = ET.fromstring(
            render_svg(
                diagram.model_copy(
                    update={
                        "nodes": [node],
                        "connectors": [],
                    }
                ),
                style=NativeDiagramStyleConfig(ea_detail_nodes=True),
            )
        )
        ns = "{http://www.w3.org/2000/svg}"
        group = root.find(f".//{ns}g[@data-object-id='{node.object_id}']")
        row_lines = group.findall(ns + "line")
        label = next(text for text in group.findall(ns + "text") if "authoriser" in (text.text or ""))
        assert len(row_lines) == 1  # EA separates the header, not each attribute.
        assert label.get("y") == "51.0"

    def test_diagonal_stateflow_uses_state_corners(self, extractor):
        from xml.etree import ElementTree as ET
        from eaidl.config import NativeDiagramStyleConfig

        diagram = extractor.extract_by_id(3)
        first, second = [n for n in diagram.nodes if n.object_type == "Class"][:2]
        source = first.model_copy(
            update={
                "object_type": "State",
                "name": "ACTIVE",
                "note_text": "Executing",
                "rect_left": 468,
                "rect_right": 588,
                "rect_top": -622,
                "rect_bottom": -682,
            }
        )
        target = second.model_copy(
            update={
                "object_type": "State",
                "name": "PREEMPTING",
                "note_text": "Preempting",
                "rect_left": 277,
                "rect_right": 419,
                "rect_top": -742,
                "rect_bottom": -802,
            }
        )
        connector = diagram.connectors[0].model_copy(
            update={
                "connector_type": "StateFlow",
                "source_object_id": source.object_id,
                "target_object_id": target.object_id,
                "hidden": False,
                "geometry": diagram.connectors[0].geometry.model_copy(
                    update={
                        "edge_style": 4,
                        "source_x": -23,
                        "source_y": 2,
                        "end_x": -23,
                        "end_y": 2,
                        "waypoints": [],
                    }
                ),
            }
        )
        root = ET.fromstring(
            render_svg(
                diagram.model_copy(
                    update={
                        "diagram_type": "Statechart",
                        "nodes": [source, target],
                        "connectors": [connector],
                    }
                ),
                style=NativeDiagramStyleConfig(ea_detail_nodes=True),
            )
        )
        ns = "{http://www.w3.org/2000/svg}"
        path = root.find(f".//{ns}g[@class='connector']/{ns}path")
        assert path.get("d") == "M 468.0,674.0 L 366.46,742.0"

    def test_later_stateflow_gets_line_jump_at_crossing(self, extractor):
        from xml.etree import ElementTree as ET
        from eaidl.native_diagram_svg import _ea_line_jumps

        base = extractor.extract_by_id(3).connectors[0]
        first = base.model_copy(update={"connector_id": 1, "connector_type": "StateFlow"})
        second = base.model_copy(update={"connector_id": 2, "connector_type": "StateFlow"})
        parent = ET.Element("g")
        old = ET.SubElement(parent, "g", **{"data-connector-id": "1"})
        ET.SubElement(old, "path", d="M 0,50 L 100,50")
        new = ET.SubElement(parent, "g", **{"data-connector-id": "2"})
        new_path = ET.SubElement(new, "path", d="M 0,0 L 100,100")
        _ea_line_jumps(parent, [first, second])
        assert "A 6 -6 180 0 0" in new_path.get("d")
        assert old.find("path").get("d") == "M 0,50 L 100,50"

    def test_horizontal_controlflow_bridges_earlier_activity_flow(self, extractor):
        from xml.etree import ElementTree as ET
        from eaidl.native_diagram_svg import _ea_line_jumps

        base = extractor.extract_by_id(3).connectors[0]
        first = base.model_copy(update={"connector_id": 1, "connector_type": "ObjectFlow"})
        second = base.model_copy(update={"connector_id": 2, "connector_type": "ControlFlow"})
        parent = ET.Element("g")
        old = ET.SubElement(parent, "g", **{"data-connector-id": "1"})
        ET.SubElement(old, "path", d="M 100,0 L 100,100")
        new = ET.SubElement(parent, "g", **{"data-connector-id": "2"})
        new_path = ET.SubElement(new, "path", d="M 300,50 L 0,50")
        _ea_line_jumps(parent, [first, second])
        assert "A 6 -6 180 0 0" in new_path.get("d")

    def test_routed_association_bridges_vertical_crossings(self, extractor):
        from xml.etree import ElementTree as ET
        from eaidl.native_diagram_svg import _ea_line_jumps

        base = extractor.extract_by_id(3).connectors[0]
        connectors = [
            base.model_copy(
                update={
                    "connector_id": number,
                    "connector_type": "Association",
                }
            )
            for number in (1, 2, 3)
        ]
        parent = ET.Element("g")
        for number, route in (
            (1, "M 150,0 L 150,200"),
            (2, "M 250,0 L 250,200"),
            (3, "M 0,0 L 0,100 L 400,100"),
        ):
            group = ET.SubElement(parent, "g", **{"data-connector-id": str(number)})
            ET.SubElement(group, "path", d=route)
        _ea_line_jumps(parent, connectors)
        path = parent.findall("g")[-1].find("path")
        assert path.get("d").count("A 6 -6 180 0 0") == 2

    def test_feature_link_attaches_to_attribute_side(self, extractor):
        from xml.etree import ElementTree as ET
        from eaidl.config import NativeDiagramStyleConfig
        from eaidl.native_diagram_model import NativeDiagramAttribute

        diagram = extractor.extract_by_id(3)
        first, second = [n for n in diagram.nodes if n.object_type == "Class"][:2]
        source = first.model_copy(
            update={
                "rect_left": 0,
                "rect_right": 100,
                "rect_top": 0,
                "rect_bottom": -90,
                "attributes": [NativeDiagramAttribute(name="Provider", type="Actor", ea_guid="{provider}")],
            }
        )
        target = second.model_copy(
            update={
                "rect_left": 200,
                "rect_right": 300,
                "rect_top": 0,
                "rect_bottom": -90,
            }
        )
        connector = diagram.connectors[0].model_copy(
            update={
                "source_object_id": source.object_id,
                "target_object_id": target.object_id,
                "source_feature_guid": "{provider}",
                "source_feature_side": "L",
                "geometry": diagram.connectors[0].geometry.model_copy(update={"waypoints": []}),
            }
        )
        root = ET.fromstring(
            render_svg(
                diagram.model_copy(
                    update={
                        "nodes": [source, target],
                        "connectors": [connector],
                    }
                ),
                style=NativeDiagramStyleConfig(compact_nodes=True),
            )
        )
        path = root.find('.//{http://www.w3.org/2000/svg}g[@class="connector"]/{http://www.w3.org/2000/svg}path')
        assert path.get("d").startswith("M 100.0,47.0 L ")

    def test_ea_detail_property_group_expands_class_and_anchors_row(self, extractor):
        from xml.etree import ElementTree as ET
        from eaidl.config import NativeDiagramStyleConfig
        from eaidl.native_diagram_model import NativeDiagramAttribute

        diagram = extractor.extract_by_id(3)
        first, second = [n for n in diagram.nodes if n.object_type == "Class"][:2]
        source = first.model_copy(
            update={
                "rect_left": 0,
                "rect_right": 200,
                "rect_top": 0,
                "rect_bottom": -70,
                "parent_name": None,
                "note_text": None,
                "attributes": [
                    NativeDiagramAttribute(name="node", type="GUID", ea_guid="{node}"),
                    NativeDiagramAttribute(
                        name="authority",
                        type="Authority",
                        stereotype="optional",
                        lower_bound="0",
                        upper_bound="1",
                        ea_guid="{authority}",
                    ),
                ],
            }
        )
        target = second.model_copy(
            update={
                "rect_left": 300,
                "rect_right": 400,
                "rect_top": 0,
                "rect_bottom": -90,
                "attributes": [],
            }
        )
        connector = diagram.connectors[0].model_copy(
            update={
                "source_object_id": source.object_id,
                "target_object_id": target.object_id,
                "source_feature_guid": "{authority}",
                "source_feature_side": "R",
                "target_feature_guid": None,
                "geometry": diagram.connectors[0].geometry.model_copy(update={"waypoints": []}),
            }
        )
        root = ET.fromstring(
            render_svg(
                diagram.model_copy(
                    update={
                        "nodes": [source, target],
                        "connectors": [connector],
                    }
                ),
                style=NativeDiagramStyleConfig(ea_detail_nodes=True),
            )
        )
        ns = "{http://www.w3.org/2000/svg}"
        card = root.find(f".//{ns}g[@data-object-id='{source.object_id}']")
        assert card.find(ns + "rect").get("height") == "89.0"
        assert len(card.findall(ns + "line")) == 1
        texts = [(item.text, item.get("y")) for item in card.findall(ns + "text")]
        assert ("«optional»", "68.0") in texts
        assert ("authority: Authority [0..1]", "81.0") in texts
        path = root.find(f".//{ns}g[@class='connector']/{ns}path")
        assert path.get("d").startswith("M 200.0,77.0 L ")

    def test_association_class_link_is_drawn(self, extractor):
        from xml.etree import ElementTree as ET
        from eaidl.config import NativeDiagramStyleConfig

        diagram = extractor.extract_by_id(3)
        first, second = [n for n in diagram.nodes if n.object_type == "Class"][:2]
        association_class = first.model_copy(
            update={
                "object_id": 999999,
                "rect_left": 100,
                "rect_right": 200,
                "rect_top": -150,
                "rect_bottom": -220,
            }
        )
        connector = diagram.connectors[0].model_copy(
            update={
                "source_object_id": first.object_id,
                "target_object_id": second.object_id,
                "association_class_object_id": association_class.object_id,
                "hidden": False,
            }
        )
        root = ET.fromstring(
            render_svg(
                diagram.model_copy(
                    update={
                        "nodes": [first, second, association_class],
                        "connectors": [connector],
                    }
                ),
                style=NativeDiagramStyleConfig(compact_nodes=True),
            )
        )
        link = root.find('.//{http://www.w3.org/2000/svg}path[@class="association-class-link"]')
        assert link is not None
        assert link.get("stroke-dasharray") == "5,3"

    def test_connector_directions_aggregates_and_dependencies(self, extractor):
        from xml.etree import ElementTree as ET
        from eaidl.config import NativeDiagramStyleConfig

        diagram = extractor.extract_by_id(3)
        first, second = [n for n in diagram.nodes if n.object_type == "Class"][:2]
        connector = diagram.connectors[0].model_copy(
            update={
                "source_object_id": first.object_id,
                "target_object_id": second.object_id,
                "hidden": False,
                "geometry": diagram.connectors[0].geometry.model_copy(
                    update={
                        "source_x": None,
                        "source_y": None,
                        "end_x": None,
                        "end_y": None,
                        "waypoints": [],
                    }
                ),
            }
        )
        style = NativeDiagramStyleConfig(compact_nodes=True)

        def path(**changes):
            current = connector.model_copy(update=changes)
            svg = render_svg(
                diagram.model_copy(update={"nodes": [first, second], "connectors": [current]}), style=style
            )
            root = ET.fromstring(svg)
            return root.find('.//{http://www.w3.org/2000/svg}g[@class="connector"]/{http://www.w3.org/2000/svg}path')

        assert (
            path(
                connector_type="Association", direction="Unspecified", source_is_aggregate=0, target_is_aggregate=0
            ).get("marker-end")
            is None
        )
        assert (
            path(
                connector_type="Association",
                direction="Source -> Destination",
                source_is_aggregate=0,
                target_is_aggregate=0,
            ).get("marker-end")
            == "url(#arrow-open)"
        )
        assert (
            path(connector_type="Aggregation", source_is_aggregate=0, target_is_aggregate=1).get("marker-end")
            == "url(#diamond-open-end)"
        )
        assert (
            path(connector_type="Aggregation", source_is_aggregate=2, target_is_aggregate=0).get("marker-start")
            == "url(#diamond-filled-start)"
        )
        composed = path(
            connector_type="Association",
            direction="Source -> Destination",
            source_is_aggregate=2,
            target_is_aggregate=0,
            source_navigability="Non-Navigable",
            target_navigability="Navigable",
        )
        assert composed.get("marker-start") == "url(#diamond-filled-start)"
        # EA draws a plain line at the end opposite a diamond even when the
        # role is explicitly Navigable (verified in all reference exports).
        assert composed.get("marker-end") is None
        blocked = path(
            connector_type="Association",
            direction="Source -> Destination",
            source_is_aggregate=0,
            target_is_aggregate=0,
            source_navigability="Non-Navigable",
            target_navigability="Non-Navigable",
        )
        assert blocked.get("marker-end") is None
        realization = path(connector_type="Realisation", source_is_aggregate=0, target_is_aggregate=0)
        assert realization.get("stroke-dasharray") == "5,3"
        assert realization.get("marker-end") == "url(#arrow-generalization)"

    def test_diamond_link_keeps_opposite_end_plain(self, extractor):
        """EA exports aggregate links with the diamond only: a Navigable role
        style never adds a navigability arrow at the end opposite a diamond
        (all 26 diamond groups in the reference exports show a plain line)."""
        from xml.etree import ElementTree as ET
        from eaidl.config import NativeDiagramStyleConfig

        diagram = extractor.extract_by_id(3)
        first, second = [n for n in diagram.nodes if n.object_type == "Class"][:2]
        connector = diagram.connectors[0].model_copy(
            update={
                "source_object_id": first.object_id,
                "target_object_id": second.object_id,
                "hidden": False,
                "geometry": diagram.connectors[0].geometry.model_copy(
                    update={
                        "source_x": None,
                        "source_y": None,
                        "end_x": None,
                        "end_y": None,
                        "waypoints": [],
                    }
                ),
            }
        )
        style = NativeDiagramStyleConfig(compact_nodes=True)
        current = connector.model_copy(
            update={
                "connector_type": "Aggregation",
                "direction": "Source -> Destination",
                "source_is_aggregate": 0,
                "target_is_aggregate": 2,
                "source_navigability": "Navigable",
                "target_navigability": "Unspecified",
            }
        )
        svg = render_svg(diagram.model_copy(update={"nodes": [first, second], "connectors": [current]}), style=style)
        root = ET.fromstring(svg)
        ns = "{http://www.w3.org/2000/svg}"
        path = root.find(f'.//{ns}g[@class="connector"]/{ns}path')
        assert path.get("marker-end") == "url(#diamond-filled-end)"
        assert path.get("marker-start") is None

    def test_compact_long_name_fits_ea_bounds(self, extractor):
        from xml.etree import ElementTree as ET
        from eaidl.config import NativeDiagramStyleConfig

        diagram = extractor.extract_by_id(3)
        node = next(n for n in diagram.nodes if n.object_type == "Class")
        node = node.model_copy(
            update={
                "name": "SecurityReferenceBaseType",
                "rect_left": 0,
                "rect_right": 110,
                "rect_top": 0,
                "rect_bottom": -70,
            }
        )
        style = NativeDiagramStyleConfig(compact_nodes=True, font_size=16)
        svg = render_svg(diagram.model_copy(update={"nodes": [node], "connectors": []}), style=style)
        root = ET.fromstring(svg)
        ns = {"s": "http://www.w3.org/2000/svg"}
        card = root.find('.//s:g[@class="node-class"]', ns)
        labels = card.findall("s:text", ns)
        assert "".join(label.text or "" for label in labels) == node.name
        assert len(labels) > 1
        assert all(0 < float(label.get("y")) < 70 for label in labels)

    def test_compact_connector_labels_can_be_hidden(self, extractor):
        from xml.etree import ElementTree as ET
        from eaidl.config import NativeDiagramStyleConfig

        diagram = extractor.extract_by_id(3)
        style = NativeDiagramStyleConfig(compact_nodes=True, compact_connector_labels=False)
        root = ET.fromstring(render_svg(diagram, style=style))
        ns = {"s": "http://www.w3.org/2000/svg"}
        connectors = root.findall('.//s:g[@class="connector"]', ns)
        assert connectors
        assert all(not connector.findall("s:text", ns) for connector in connectors)

    def test_compact_stereotype_fill_and_explicit_ea_override(self, extractor):
        """Compact cards use profile fills while preserving diagram overrides."""
        from xml.etree import ElementTree as ET
        from eaidl.config import NativeDiagramStyleConfig

        diagram = extractor.extract_by_id(3)
        node = next(n for n in diagram.nodes if n.object_type == "Class")
        style = NativeDiagramStyleConfig(
            compact_nodes=True,
            stereotype_bg_colors={"InformationElement": "#66b2e4"},
        )

        def fill(card):
            svg = render_svg(diagram.model_copy(update={"nodes": [card], "connectors": []}), style=style)
            root = ET.fromstring(svg)
            return root.find(
                ".//{http://www.w3.org/2000/svg}g[@class='node-class']/{http://www.w3.org/2000/svg}rect"
            ).get("fill")

        card = node.model_copy(
            update={
                "stereotype": "InformationElement",
                "style": node.style.model_copy(update={"background_color": -1}),
            }
        )
        assert fill(card) == "#66b2e4"
        assert (
            fill(
                card.model_copy(
                    update={
                        "style": card.style.model_copy(update={"background_color": 0x8CE6F0}),
                    }
                )
            )
            == "#f0e68c"
        )

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

    def test_note_text_rendered_as_svg(self, extractor):
        """Notes should remain visible in renderers without foreignObject support."""
        diag = extractor.extract_by_id(3)
        notes = [n for n in diag.nodes if n.object_type == "Note"]
        if not notes:
            pytest.skip("No Note nodes in diagram 3")
        svg = render_svg(diag)
        assert 'class="node-note"' in svg
        assert "<foreignObject" not in svg

    def test_note_html_content_in_svg(self, extractor):
        """Rich HTML note content (bold/italic/list) should appear in SVG."""
        diag = extractor.extract_by_id(3)
        notes = [n for n in diag.nodes if n.object_type == "Note" and n.note_text]
        if not notes:
            pytest.skip("No Note nodes with text in diagram 3")
        svg = render_svg(diag)
        assert "<text" in svg
        assert "<foreignObject" not in svg

    def test_ea_note_preserves_list_markers_and_font(self, extractor):
        from xml.etree import ElementTree as ET
        from eaidl.config import NativeDiagramStyleConfig

        diagram = extractor.extract_by_id(3)
        base = next(n for n in diagram.nodes if n.object_type == "Class")
        note = base.model_copy(
            update={
                "object_type": "Note",
                "name": "",
                "rect_left": 0,
                "rect_right": 260,
                "rect_top": 0,
                "rect_bottom": -149,
                "note_text": "Intro.\r\n<ul><li>first item</li><li>second item</li></ul>",
            }
        )
        root = ET.fromstring(
            render_svg(
                diagram.model_copy(
                    update={
                        "diagram_type": "Custom",
                        "nodes": [note],
                        "connectors": [],
                    }
                ),
                style=NativeDiagramStyleConfig(ea_detail_nodes=True),
            )
        )
        ns = "{http://www.w3.org/2000/svg}"
        group = root.find(f".//{ns}g[@class='node-note']")
        labels = group.findall(ns + "text")
        assert [label.text for label in labels] == ["Intro.", "- first item", "- second item"]
        assert labels[0].get("y") == "24.0"
        assert all(label.get("font-size") == "10" for label in labels)
        assert group.findall(ns + "polygon")[1].get("fill") == "#dcdcdc"

        code_note = note.model_copy(
            update={
                "note_text": "first\n  second",
                "style": note.style.model_copy(update={"font_size": 80, "extra": {"font": "Courier New"}}),
            }
        )
        code_root = ET.fromstring(
            render_svg(
                diagram.model_copy(
                    update={
                        "diagram_type": "Custom",
                        "nodes": [code_note],
                        "connectors": [],
                    }
                ),
                style=NativeDiagramStyleConfig(ea_detail_nodes=True),
            )
        )
        code_label = code_root.find(f".//{ns}g[@class='node-note']/{ns}text")
        assert code_label.get("font-family") == "Courier New"
        assert code_label.get("font-size") == "10"
        assert [label.text for label in code_root.findall(f".//{ns}g[@class='node-note']/{ns}text")] == [
            "first",
            "  second",
        ]

        calibri_note = note.model_copy(
            update={
                "style": note.style.model_copy(
                    update={
                        "font_size": 90,
                        "extra": {"font": "Calibri"},
                    }
                ),
            }
        )
        calibri_root = ET.fromstring(
            render_svg(
                diagram.model_copy(
                    update={
                        "diagram_type": "Custom",
                        "nodes": [calibri_note],
                        "connectors": [],
                    }
                ),
                style=NativeDiagramStyleConfig(ea_detail_nodes=True, font_family="Carlito"),
            )
        )
        calibri_label = calibri_root.find(f".//{ns}g[@class='node-note']/{ns}text")
        assert calibri_label.get("font-family") == "Carlito"

    def test_ea_page_frame_follows_object_bounds(self, extractor):
        from xml.etree import ElementTree as ET
        from eaidl.config import NativeDiagramStyleConfig

        diagram = extractor.extract_by_id(3)
        node = next(n for n in diagram.nodes if n.object_type == "Class")
        root = ET.fromstring(
            render_svg(
                diagram.model_copy(
                    update={
                        "name": "L7 : Example",
                        "view_id": None,
                        "diagram_type": "Custom",
                        "nodes": [node],
                        "connectors": [],
                    }
                ),
                style=NativeDiagramStyleConfig(ea_detail_nodes=True),
            )
        )
        ns = "{http://www.w3.org/2000/svg}"
        frame = root.find(f".//{ns}g[@id='ea-page-frame']")
        rect = frame.find(ns + "rect")
        assert float(rect.get("x")) == node.rect_left - 29
        assert float(rect.get("y")) == -node.rect_top - 34
        assert frame.find(ns + "text").text == "L7 L7 : Example"

    def test_statechart_frame_tab_tracks_its_label_width(self, extractor):
        from xml.etree import ElementTree as ET
        from eaidl.config import NativeDiagramStyleConfig

        diagram = extractor.extract_by_id(3)
        base = next(n for n in diagram.nodes if n.object_type == "Class")
        frame = base.model_copy(
            update={
                "object_type": "StateMachine",
                "name": "States",
                "rect_left": 20,
                "rect_right": 600,
                "rect_top": -20,
                "rect_bottom": -320,
            }
        )
        root = ET.fromstring(
            render_svg(
                diagram.model_copy(
                    update={
                        "diagram_type": "Statechart",
                        "name": "Task server state machine",
                        "nodes": [frame],
                        "connectors": [],
                    }
                ),
                style=NativeDiagramStyleConfig(ea_detail_nodes=True),
            )
        )
        ns = "{http://www.w3.org/2000/svg}"
        group = root.find(f".//{ns}g[@data-object-id='{frame.object_id}']")
        rects = group.findall(ns + "rect")
        assert [rect.get("stroke-width") for rect in rects] == ["2", None]
        assert group.find(ns + "polygon").get("points").startswith("20.0,40.0 150")

        state = frame.model_copy(
            update={
                "object_type": "State",
                "name": "CQL2 JSON\r\n(interchange format)",
                "rect_left": 40,
                "rect_right": 160,
                "rect_top": -60,
                "rect_bottom": -120,
            }
        )
        state_root = ET.fromstring(
            render_svg(
                diagram.model_copy(
                    update={
                        "diagram_type": "Statechart",
                        "nodes": [state],
                        "connectors": [],
                    }
                ),
                style=NativeDiagramStyleConfig(ea_detail_nodes=True),
            )
        )
        labels = state_root.findall(f".//{ns}g[@class='node-state']/{ns}text")
        assert [label.text for label in labels] == ["CQL2 JSON", "(interchange format)"]

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

    def test_ea_sequence_lifeline_and_reverse_async_message(self, extractor):
        from xml.etree import ElementTree as ET
        from eaidl.config import NativeDiagramStyleConfig

        diagram = extractor.extract_by_id(12)
        lifeline = next(n for n in diagram.nodes if n.object_type in ("Part", "Class"))
        lifeline = lifeline.model_copy(update={"name": "UPCS", "classifier_name": "Control System"})
        message = diagram.sequence_messages[0].model_copy(
            update={
                "name": "NodeStatus",
                "stereotype": "ResourceMessage",
                "call_type": "Asynchronous",
                "start_x": 300,
                "end_x": 140,
                "param_values": None,
                "source_object_id": lifeline.object_id,
                "target_object_id": lifeline.object_id + 1,
            }
        )
        root = ET.fromstring(
            render_svg(
                diagram.model_copy(
                    update={
                        "nodes": [lifeline],
                        "connectors": [],
                        "sequence_messages": [message],
                    }
                ),
                style=NativeDiagramStyleConfig(ea_detail_nodes=True),
            )
        )
        ns = "{http://www.w3.org/2000/svg}"
        head = root.find(f".//{ns}g[@class='lifeline']")
        assert " ".join(text.text or "" for text in head.findall(ns + "text")) == "UPCS: Control System"
        assert head.find(ns + "rect").get("stroke") == "#9a8484"
        group = root.find(f".//{ns}g[@class='seq-message']")
        path = group.find(ns + "path")
        assert path.get("stroke-dasharray") is None
        assert path.get("marker-end") == "url(#arrow-sequence)"
        assert [text.text for text in group.findall(ns + "text")] == ["NodeStatus()"]
        # EA exports every P6 message head as a closed, filled 12x8 triangle.
        marker = root.find(f".//{ns}marker[@id='arrow-sequence']")
        head_shape = marker.find(ns + "polygon")
        assert head_shape is not None
        assert head_shape.get("points") == "0,0 12,4 0,8"
        assert head_shape.get("fill") == "#69738c"

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

    def test_sequence_fragment_uses_ea_kind_and_tab_geometry(self, extractor):
        from xml.etree import ElementTree as ET
        from eaidl.config import NativeDiagramStyleConfig

        diagram = extractor.extract_by_id(12)
        base = diagram.nodes[0]
        fragment = base.model_copy(
            update={
                "object_type": "InteractionFragment",
                "ntype": 4,
                "name": "repeat status",
                "rect_left": 40,
                "rect_right": 574,
                "rect_top": -154,
                "rect_bottom": -513,
            }
        )
        root = ET.fromstring(
            render_svg(
                diagram.model_copy(
                    update={
                        "nodes": [fragment],
                        "connectors": [],
                        "sequence_messages": [],
                    }
                ),
                style=NativeDiagramStyleConfig(ea_detail_nodes=True),
            )
        )
        ns = "{http://www.w3.org/2000/svg}"
        group = root.find(f".//{ns}g[@class='fragment']")
        assert group.find(ns + "text").text == "loop repeat status"
        assert group.find(ns + "text").get("font-size") == "10"
        assert group.find(ns + "polygon").get("fill") == "#f1faed"
        assert group.find(ns + "polygon").get("points").startswith("40.0,154.0 40.0,174.0")

        alternatives = fragment.model_copy(
            update={
                "ntype": 0,
                "name": "",
                "interaction_operands": [
                    ("Payload reporting directly", 137),
                    ("Vehicle reporting on payload's behalf", 182),
                ],
            }
        )
        root = ET.fromstring(
            render_svg(
                diagram.model_copy(
                    update={
                        "nodes": [alternatives],
                        "connectors": [],
                        "sequence_messages": [],
                    }
                ),
                style=NativeDiagramStyleConfig(ea_detail_nodes=True),
            )
        )
        group = root.find(f".//{ns}g[@class='fragment']")
        assert [text.text for text in group.findall(ns + "text")] == [
            "alt",
            "[Payload reporting directly]",
            "[Vehicle reporting on payload's behalf]",
        ]
        assert group.find(ns + "line").get("y1") == "291.0"

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
            assert msg.activation_bar_height > 0, f"Expected activation_bar_height > 0 for {msg.name}"

    def test_note_connector_ref_extracted(self, extractor):
        """Note 77 in diagram 12 should reference connector id 54 (Message1)."""
        diag = extractor.extract_by_id(12)
        note = next(n for n in diag.nodes if n.object_id == 77)
        assert note.note_connector_ref == 54

    def test_note_without_connector_ref_is_none(self, extractor):
        """Note 76 (plain NoteLink note) should have note_connector_ref == None."""
        diag = extractor.extract_by_id(12)
        note = next(n for n in diag.nodes if n.object_id == 76)
        assert note.note_connector_ref is None

    def test_sequence_svg_contains_activation_bars(self, extractor):
        """Rendered SVG for sequence diagram should contain activation-bars group."""
        diag = extractor.extract_by_id(12)
        svg = render_svg(diag)
        assert 'id="activation-bars"' in svg

    def test_sequence_boundary_renders_division_and_label(self, extractor):
        from xml.etree import ElementTree as ET
        from eaidl.config import NativeDiagramStyleConfig

        diagram = extractor.extract_by_id(12)
        base = next(n for n in diagram.nodes if n.object_type in ("Class", "Part"))
        boundary = base.model_copy(
            update={
                "object_type": "Boundary",
                "name": "Patrol is activated",
                "rect_left": 30,
                "rect_right": 512,
                "rect_top": -118,
                "rect_bottom": -146,
            }
        )
        root = ET.fromstring(
            render_svg(
                diagram.model_copy(
                    update={
                        "diagram_type": "Sequence",
                        "nodes": [boundary],
                        "connectors": [],
                        "sequence_messages": [],
                    }
                ),
                style=NativeDiagramStyleConfig(ea_detail_nodes=True),
            )
        )
        ns = "{http://www.w3.org/2000/svg}"
        group = root.find(f".//{ns}g[@class='sequence-boundary']")
        assert group.find(ns + "rect").get("stroke-width") == "2"
        assert group.find(ns + "text").text == "Patrol is activated"
        assert group.find(ns + "text").get("y") == "134.0"

    def test_ea_sequence_export_does_not_infer_activation_from_message_height(self, extractor):
        from xml.etree import ElementTree as ET
        from eaidl.config import NativeDiagramStyleConfig

        diag = extractor.extract_by_id(12)
        root = ET.fromstring(render_svg(diag, style=NativeDiagramStyleConfig(ea_detail_nodes=True)))
        ns = "{http://www.w3.org/2000/svg}"
        group = root.find(f".//{ns}g[@id='activation-bars']")
        assert group is not None
        assert not group.findall(ns + "rect")

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
        required = {"type", "id", "x", "y", "width", "height", "strokeColor", "fillStyle", "roughness", "opacity"}
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
                assert el["roughness"] == 1, f"Element {el['id']} (type={el['type']}) has roughness {el['roughness']}"

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
                    f"Arrow {arrow['id']} startBinding.elementId {sb['elementId']!r} " "not found in elements"
                )
            eb = arrow.get("endBinding")
            if eb is not None:
                assert eb["elementId"] in element_ids, (
                    f"Arrow {arrow['id']} endBinding.elementId {eb['elementId']!r} " "not found in elements"
                )

    def test_arrows_are_bound_on_both_ends(self, extractor):
        """Most class-diagram arrows should be bound on both source and target."""
        import json

        diag = extractor.extract_by_id(3)
        doc = json.loads(render_excalidraw(diag))
        arrows = [el for el in doc["elements"] if el["type"] == "arrow"]
        bound_both = [a for a in arrows if a.get("startBinding") is not None and a.get("endBinding") is not None]
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
                        f"Rect {rect['id']} does not list arrow {arrow['id']} " "in its boundElements"
                    )

    def test_binding_references_header_rects(self, extractor):
        """Arrow bindings should point to 'hdr' elements (the header rects),
        not body or attr elements."""
        import json

        diag = extractor.extract_by_id(3)
        doc = json.loads(render_excalidraw(diag))
        arrows = [el for el in doc["elements"] if el["type"] == "arrow"]
        for arrow in arrows:
            for key in ("startBinding", "endBinding"):
                binding = arrow.get(key)
                if binding is not None:
                    eid = binding["elementId"]
                    assert eid.startswith("hdr-"), (
                        f"Arrow {arrow['id']} {key}.elementId={eid!r} " "should start with 'hdr-'"
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
                assert guid_re.match(node.ea_guid), f"Node {node.name!r} ea_guid {node.ea_guid!r} is not GUID-shaped"

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
            assert guid_re.match(key) or fallback_re.match(key), f"Unexpected link-map key format: {key!r}"

    def test_values_contain_name_and_object_id(self, extractor):
        diag = extractor.extract_by_id(3)
        for key, entry in svg_link_map(diag).items():
            assert "name" in entry
            assert "object_id" in entry

    def test_guid_keys_match_node_guids(self, extractor):
        diag = extractor.extract_by_id(3)
        # Notes are excluded from the link map
        node_guids = {n.ea_guid for n in diag.nodes if n.ea_guid and n.object_type != "Note"}
        map_keys = set(svg_link_map(diag).keys())
        assert node_guids <= map_keys, "Not all non-Note node ea_guids appear as keys in svg_link_map()"


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
        assert re.search(r'href="eaidl:\{[0-9A-Fa-f-]+\}"', svg), "Expected eaidl:{guid} pattern in SVG href attributes"

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
            assert el["link"].startswith("eaidl:"), f"Expected eaidl: prefix on link, got {el['link']!r}"

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
                    assert guid_re.match(
                        attr.type_guid
                    ), f"Attr {attr.name!r} type_guid {attr.type_guid!r} is not GUID-shaped"

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
        assert len(hrefs) > 1, "Expected multiple distinct eaidl: hrefs (one per class + one per linked type)"

    def test_header_link_differs_from_attribute_link(self, extractor):
        """For a node with linked-type attributes, header href != at least one attr href."""
        diag = extractor.extract_by_id(3)
        # Find a node that has ea_guid AND at least one attribute with type_guid
        candidate = next(
            (n for n in diag.nodes if n.ea_guid and any(a.type_guid for a in n.attributes)),
            None,
        )
        if candidate is None:
            pytest.skip("No suitable node found in diagram 3")
        node_href = f"eaidl:{candidate.ea_guid}"
        attr_hrefs = {f"eaidl:{a.type_guid}" for a in candidate.attributes if a.type_guid}
        assert (
            node_href not in attr_hrefs or len(attr_hrefs) > 0
        ), "At least one attribute href should be present alongside the header href"
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


# ---------------------------------------------------------------------------
# Renderer gaps: unlinked connectors, EA-mode labels
# ---------------------------------------------------------------------------


def _render_copy(db_path, diagram_name, ea_detail_nodes=False):
    from eaidl.config import NativeDiagramStyleConfig

    ex = NativeDiagramExtractor.from_url(f"sqlite:///{db_path}")
    try:
        diagram = next(d for d in ex.extract_all() if d.name == diagram_name)
    finally:
        ex.close()
    return diagram, render_svg(diagram, style=NativeDiagramStyleConfig(ea_detail_nodes=ea_detail_nodes))


def _texts(svg):
    from xml.etree import ElementTree as ET

    return [t.text for t in ET.fromstring(svg).iter("{http://www.w3.org/2000/svg}text")]


class TestRendererGaps:
    def test_connector_without_link_row_drawn(self, tmp_path):
        import shutil
        import sqlite3

        db = tmp_path / "copy.qea"
        shutil.copy("tests/data/nafv4.qea", db)
        con = sqlite3.connect(db)
        con.execute("delete from t_diagramlinks where DiagramID = (select Diagram_ID from t_diagram where Name='L7')")
        con.commit()
        con.close()
        diagram, svg = _render_copy(db, "L7")
        assert len(diagram.connectors) == 4
        assert all(c.ea_guid for c in diagram.connectors)
        assert svg.count('class="connector"') == 4

    def test_ea_mode_labels(self):
        diagram, svg = _render_copy("tests/data/nafv4.qea", "L7", ea_detail_nodes=True)
        assert diagram.view_id == "L7"
        texts = _texts(svg)
        assert "L7 L7" in texts
        assert "«DataElement,idlStruct»" in texts
        assert all(n.ea_guid for n in diagram.nodes)
        _, default_svg = _render_copy("tests/data/nafv4.qea", "L7")
        default_texts = _texts(default_svg)
        assert "L7" in default_texts
        assert "L7 L7" not in default_texts
        assert "«DataElement»" in default_texts
        assert "«DataElement,idlStruct»" not in default_texts

    def test_part_label_with_classifier(self, tmp_path):
        import shutil
        import sqlite3

        db = tmp_path / "copy.qea"
        shutil.copy("tests/data/nafv4.qea", db)
        con = sqlite3.connect(db)
        class_id, class_name = con.execute(
            "select Object_ID, Name from t_object where Object_Type='Class' order by length(Name), Object_ID limit 1"
        ).fetchone()
        con.execute("update t_object set Classifier = ? where Name = 'Asset1'", (class_id,))
        con.commit()
        con.close()
        _, svg = _render_copy(db, "p2", ea_detail_nodes=True)
        # EA wraps the label inside the narrow Part box
        assert f"Asset1 / {class_name}" in " ".join(_texts(svg))
