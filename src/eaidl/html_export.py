"""
HTML documentation export for EA-IDL.

This module generates static HTML documentation from EA model packages,
including interactive Mermaid diagrams, search, and cross-references.
"""

from pathlib import Path
from typing import List, Dict
import json
import shutil
from datetime import datetime
import logging

from jinja2 import Environment, PackageLoader, select_autoescape

from eaidl.model import ModelPackage
from eaidl.config import Configuration
from eaidl.link_utils import (
    generate_class_link,
    generate_package_link,
    generate_index_link,
    resolve_type_reference,
    get_inherited_attributes,
)
from eaidl.html_utils import strip_html, format_notes_for_html
import sqlalchemy
from sqlalchemy.orm import Session

log = logging.getLogger(__name__)


def create_html_env(config: Configuration) -> Environment:
    """
    Create Jinja2 environment for HTML templates.

    :param config: Configuration object
    :return: Configured Jinja2 environment
    """
    env = Environment(
        loader=PackageLoader("eaidl", "templates/html"),
        autoescape=select_autoescape(["html", "xml"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )

    # Make config available globally
    env.globals["config"] = config

    # Add custom filters and functions
    env.filters["strip_html"] = strip_html
    env.filters["format_notes"] = format_notes_for_html

    return env


def export_html(config: Configuration, packages: List[ModelPackage], output_dir: Path) -> None:
    """
    Export HTML documentation to output directory.

    Creates complete static website with:
    - Index page
    - Package pages with diagrams
    - Class detail pages
    - Search index
    - Assets (CSS, JS)

    :param config: Configuration object
    :param packages: List of model packages
    :param output_dir: Output directory path
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    log.info(f"Exporting HTML documentation to {output_path}")

    # Copy assets
    copy_assets(output_path)

    # Create Jinja2 environment
    env = create_html_env(config)

    # Register helper functions as globals
    env.globals["generate_class_link"] = generate_class_link
    env.globals["generate_package_link"] = generate_package_link
    env.globals["generate_index_link"] = generate_index_link
    env.globals["resolve_type_reference"] = resolve_type_reference
    env.globals["get_inherited_attributes"] = get_inherited_attributes
    env.globals["all_packages"] = packages
    env.globals["generation_date"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Helper function for generating package links with current namespace context
    def generate_package_link_from_current(current_ns, target_ns):
        return generate_package_link(current_ns or [], target_ns)

    def generate_package_link_for_breadcrumb(current_ns, target_ns):
        # For breadcrumbs, we need to calculate from current page to target package
        return generate_package_link(current_ns, target_ns)

    env.globals["generate_package_link_from_current"] = generate_package_link_from_current
    env.globals["generate_package_link_for_breadcrumb"] = generate_package_link_for_breadcrumb

    # Generate pages
    generate_index_page(packages, output_path, env)
    generate_package_pages(packages, output_path, env, config)
    generate_class_pages(packages, output_path, env, config)

    # Generate search index
    generate_search_index(packages, output_path)

    log.info("HTML export completed successfully")


def copy_assets(output_dir: Path) -> None:
    """
    Copy static assets (CSS, JS) to output directory.

    :param output_dir: Output directory path
    """
    assets_src = Path(__file__).parent / "templates" / "html" / "assets"
    assets_dest = output_dir / "assets"

    if not assets_src.exists():
        log.error(f"Assets directory not found: {assets_src}")
        log.error("Run scripts/download_assets.py to download required files")
        raise FileNotFoundError(f"Assets not found: {assets_src}")

    # Remove existing assets and copy fresh
    if assets_dest.exists():
        shutil.rmtree(assets_dest)

    shutil.copytree(assets_src, assets_dest)
    log.info(f"Copied assets to {assets_dest}")


def generate_index_page(packages: List[ModelPackage], output_dir: Path, env: Environment) -> None:
    """
    Generate index/landing page.

    :param packages: All model packages
    :param output_dir: Output directory
    :param env: Jinja2 environment
    """
    template = env.get_template("index.jinja2")

    # Calculate statistics
    stats = calculate_model_statistics(packages)

    # Set paths for base template
    html = template.render(
        packages=packages,
        stats=stats,
        current_namespace=None,
        index_link="index.html",
        assets_path="assets",
        search_index_path="search.json",
    )

    index_file = output_dir / "index.html"
    index_file.write_text(html, encoding="utf-8")
    log.info(f"Generated index page: {index_file}")


def generate_package_pages(
    packages: List[ModelPackage], output_dir: Path, env: Environment, config: Configuration
) -> None:
    """
    Generate package pages (index and diagram) for all packages.

    :param packages: All model packages
    :param output_dir: Output directory
    :param env: Jinja2 environment
    :param config: Configuration
    """
    template_package = env.get_template("package.jinja2")
    template_diagram = env.get_template("diagram.jinja2")

    # Create database session for EA diagram conversion
    engine = sqlalchemy.create_engine(config.database_url, echo=False, future=True)
    session = Session(engine)

    def process_package(package: ModelPackage, namespace_path: List[str]) -> None:
        """Recursively process package and nested packages."""
        # Create package directory
        pkg_dir = output_dir / "packages" / "/".join(namespace_path)
        pkg_dir.mkdir(parents=True, exist_ok=True)

        # Calculate paths for this namespace level
        depth = len(namespace_path)
        assets_rel_path = "/".join([".."] * (depth + 1)) + "/assets"
        index_rel_link = "/".join([".."] * (depth + 1)) + "/index.html"
        search_rel_path = "/".join([".."] * (depth + 1)) + "/search.json"

        # Generate package index page
        html = template_package.render(
            package=package,
            current_namespace=namespace_path,
            index_link=index_rel_link,
            assets_path=assets_rel_path,
            search_index_path=search_rel_path,
        )
        (pkg_dir / "index.html").write_text(html, encoding="utf-8")

        # Generate diagram page with both auto-generated and EA diagrams
        if package.classes or package.diagrams:
            # Use new builder → renderer pipeline
            from eaidl.diagram_builder import ClassDiagramBuilder
            from eaidl.renderers.factory import get_renderer

            renderer = get_renderer(config)

            # Generate auto-generated diagram
            auto_diagram_output = None
            auto_diagram_content = None
            auto_diagram_type = None
            if package.classes:
                try:
                    builder = ClassDiagramBuilder(package, config, packages)
                    diagram_desc = builder.build()
                    auto_diagram_output = renderer.render_class_diagram(diagram_desc)
                    auto_diagram_content = auto_diagram_output.content
                    auto_diagram_type = auto_diagram_output.output_type.value
                except Exception as e:
                    # Re-raise PlantUML server errors to fail the build
                    from eaidl.renderers import PlantUMLServerError

                    if isinstance(e, PlantUMLServerError):
                        raise
                    log.error(f"Failed to generate auto diagram for package '{package.name}': {e}")
                    # For Mermaid and other errors, this is non-fatal

            # Convert EA diagrams using builder → renderer pipeline
            ea_diagrams = []
            for ea_diagram in package.diagrams:
                try:
                    # Use new builder architecture
                    from eaidl.ea_diagram_builder import EADiagramBuilder

                    builder = EADiagramBuilder(ea_diagram, packages, config, session)
                    diagram_desc = builder.build()

                    # Render with configured renderer (Mermaid or PlantUML)
                    if hasattr(diagram_desc, "participants"):
                        # Sequence diagram
                        ea_output = renderer.render_sequence_diagram(diagram_desc)
                    else:
                        # Class diagram
                        ea_output = renderer.render_class_diagram(diagram_desc)

                    ea_diagrams.append(
                        {
                            "name": ea_diagram.name,
                            "type": ea_diagram.diagram_type,
                            "notes": ea_diagram.notes,
                            "author": ea_diagram.author,
                            "diagram_content": ea_output.content,
                            "diagram_type": ea_output.output_type.value,  # "text" or "svg"
                        }
                    )
                except Exception as e:
                    # Re-raise PlantUML server errors to fail the build
                    from eaidl.renderers import PlantUMLServerError

                    if isinstance(e, PlantUMLServerError):
                        raise
                    log.warning(
                        f"Failed to convert EA diagram '{ea_diagram.name}' " f"in package '{package.name}': {e}"
                    )
                    # Continue with other diagrams

            # Render diagram page with tabs
            html_diagram = template_diagram.render(
                package=package,
                auto_diagram_content=auto_diagram_content,
                auto_diagram_type=auto_diagram_type,
                ea_diagrams=ea_diagrams,
                current_namespace=namespace_path,
                index_link=index_rel_link,
                assets_path=assets_rel_path,
                search_index_path=search_rel_path,
            )
            (pkg_dir / "diagram.html").write_text(html_diagram, encoding="utf-8")

        log.debug(f"Generated package pages: {pkg_dir}")

        # Process nested packages
        for nested in package.packages:
            process_package(nested, namespace_path + [nested.name])

    # Process all top-level packages
    for package in packages:
        if package.name != "ext":  # Skip internal 'ext' package
            process_package(package, [package.name])

    # Close session
    session.close()

    log.info("Generated all package pages")


def generate_class_pages(
    packages: List[ModelPackage], output_dir: Path, env: Environment, config: Configuration
) -> None:
    """
    Generate class detail pages for all classes.

    :param packages: All model packages
    :param output_dir: Output directory
    :param env: Jinja2 environment
    :param config: Configuration
    """
    template = env.get_template("class.jinja2")

    def process_package_classes(package: ModelPackage) -> None:
        """Process all classes in package and nested packages."""
        for cls in package.classes:
            # Create class directory
            namespace = cls.namespace
            class_dir = output_dir / "classes" / "/".join(namespace)
            class_dir.mkdir(parents=True, exist_ok=True)

            # Calculate paths
            depth = len(namespace)
            assets_rel_path = "/".join([".."] * (depth + 1)) + "/assets"
            index_rel_link = "/".join([".."] * (depth + 1)) + "/index.html"
            search_rel_path = "/".join([".."] * (depth + 1)) + "/search.json"

            # Generate class page
            html = template.render(
                cls=cls,
                current_namespace=namespace,
                index_link=index_rel_link,
                assets_path=assets_rel_path,
                search_index_path=search_rel_path,
            )

            class_file = class_dir / f"{cls.name}.html"
            class_file.write_text(html, encoding="utf-8")

            log.debug(f"Generated class page: {class_file}")

        # Process nested packages
        for nested in package.packages:
            process_package_classes(nested)

    for package in packages:
        if package.name != "ext":
            process_package_classes(package)

    log.info("Generated all class pages")


def generate_search_index(packages: List[ModelPackage], output_dir: Path) -> None:
    """
    Generate JavaScript search index for client-side search.

    Creates both search.json (for backward compatibility) and search.js
    (for file:// protocol support).

    :param packages: All model packages
    :param output_dir: Output directory
    """
    index = []

    def process_package(package: ModelPackage, namespace_path: List[str]) -> None:
        """Build search index from package."""
        # Add package to index
        pkg_url = f"packages/{'/'.join(namespace_path)}/index.html"
        index.append(
            {
                "name": package.name,
                "type": "package",
                "namespace": namespace_path[:-1] if len(namespace_path) > 1 else [],
                "content": strip_html(package.notes) if package.notes else "",
                "url": pkg_url,
            }
        )

        # Add classes
        for cls in package.classes:
            class_url = f"classes/{'/'.join(cls.namespace)}/{cls.name}.html"
            cls_type = (
                "struct"
                if cls.is_struct
                else "enum"
                if cls.is_enum
                else "union"
                if cls.is_union
                else "typedef"
                if cls.is_typedef
                else "class"
            )

            notes_content = strip_html(cls.notes) if cls.notes else ""

            index.append(
                {
                    "name": cls.name,
                    "type": cls_type,
                    "namespace": cls.namespace,
                    "content": notes_content,
                    "url": class_url,
                }
            )

            # Add attributes
            for attr in cls.attributes:
                attr_url = f"{class_url}#attr-{attr.name}"
                attr_content = strip_html(attr.notes) if attr.notes else ""

                index.append(
                    {
                        "name": attr.name,
                        "type": "attribute",
                        "parent": cls.name,
                        "namespace": cls.namespace,
                        "content": attr_content,
                        "url": attr_url,
                    }
                )

        # Process nested packages
        for nested in package.packages:
            process_package(nested, namespace_path + [nested.name])

    # Build index from all packages
    for package in packages:
        if package.name != "ext":
            process_package(package, [package.name])

    # Write JSON index (for backward compatibility and debugging)
    json_file = output_dir / "search.json"
    json_file.write_text(json.dumps(index, indent=2), encoding="utf-8")
    log.info(f"Generated search index (JSON): {json_file} ({len(index)} items)")

    # Write JavaScript index (works with file:// protocol)
    js_file = output_dir / "search.js"
    js_content = f"// EA-IDL Search Index\n// Auto-generated on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\nconst SEARCH_INDEX = {json.dumps(index)};\n"
    js_file.write_text(js_content, encoding="utf-8")
    log.info(f"Generated search index (JS): {js_file} ({len(index)} items)")


def calculate_model_statistics(packages: List[ModelPackage]) -> Dict[str, int]:
    """
    Calculate statistics about the model.

    :param packages: All model packages
    :return: Dictionary with counts
    """
    stats = {
        "packages": 0,
        "structs": 0,
        "enums": 0,
        "unions": 0,
        "typedefs": 0,
        "classes": 0,
        "attributes": 0,
    }

    def count_package(package: ModelPackage) -> None:
        """Recursively count package contents."""
        stats["packages"] += 1

        for cls in package.classes:
            stats["classes"] += 1
            stats["attributes"] += len(cls.attributes)

            if cls.is_struct:
                stats["structs"] += 1
            elif cls.is_enum:
                stats["enums"] += 1
            elif cls.is_union:
                stats["unions"] += 1
            elif cls.is_typedef:
                stats["typedefs"] += 1

        for nested in package.packages:
            count_package(nested)

    for package in packages:
        if package.name != "ext":
            count_package(package)

    return stats
