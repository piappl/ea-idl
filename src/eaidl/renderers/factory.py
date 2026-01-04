"""
Renderer factory - Returns appropriate diagram renderer based on configuration.
"""

from eaidl.config import Configuration
from eaidl.diagram_model import DiagramRenderer
from eaidl.renderers.mermaid_renderer import MermaidRenderer
from eaidl.renderers.plantuml_renderer import PlantUMLRenderer
import logging

log = logging.getLogger(__name__)


def get_renderer(config: Configuration) -> DiagramRenderer:
    """
    Get the appropriate diagram renderer based on configuration.

    :param config: Configuration object
    :return: DiagramRenderer instance
    :raises ValueError: If renderer type is not supported
    """
    renderer_type = config.diagrams.renderer

    if renderer_type == "mermaid":
        return MermaidRenderer()
    elif renderer_type == "plantuml":
        return PlantUMLRenderer(
            server_url=config.diagrams.plantuml_server_url,
            timeout=config.diagrams.plantuml_timeout,
        )
    else:
        raise ValueError(f"Unknown diagram renderer: {renderer_type}. " f"Supported renderers: mermaid, plantuml")
