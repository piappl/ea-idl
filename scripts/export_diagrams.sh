#!/bin/bash
# Helper script to run diagram export
#
# This script automatically detects the platform and runs the Python export script:
# - On Windows: Uses native Python
# - On Linux/macOS: Uses Wine with 32-bit Python

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EXPORT_SCRIPT="${SCRIPT_DIR}/export_diagrams_wine.py"

# Detect platform
case "$(uname -s)" in
    CYGWIN*|MINGW*|MSYS*|Windows_NT)
        # Windows (Git Bash, Cygwin, etc.)
        echo "Detected Windows - using native Python"
        python "$EXPORT_SCRIPT" "$@"
        ;;
    Linux|Darwin)
        # Linux or macOS - use Wine
        echo "Detected Unix-like OS - using Wine"

        # Wine environment setup (32-bit)
        # export WINEPREFIX="${WINEPREFIX:-$HOME/.wine32}"
        # export WINEARCH=win32

        # Path to Wine Python (customize if needed)
        WINE_PYTHON="${WINE_PYTHON:-C:\\users\\${USER}\\AppData\\Local\\Programs\\Python\\Python313-32\\python.exe}"

        # Convert to Wine Z: path
        WINE_EXPORT_SCRIPT="Z:${EXPORT_SCRIPT}"

        # Run the export script with Wine Python
        wine "$WINE_PYTHON" "$WINE_EXPORT_SCRIPT" "$@"
        ;;
    *)
        echo "Unknown platform: $(uname -s)"
        echo "Please run the Python script directly or modify this script for your platform."
        exit 1
        ;;
esac
