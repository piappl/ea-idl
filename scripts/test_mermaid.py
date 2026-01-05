#!/usr/bin/env python3
"""
Test script to validate Mermaid diagram syntax.

This script generates HTML test files for Mermaid diagrams from the EA-IDL documentation.
Open the generated HTML files in a browser to verify they render correctly.

Usage:
    python scripts/test_mermaid.py
"""

from pathlib import Path
import sys

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from eaidl.load import ModelParser
from eaidl.utils import load_config
from eaidl.diagram_builder import ClassDiagramBuilder
from eaidl.renderers.factory import get_renderer
from eaidl.transforms import flatten_abstract_classes


def create_test_html(diagram_code: str, title: str, output_path: Path) -> None:
    """Create a test HTML file with the given Mermaid diagram."""
    html = f"""<!DOCTYPE html>
<html>
<head>
    <title>{title}</title>
    <script type="module">
        import mermaid from 'https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs';

        mermaid.initialize({{
            startOnLoad: true,
            theme: 'default',
            securityLevel: 'loose',
            logLevel: 'error'
        }});

        window.addEventListener('load', async () => {{
            try {{
                await mermaid.run({{
                    querySelector: '.mermaid'
                }});
                document.getElementById('status').textContent = '✓ Diagram rendered successfully';
                document.getElementById('status').style.color = 'green';
            }} catch (error) {{
                document.getElementById('status').textContent = '✗ Error: ' + error.message;
                document.getElementById('status').style.color = 'red';
                document.getElementById('error-detail').textContent = error.stack || error.toString();
            }}
        }});
    </script>
    <style>
        body {{ font-family: sans-serif; padding: 20px; }}
        #status {{ font-weight: bold; margin: 20px 0; font-size: 18px; }}
        #error-detail {{ background: #fee; padding: 10px; border-radius: 5px; white-space: pre-wrap; margin: 10px 0; }}
        .mermaid {{ border: 1px solid #ccc; padding: 20px; background: white; }}
        .source {{ background: #f5f5f5; padding: 10px; border-radius: 5px; white-space: pre; font-family: monospace; font-size: 12px; }}
    </style>
</head>
<body>
    <h1>{title}</h1>
    <div id="status">Loading...</div>
    <div id="error-detail"></div>

    <h2>Rendered Diagram</h2>
    <pre class="mermaid">
{diagram_code}
    </pre>

    <h2>Source Code</h2>
    <div class="source">{diagram_code}</div>
</body>
</html>
"""
    output_path.write_text(html, encoding="utf-8")
    print(f"Created test file: {output_path}")


def main():
    """Generate test HTML files for all package diagrams."""
    # Load test database
    config_path = Path("config/sqlite.yaml")
    if not config_path.exists():
        print("Error: config/sqlite.yaml not found")
        print("Run this script from the EA-IDL project root directory")
        return 1

    print("Loading model from test database...")
    config = load_config(config_path)
    parser = ModelParser(config)
    packages = parser.load()

    # Apply transformations
    if config.flatten_abstract_classes:
        flatten_abstract_classes(packages)

    # Create output directory
    output_dir = Path("/tmp/ea-idl-mermaid-tests")
    output_dir.mkdir(exist_ok=True)

    # Generate test HTML for each package
    test_count = 0
    for package in packages:
        if package.name == "ext":
            continue

        def process_package(pkg, namespace_path):
            nonlocal test_count
            if pkg.classes:
                print(f"Generating diagram for {'.'.join(namespace_path)}...")
                builder = ClassDiagramBuilder(pkg, config, packages)
                desc = builder.build()
                renderer = get_renderer(config)
                output = renderer.render_class_diagram(desc)
                diagram_code = output.content

                # Create test HTML
                title = f"Mermaid Test: {'.'.join(namespace_path)}"
                filename = "_".join(namespace_path) + ".html"
                output_path = output_dir / filename

                create_test_html(diagram_code, title, output_path)
                test_count += 1

            # Process nested packages
            for nested in pkg.packages:
                process_package(nested, namespace_path + [nested.name])

        process_package(package, [package.name])

    print(f"\n✓ Generated {test_count} test HTML files in {output_dir}")
    print("Open the HTML files in a browser to verify the diagrams render correctly")
    print(f"\nExample: open {output_dir}/core_data.html")

    return 0


if __name__ == "__main__":
    sys.exit(main())
