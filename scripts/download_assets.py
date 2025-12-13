#!/usr/bin/env python3
"""
Download static assets for HTML documentation export.

This script downloads Bootstrap 5, Mermaid.js, and Fuse.js for offline use.
Assets are saved to src/eaidl/templates/html/assets/ and should be committed to the repository.

Run this script once during development setup:
    python scripts/download_assets.py
"""

import urllib.request
from pathlib import Path
import shutil

# Asset URLs (using specific versions for reproducibility)
ASSETS = {
    "css/bootstrap.min.css": "https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css",
    "js/bootstrap.bundle.min.js": "https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js",
    "js/mermaid.min.js": "https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js",
    "js/fuse.min.js": "https://cdn.jsdelivr.net/npm/fuse.js@7.0.0/dist/fuse.min.js",
}


def download_file(url: str, dest: Path) -> None:
    """Download a file from URL to destination path."""
    print(f"Downloading {url}...")
    dest.parent.mkdir(parents=True, exist_ok=True)

    with urllib.request.urlopen(url) as response:
        with open(dest, "wb") as out_file:
            shutil.copyfileobj(response, out_file)

    print(f"  → Saved to {dest}")


def main():
    """Download all assets to templates directory."""
    # Get project root (parent of scripts/)
    script_dir = Path(__file__).parent
    project_root = script_dir.parent
    assets_dir = project_root / "src" / "eaidl" / "templates" / "html" / "assets"

    print(f"Downloading assets to {assets_dir}")
    print("=" * 60)

    for rel_path, url in ASSETS.items():
        dest = assets_dir / rel_path
        try:
            download_file(url, dest)
        except Exception as e:
            print(f"ERROR: Failed to download {url}: {e}")
            return 1

    print("=" * 60)
    print(f"✓ All assets downloaded successfully to {assets_dir}")
    print("\nNext steps:")
    print("  1. Review downloaded files")
    print("  2. Commit assets to repository")
    print("  3. Run HTML export: eaidl docs --config config.yaml")

    return 0


if __name__ == "__main__":
    exit(main())
