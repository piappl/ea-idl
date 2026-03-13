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
    elif renderer_type == "native":
        # The 'native' renderer is handled directly in html_export and does not
        # go through the DiagramRenderer interface.  For paths that still need
        # a DiagramRenderer (e.g. auto-generated class diagrams) we fall back
        # to Mermaid.
        log.debug(
            "renderer='native' was passed to get_renderer(); "
            "returning MermaidRenderer as fallback for auto-generated diagrams."
        )
        return MermaidRenderer()
    else:
        raise ValueError(f"Unknown diagram renderer: {renderer_type}. " f"Supported renderers: mermaid, plantuml, native")
