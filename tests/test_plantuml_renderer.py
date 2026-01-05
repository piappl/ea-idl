"""Tests for plantuml_renderer.py - PlantUML diagram rendering with mocked server."""

import pytest
from unittest.mock import Mock, patch
from eaidl.renderers.plantuml_renderer import (
    PlantUMLRenderer,
    PlantUMLClient,
    PlantUMLServerError,
)
from eaidl.diagram_model import (
    ClassDiagramDescription,
    DiagramClassNode,
    DiagramAttribute,
    DiagramRelationship,
    DiagramClickHandler,
    RelationType,
    OutputType,
)


class TestPlantUMLClient:
    """Test PlantUMLClient HTTP communication."""

    def test_init(self):
        """Test client initialization."""
        client = PlantUMLClient("http://localhost:10005/", timeout=30)
        assert client.server_url == "http://localhost:10005"
        assert client.timeout == 30

    def test_server_url_trailing_slash_removed(self):
        """Test that trailing slash is removed from server URL."""
        client = PlantUMLClient("http://localhost:10005/")
        assert client.server_url == "http://localhost:10005"

    @patch("eaidl.renderers.plantuml_renderer.requests.post")
    def test_generate_svg_success(self, mock_post):
        """Test successful SVG generation."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = "<svg>test</svg>"
        mock_post.return_value = mock_response

        client = PlantUMLClient("http://localhost:10005")
        svg = client.generate_svg("@startuml\nclass Foo\n@enduml")

        assert svg == "<svg>test</svg>"
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        assert args[0] == "http://localhost:10005/svg"
        assert kwargs["timeout"] == 30

    @patch("eaidl.renderers.plantuml_renderer.requests.post")
    def test_generate_svg_server_error(self, mock_post):
        """Test handling of server error response."""
        mock_response = Mock()
        mock_response.status_code = 500
        mock_response.text = "Internal server error"
        mock_post.return_value = mock_response

        client = PlantUMLClient("http://localhost:10005")

        with pytest.raises(PlantUMLServerError, match="returned HTTP 500"):
            client.generate_svg("@startuml\nclass Foo\n@enduml")

    @patch("eaidl.renderers.plantuml_renderer.requests.post")
    def test_generate_svg_timeout(self, mock_post):
        """Test handling of request timeout."""
        import requests

        mock_post.side_effect = requests.exceptions.Timeout()

        client = PlantUMLClient("http://localhost:10005", timeout=5)

        with pytest.raises(PlantUMLServerError, match="timed out after 5 seconds"):
            client.generate_svg("@startuml\nclass Foo\n@enduml")

    @patch("eaidl.renderers.plantuml_renderer.requests.post")
    def test_generate_svg_connection_error(self, mock_post):
        """Test handling of connection error."""
        import requests

        mock_post.side_effect = requests.exceptions.ConnectionError("Connection refused")

        client = PlantUMLClient("http://localhost:10005")

        with pytest.raises(PlantUMLServerError, match="Failed to connect"):
            client.generate_svg("@startuml\nclass Foo\n@enduml")

    @patch("eaidl.renderers.plantuml_renderer.requests.get")
    def test_check_health_success(self, mock_get):
        """Test successful health check."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_get.return_value = mock_response

        client = PlantUMLClient("http://localhost:10005")
        assert client.check_health() is True

    @patch("eaidl.renderers.plantuml_renderer.requests.get")
    def test_check_health_failure(self, mock_get):
        """Test failed health check."""
        import requests

        mock_get.side_effect = requests.exceptions.ConnectionError()

        client = PlantUMLClient("http://localhost:10005")
        assert client.check_health() is False


class TestPlantUMLRenderer:
    """Test PlantUMLRenderer functionality."""

    @pytest.fixture
    def renderer(self):
        """Create a PlantUMLRenderer instance."""
        return PlantUMLRenderer("http://localhost:10005", timeout=30)

    @patch("eaidl.renderers.plantuml_renderer.requests.post")
    def test_render_empty_diagram(self, mock_post, renderer):
        """Test rendering an empty diagram."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = "<svg>empty</svg>"
        mock_post.return_value = mock_response

        desc = ClassDiagramDescription()
        output = renderer.render_class_diagram(desc)

        assert output.output_type == OutputType.SVG
        assert output.error is None
        assert "<svg>" in output.content

    @patch("eaidl.renderers.plantuml_renderer.requests.post")
    def test_render_class_with_stereotypes(self, mock_post, renderer):
        """Test that stereotypes are included in PlantUML output."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = "<svg>diagram with stereotypes</svg>"
        mock_post.return_value = mock_response

        node = DiagramClassNode(id="Message", name="Message", stereotypes=["struct", "experimental"])
        desc = ClassDiagramDescription(nodes=[node])

        renderer.render_class_diagram(desc)

        # Check that PlantUML syntax includes stereotypes
        plantuml_text = mock_post.call_args[1]["data"].decode("utf-8")
        assert "<<struct>>" in plantuml_text
        assert "<<experimental>>" in plantuml_text

    @patch("eaidl.renderers.plantuml_renderer.requests.post")
    def test_render_abstract_class(self, mock_post, renderer):
        """Test that abstract classes use 'abstract' keyword."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = "<svg>abstract class</svg>"
        mock_post.return_value = mock_response

        node = DiagramClassNode(id="Base", name="Base", is_abstract=True)
        desc = ClassDiagramDescription(nodes=[node])

        renderer.render_class_diagram(desc)

        plantuml_text = mock_post.call_args[1]["data"].decode("utf-8")
        assert "abstract class Base" in plantuml_text

    @patch("eaidl.renderers.plantuml_renderer.requests.post")
    def test_render_class_with_attributes(self, mock_post, renderer):
        """Test rendering class with attributes."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = "<svg>class with attributes</svg>"
        mock_post.return_value = mock_response

        attr1 = DiagramAttribute(name="id", type="long")
        attr2 = DiagramAttribute(name="name", type="string", is_optional=True)
        node = DiagramClassNode(id="Message", name="Message", attributes=[attr1, attr2])
        desc = ClassDiagramDescription(nodes=[node])

        renderer.render_class_diagram(desc)

        plantuml_text = mock_post.call_args[1]["data"].decode("utf-8")
        assert "+id: long" in plantuml_text
        assert "+name?: string" in plantuml_text

    @patch("eaidl.renderers.plantuml_renderer.requests.post")
    def test_render_inherited_attributes(self, mock_post, renderer):
        """Test that inherited attributes are marked with {field}."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = "<svg>inherited</svg>"
        mock_post.return_value = mock_response

        attr1 = DiagramAttribute(name="base_id", type="long", is_inherited=True)
        attr2 = DiagramAttribute(name="child_name", type="string", is_inherited=False)
        node = DiagramClassNode(id="Child", name="Child", attributes=[attr1, attr2])
        desc = ClassDiagramDescription(nodes=[node])

        renderer.render_class_diagram(desc)

        plantuml_text = mock_post.call_args[1]["data"].decode("utf-8")
        assert "{field} +base_id: long" in plantuml_text
        assert "+child_name: string" in plantuml_text

    @patch("eaidl.renderers.plantuml_renderer.requests.post")
    def test_render_relationships(self, mock_post, renderer):
        """Test rendering various relationship types."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = "<svg>relationships</svg>"
        mock_post.return_value = mock_response

        node1 = DiagramClassNode(id="Child", name="Child")
        node2 = DiagramClassNode(id="Parent", name="Parent")
        node3 = DiagramClassNode(id="Helper", name="Helper")

        rel1 = DiagramRelationship(source_id="Child", target_id="Parent", type=RelationType.INHERITANCE)
        rel2 = DiagramRelationship(source_id="Child", target_id="Helper", type=RelationType.COMPOSITION)

        desc = ClassDiagramDescription(nodes=[node1, node2, node3], relationships=[rel1, rel2])

        renderer.render_class_diagram(desc)

        plantuml_text = mock_post.call_args[1]["data"].decode("utf-8")
        assert "Child --|> Parent" in plantuml_text
        assert "Child *-- Helper" in plantuml_text

    @patch("eaidl.renderers.plantuml_renderer.requests.post")
    def test_render_relationship_with_stereotypes(self, mock_post, renderer):
        """Test rendering relationships with stereotypes."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = "<svg>stereotyped relationships</svg>"
        mock_post.return_value = mock_response

        node1 = DiagramClassNode(id="Source", name="Source")
        node2 = DiagramClassNode(id="Target", name="Target")

        # Test single stereotype
        rel1 = DiagramRelationship(
            source_id="Source", target_id="Target", type=RelationType.ASSOCIATION, stereotypes=["create"]
        )

        # Test multiple stereotypes
        rel2 = DiagramRelationship(
            source_id="Target", target_id="Source", type=RelationType.DEPENDENCY, stereotypes=["use", "access"]
        )

        desc = ClassDiagramDescription(nodes=[node1, node2], relationships=[rel1, rel2])

        renderer.render_class_diagram(desc)

        plantuml_text = mock_post.call_args[1]["data"].decode("utf-8")
        assert "Source --> Target : <<create>>" in plantuml_text
        assert "Target ..> Source : <<use>> <<access>>" in plantuml_text

    @patch("eaidl.renderers.plantuml_renderer.requests.post")
    def test_render_click_handlers(self, mock_post, renderer):
        """Test rendering click handlers as hyperlinks."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = "<svg>clickable</svg>"
        mock_post.return_value = mock_response

        node = DiagramClassNode(id="Message", name="Message")
        handler = DiagramClickHandler(node_id="Message", link="../classes/Message.html")
        desc = ClassDiagramDescription(nodes=[node], click_handlers=[handler])

        renderer.render_class_diagram(desc)

        plantuml_text = mock_post.call_args[1]["data"].decode("utf-8")
        assert "url of Message is [[../classes/Message.html]]" in plantuml_text

    @patch("eaidl.renderers.plantuml_renderer.requests.post")
    def test_server_error_raises_exception(self, mock_post, renderer):
        """Test that server errors raise PlantUMLServerError."""
        mock_response = Mock()
        mock_response.status_code = 500
        mock_response.text = "Server error"
        mock_post.return_value = mock_response

        desc = ClassDiagramDescription(nodes=[DiagramClassNode(id="Test", name="Test")])

        with pytest.raises(PlantUMLServerError):
            renderer.render_class_diagram(desc)

    @patch("eaidl.renderers.plantuml_renderer.requests.post")
    def test_plantuml_syntax_structure(self, mock_post, renderer):
        """Test that generated PlantUML has correct structure."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = "<svg>test</svg>"
        mock_post.return_value = mock_response

        node = DiagramClassNode(id="Test", name="Test")
        desc = ClassDiagramDescription(nodes=[node])

        renderer.render_class_diagram(desc)

        plantuml_text = mock_post.call_args[1]["data"].decode("utf-8")
        assert plantuml_text.startswith("@startuml")
        assert plantuml_text.endswith("@enduml")
        assert "skinparam classAttributeIconSize 0" in plantuml_text
