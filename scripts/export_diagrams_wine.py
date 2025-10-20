#!/usr/bin/env python3
"""
Export diagrams from Enterprise Architect to SVG and PNG using COM API.

This script supports both:
- Native Windows with Python + pywin32
- Linux with Wine + 32-bit Python + pywin32

The script automatically detects the platform and adjusts paths accordingly.

Requirements (Windows):
- Python 3.x (32-bit or 64-bit)
- pywin32 (pip install pywin32)
- EA model file (.qea or .eap)

Requirements (Linux with Wine):
- Wine 32-bit environment (WINEPREFIX=~/.wine32, WINEARCH=win32)
- Python 3.x 32-bit installed in Wine
- pywin32 installed in Wine Python
- EA model file (.qea or .eap)

Usage:
    # On Windows:
    python export_diagrams_wine.py --model C:\\path\\to\\model.qea --output .\\diagrams

    # On Linux with Wine:
    wine python.exe export_diagrams_wine.py --model /path/to/model.qea --output ./diagrams
"""

import argparse
import os
import platform
import re
import sys
import time
import win32com.client
from pathlib import Path


def is_running_under_wine():
    """Detect if we're running under Wine (Linux with Wine) vs native Windows."""
    # Check if we're on Windows
    if platform.system() == "Windows":
        # Check if we're running under Wine by looking for Wine-specific environment
        # Wine sets WINEPREFIX and other Wine-specific variables
        if os.environ.get("WINEPREFIX") or os.environ.get("WINEARCH"):
            return True
        # Another check: Wine's sys.platform is still 'win32' but we can detect Wine DLLs
        # For simplicity, if on Windows and no Wine env vars, assume native Windows
        return False
    else:
        # On Linux/Unix, we must be using Wine to access win32com
        return True


def convert_to_windows_path(path_str):
    """Convert a path to Windows format.

    On Wine (Linux): Converts Unix paths to Wine Z: drive format
    On Windows: Returns path as-is (already in Windows format)

    Args:
        path_str: Path string (can be Unix or Windows format)

    Returns:
        Windows-formatted path string
    """
    if not path_str:
        return path_str

    is_wine = is_running_under_wine()

    if is_wine:
        # Running under Wine - convert Unix paths to Z: drive format
        if path_str.startswith("/"):
            # Unix absolute path - convert to Wine Z: drive
            return f"Z:{path_str.replace('/', '\\')}"
        else:
            # Already in Windows format or relative path
            return path_str
    else:
        # Native Windows - path should already be in Windows format
        # Convert forward slashes to backslashes if needed
        return path_str.replace("/", "\\")


def open_repository(model_path):
    """Open EA repository via COM API.

    Args:
        model_path: Path to the EA model file

    Returns:
        EA Repository object
    """
    try:
        print(f"Opening repository: {model_path}")

        # Create EA Repository object
        repo = win32com.client.Dispatch("EA.Repository")

        # Convert path to Windows format (Wine Z: drive on Linux, native on Windows)
        windows_path = convert_to_windows_path(model_path)

        # Open the file
        success = repo.OpenFile2(windows_path, "", "")
        if not success:
            print(f"ERROR: Failed to open repository at {windows_path}")
            sys.exit(1)

        print("Repository opened successfully")
        print(f"Models count: {repo.Models.Count}")

        return repo
    except Exception as e:
        print(f"ERROR opening repository: {e}")
        sys.exit(1)


def get_all_diagrams(repo, package=None, package_path=None):
    """Recursively get all diagrams from a package and its sub-packages.

    Args:
        repo: EA Repository object
        package: Current package to process (None to start from root)
        package_path: List of parent package names (for building hierarchy)

    Returns:
        List of diagram info dictionaries with package hierarchy
    """
    diagrams = []

    if package is None:
        # Start from all models
        for i in range(repo.Models.Count):
            model = repo.Models.GetAt(i)
            # Start with model name as the root of the path
            diagrams.extend(get_all_diagrams(repo, model, package_path=[model.Name]))
    else:
        # Initialize package_path if not provided
        if package_path is None:
            package_path = [package.Name]

        # Get diagrams from current package
        for i in range(package.Diagrams.Count):
            diagram = package.Diagrams.GetAt(i)
            diagrams.append(
                {
                    "diagram": diagram,
                    "package_name": package.Name,  # Immediate package name
                    "package_path": package_path,  # Full hierarchy as list
                    "diagram_name": diagram.Name,
                    "diagram_id": diagram.DiagramID,
                    "diagram_guid": diagram.DiagramGUID,
                    "type": diagram.Type,
                }
            )

        # Recurse into sub-packages
        for i in range(package.Packages.Count):
            sub_package = package.Packages.GetAt(i)
            # Extend the package path with the sub-package name
            sub_path = package_path + [sub_package.Name]
            diagrams.extend(get_all_diagrams(repo, sub_package, package_path=sub_path))

    return diagrams


def sanitize_filename(name, max_length=200):
    """Convert a name to a safe cross-platform filename or directory name.

    Removes or replaces characters that are invalid in Windows and/or Linux filesystems.

    Args:
        name: The original name to sanitize
        max_length: Maximum length for the component (default 200)

    Returns:
        Sanitized name safe for both Windows and Linux filesystems
    """
    if not name:
        return "unnamed"

    safe_name = name

    # Windows forbidden characters: < > : " / \ | ? *
    # Linux forbidden characters: / and \0
    replacements = {
        "<": "",
        ">": "",
        ":": "_",
        '"': "",
        "/": "_",
        "\\": "_",
        "|": "_",
        "?": "",
        "*": "",
        "\0": "",
        "\r": "",
        "\n": "_",
        "\t": "_",
    }

    for old_char, new_char in replacements.items():
        safe_name = safe_name.replace(old_char, new_char)

    # Remove/replace control characters (ASCII 0-31) and DEL (127)
    safe_name = "".join(char if 32 <= ord(char) < 127 or ord(char) > 127 else "_" for char in safe_name)

    # Replace multiple consecutive underscores/spaces with single underscore
    safe_name = re.sub(r"[\s_]+", "_", safe_name)

    # Remove leading/trailing spaces, dots, and underscores
    safe_name = safe_name.strip(" ._")

    # Handle Windows reserved names (CON, PRN, AUX, NUL, COM1-9, LPT1-9)
    windows_reserved = {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        "COM1",
        "COM2",
        "COM3",
        "COM4",
        "COM5",
        "COM6",
        "COM7",
        "COM8",
        "COM9",
        "LPT1",
        "LPT2",
        "LPT3",
        "LPT4",
        "LPT5",
        "LPT6",
        "LPT7",
        "LPT8",
        "LPT9",
    }
    base_name = safe_name.split(".")[0] if "." in safe_name else safe_name
    if base_name.upper() in windows_reserved:
        safe_name = f"_{safe_name}"

    # Truncate to max length
    if len(safe_name) > max_length:
        safe_name = safe_name[:max_length].rstrip("_.")

    # Final check: ensure we have a valid name
    if not safe_name or safe_name in (".", ".."):
        safe_name = "unnamed"

    return safe_name


def export_diagram(repo, diagram_info, output_dir, formats=["svg", "png"]):
    """Export a single diagram to specified formats.

    Args:
        repo: EA Repository object
        diagram_info: Dictionary with diagram metadata
        output_dir: Output directory path
        formats: List of export formats
    """
    # Get diagram reference from repository
    diagram_id = diagram_info["diagram_id"]
    diagram = repo.GetDiagramByID(diagram_id)
    if not diagram:
        print(f"  WARNING: Could not get diagram object for ID {diagram_id}")
        return []

    # Sanitize diagram name for filesystem compatibility
    diagram_name = sanitize_filename(diagram_info["diagram_name"])

    # Build nested directory structure from package hierarchy
    package_path = diagram_info.get("package_path", [diagram_info["package_name"]])
    sanitized_path_components = [sanitize_filename(pkg) for pkg in package_path]

    # Create nested package directory structure
    package_dir = Path(output_dir)
    for component in sanitized_path_components:
        package_dir = package_dir / component
    package_dir.mkdir(parents=True, exist_ok=True)

    results = []
    for fmt in formats:
        # Determine file extension and type code
        fmt_lower = fmt.lower()
        if fmt_lower == "svg":
            ext = "svg"
            file_type_code = 5
            max_wait = 5
        elif fmt_lower == "png":
            ext = "png"
            file_type_code = 3
            max_wait = 2
        elif fmt_lower == "bmp":
            ext = "bmp"
            file_type_code = 0
            max_wait = 2
        elif fmt_lower in ["jpg", "jpeg"]:
            ext = "jpg"
            file_type_code = 1
            max_wait = 2
        else:
            print(f"WARNING: Unsupported format {fmt}, skipping")
            continue

        # Build output path
        output_path = package_dir / f"{diagram_name}.{ext}"

        # Convert to Windows path (Wine Z: drive on Linux, native on Windows)
        abs_path = str(output_path.absolute())
        windows_output_path = convert_to_windows_path(abs_path)

        try:
            # Open diagram programmatically
            repo.OpenDiagram(diagram.DiagramID)
            time.sleep(0.1)

            # Try to refresh the diagram
            try:
                diagram.RepositionDiagramObject(0, True)
            except Exception as e:
                print(f"  {type(e).__name__}: {e}")

            time.sleep(0.05)

            # Get the Project interface for export
            project = repo.GetProjectInterface()

            # Use PutDiagramImageToFile method
            # Signature: PutDiagramImageToFile(DiagramGUID, FileName, FileType)
            # FileType: 0=BMP, 1=JPEG, 2=GIF, 3=PNG, 5=SVG
            project.PutDiagramImageToFile(diagram.DiagramGUID, windows_output_path, file_type_code)

            # Wait for file to be written
            wait_interval = 0.2
            waited = 0

            while waited < max_wait:
                if Path(output_path).exists():
                    break
                time.sleep(wait_interval)
                waited += wait_interval

            # Check if file was created
            if Path(output_path).exists():
                file_size = Path(output_path).stat().st_size
                print(f"  Exported: {output_path} ({file_size} bytes)")
                results.append(str(output_path))
            else:
                if file_type_code == 5:  # SVG
                    print(f"  SKIPPED: {ext.upper()} export may not be supported in this EA version")
                else:
                    print(f"  FAILED: {output_path} (waited {waited:.1f}s)")
        except Exception as e:
            print(f"  ERROR exporting {diagram_name} as {fmt}:")
            print(f"    {type(e).__name__}: {e}")

    return results


def main():
    parser = argparse.ArgumentParser(
        description="Export EA diagrams to SVG and PNG via COM API (supports Windows and Linux/Wine)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Windows - Export all diagrams from a model
  python export_diagrams_wine.py --model C:\\path\\to\\model.qea --output .\\diagrams

  # Linux/Wine - Export all diagrams from a model
  wine python.exe export_diagrams_wine.py --model /path/to/model.qea --output ./diagrams

  # Export only PNG format
  python export_diagrams_wine.py --model /path/to/model.qea --output ./diagrams --formats png

  # Filter by package name
  python export_diagrams_wine.py --model /path/to/model.qea --output ./diagrams --package-filter "Core"
        """,
    )

    parser.add_argument(
        "--model",
        required=True,
        help="Path to EA model file (.qea or .eap). On Linux, Unix paths are auto-converted to Wine Z: drive.",
    )

    parser.add_argument("--output", help="Output directory for exported diagrams (required unless --list-only)")

    parser.add_argument(
        "--formats",
        nargs="+",
        default=["png"],
        choices=["svg", "png", "bmp", "jpg"],
        help="Export formats (default: png). Note: SVG may not be supported in all EA versions.",
    )

    parser.add_argument(
        "--package-filter", help="Only export diagrams from packages containing this string (case-insensitive)"
    )

    parser.add_argument(
        "--diagram-filter", help="Only export diagrams with names containing this string (case-insensitive)"
    )

    parser.add_argument("--diagram-guid", help="Only export diagram(s) with this exact GUID (case-insensitive)")

    parser.add_argument("--list-only", action="store_true", help="List diagrams without exporting")

    args = parser.parse_args()

    # Validate arguments
    if not args.list_only and not args.output:
        parser.error("--output is required unless --list-only is specified")

    if not args.model:
        parser.error("--model is required")

    # Open repository
    repo = open_repository(args.model)

    # Get all diagrams
    print("\nDiscovering diagrams...")
    all_diagrams = get_all_diagrams(repo)
    print(f"Found {len(all_diagrams)} diagrams")

    # Apply filters
    filtered_diagrams = all_diagrams

    if args.package_filter:
        # Filter by any package in the hierarchy path
        filtered_diagrams = [
            d
            for d in filtered_diagrams
            if any(args.package_filter.lower() in pkg.lower() for pkg in d.get("package_path", [d["package_name"]]))
        ]
        print(f"After package filter: {len(filtered_diagrams)} diagrams")

    if args.diagram_filter:
        filtered_diagrams = [d for d in filtered_diagrams if args.diagram_filter.lower() in d["diagram_name"].lower()]
        print(f"After diagram filter: {len(filtered_diagrams)} diagrams")

    if args.diagram_guid:
        filtered_diagrams = [d for d in filtered_diagrams if args.diagram_guid.lower() in d["diagram_guid"].lower()]
        print(f"After GUID filter: {len(filtered_diagrams)} diagrams")

    # List or export
    if args.list_only:
        print("\nDiagrams:")
        for d in filtered_diagrams:
            # Show full package hierarchy path
            package_path = d.get("package_path", [d["package_name"]])
            full_path = " > ".join(package_path)
            print(f"  [{full_path}] {d['diagram_name']}")
            print(f"    GUID: {d['diagram_guid']}")
            print(f"    ID: {d['diagram_id']}, Type: {d['type']}")
    else:
        print(f"\nExporting {len(filtered_diagrams)} diagrams to {args.output}...")

        # Create output directory
        Path(args.output).mkdir(parents=True, exist_ok=True)

        exported_count = 0
        for i, diagram_info in enumerate(filtered_diagrams, 1):
            # Show full package hierarchy path
            package_path = diagram_info.get("package_path", [diagram_info["package_name"]])
            full_path = "/".join(package_path)
            print(f"\n[{i}/{len(filtered_diagrams)}] {full_path}/{diagram_info['diagram_name']}")
            results = export_diagram(repo, diagram_info, args.output, args.formats)
            if results:
                exported_count += 1

        print(f"\n{'='*60}")
        print(f"Export complete: {exported_count}/{len(filtered_diagrams)} diagrams exported successfully")

    # Close repository
    repo.CloseFile()
    print("\nRepository closed")


if __name__ == "__main__":
    main()
