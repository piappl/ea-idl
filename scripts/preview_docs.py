#!/usr/bin/env python3
"""
Preview helper script for quick HTML documentation iteration.

This script generates HTML documentation to a temporary directory and
automatically opens it in your browser for quick visual verification.

Usage:
    python scripts/preview_docs.py [--config CONFIG_FILE] [--output OUTPUT_DIR]

Examples:
    # Use default config (config/sqlite.yaml) and temp directory
    python scripts/preview_docs.py

    # Use specific config
    python scripts/preview_docs.py --config config/postgres.yaml

    # Use specific output directory
    python scripts/preview_docs.py --output /tmp/my-docs
"""

import argparse
import webbrowser
from pathlib import Path
import sys
import shutil

# Add src to path for local imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from eaidl.utils import load_config
from eaidl.load import ModelParser
from eaidl.html_export import export_html
from eaidl.transforms import flatten_abstract_classes
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)


def preview_docs(config_file: str = "config/sqlite.yaml", output_dir: Path | None = None):
    """
    Generate HTML documentation and open in browser.

    :param config_file: Path to configuration file
    :param output_dir: Output directory (defaults to /tmp/ea-idl-preview)
    """
    # Default output to temp directory
    if output_dir is None:
        output_dir = Path("/tmp/ea-idl-preview")

    # Clean output directory if it exists
    if output_dir.exists():
        log.info(f"Cleaning existing output directory: {output_dir}")
        shutil.rmtree(output_dir)

    output_dir.mkdir(parents=True, exist_ok=True)

    # Load configuration
    log.info(f"Loading configuration from {config_file}")
    config = load_config(config_file)

    # Parse model
    log.info("Parsing EA model...")
    parser = ModelParser(config)
    packages = parser.load()

    # Apply transformations
    log.info("Applying transformations...")
    if config.flatten_abstract_classes:
        flatten_abstract_classes(packages)

    # Generate HTML
    log.info(f"Generating HTML documentation to {output_dir}")
    export_html(config, packages, output_dir)

    # Get path to index.html
    index_path = output_dir / "index.html"

    # Open in browser
    log.info(f"Opening browser to {index_path}")
    webbrowser.open(f"file://{index_path.absolute()}")

    # Print helpful message
    print("\n" + "=" * 60)
    print("HTML Documentation Preview")
    print("=" * 60)
    print(f"Location: {output_dir}")
    print(f"URL:      file://{index_path.absolute()}")
    print("=" * 60)
    print("\nThe documentation has been opened in your browser.")
    print("You can keep this directory for inspection or delete it when done.")
    print("=" * 60 + "\n")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Preview HTML documentation with auto-open in browser",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Use default config and temp directory
  python scripts/preview_docs.py

  # Use specific config
  python scripts/preview_docs.py --config config/postgres.yaml

  # Use specific output directory
  python scripts/preview_docs.py --output /tmp/my-docs

  # Combine options
  python scripts/preview_docs.py --config config/sqlite.yaml --output /tmp/test
        """,
    )

    parser.add_argument(
        "--config",
        "-c",
        default="config/sqlite.yaml",
        help="Configuration file (default: config/sqlite.yaml)",
    )

    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=None,
        help="Output directory (default: /tmp/ea-idl-preview)",
    )

    args = parser.parse_args()

    try:
        preview_docs(config_file=args.config, output_dir=args.output)
    except Exception as e:
        log.error(f"Failed to generate preview: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
