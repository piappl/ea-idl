# Enterprise Architect Diagram Export

This directory contains scripts to export diagrams from Enterprise Architect (EA) using the COM API. The scripts support both **native Windows** and **Linux/macOS with Wine**.

## Platform-Specific Setup

### Windows Setup

On Windows, you need:
1. **Python 3.x** (32-bit or 64-bit) - [Download from python.org](https://www.python.org/downloads/)
2. **pywin32** - Install with: `pip install pywin32`
3. **Enterprise Architect** installed
4. Post-install pywin32: `python -m pywin32_postinstall -install`

### Linux/macOS Setup (Wine)

## Use wine from WineHQ

https://gitlab.winehq.org/wine/wine/-/wikis/Debian-Ubuntu

## Proper env

We use 32 bit here, always make sure:

```sh
export WINEPREFIX=~/.wine32
export WINEARCH=win32
```

## Install

```sh
export WINEPREFIX=~/.wine32
export WINEARCH=win32
# This initializes the new 32-bit prefix
winecfg
winetricks msxml3 msxml6

wine ~/Downloads/python-3.13.9.exe
wine ~/Downloads/easetup_x84.exe
wine 'C:\\Program Files (x86)\\Sparx Systems\\EA\\EA.exe'


#wine 'C:\\Program Files\\Python3x\\python.exe'
wine 'C:\\users\\mmacias\\AppData\\Local\\Programs\\Python\\Python313-32\\python.exe'


wine Z:\\home\\mmacias\\.wine32\\drive_c\\users\\mmacias\\AppData\\Local\\Programs\\Python\\Python313-32\\python.exe -m ensurepip --upgrade
wine Z:\\home\\mmacias\\.wine32\\drive_c\\users\\mmacias\\AppData\\Local\\Programs\\Python\\Python313-32\\python.exe -m pip install pywin32
wine Z:\\home\\mmacias\\.wine32\\drive_c\\users\\mmacias\\AppData\\Local\\Programs\\Python\\Python313-32\\Scripts\\pywin32_postinstall.exe -install -silent


# WARNING: The scripts pywin32_postinstall.exe and pywin32_testall.exe are installed in 'Z:\home\mmacias\.wine32\drive_c\users\mmacias\AppData\Local\Programs\Python\Python313-32\Scripts' which is not on PATH.
# Consider adding this directory to PATH or, if you prefer to suppress this warning, use --no-warn-script-location.

#WINEPATH="/home/mmacias/.wine32/drive_c/users/mmacias/AppData/Local/Programs/Python/Python313-32/:Z:\home\mmacias\.wine32\drive_c\users\mmacias\AppData\Local\Programs\Python\Python313-32\Scripts"
#wine 'w'
```

Install NAFv4.

## Test

wine 'C:\\users\\mmacias\\AppData\\Local\\Programs\\Python\\Python313-32\\python.exe'

```python
import sys
import win32com.client
# app = win32com.client.GetActiveObject("EA.App")
app = win32com.client.Dispatch('EA.Repository')
path = "Z:\\home\\user\\model.qea"
app.OpenFile2(path, "", "")
app.Models.Count
```

## Export Diagrams via COM API

The `export_diagrams_wine.py` script exports diagrams from EA to SVG and PNG formats using the COM API. **This script now supports both native Windows and Linux/Wine environments** - it automatically detects the platform and adjusts paths accordingly.

### Usage

**Method 1: Using the helper script (recommended, cross-platform):**
```sh
./export_diagrams.sh --model /path/to/model.qea --output ./diagrams
```

The helper script automatically detects your platform:
- On **Windows**: Uses native Python
- On **Linux/macOS**: Uses Wine with 32-bit Python

**Method 2: Direct Python execution:**

On Windows:
```sh
python export_diagrams_wine.py --model C:\path\to\model.qea --output .\diagrams
```

On Linux with Wine:
```sh
export WINEPREFIX=~/.wine32
export WINEARCH=win32
wine 'C:\\users\\mmacias\\AppData\\Local\\Programs\\Python\\Python313-32\\python.exe' export_diagrams_wine.py --model /path/to/model.qea --output ./diagrams
```

### Options

- `--model PATH` - Path to EA model file (.qea or .eap) - **required**
- `--output DIR` - Output directory for exported diagrams (required unless --list-only)
- `--formats png svg bmp jpg` - Export formats (default: png). Note: SVG may not be supported in all EA versions.
- `--package-filter TEXT` - Only export diagrams from packages containing this text
- `--diagram-filter TEXT` - Only export diagrams with names containing this text
- `--diagram-guid GUID` - Only export diagram(s) with this exact GUID
- `--list-only` - List diagrams without exporting
- `--use-running-ea` - Connect to already-running EA instance for better compatibility

### Notes

- **SVG Export**: SVG export via COM API is **not supported in most EA builds**. The script defaults to PNG which works reliably. You can try SVG with `--formats svg`, but it will likely fail.
  - Never EA build could help: https://sparxsystems.com/forums/smf/index.php?topic=47773.0
- **Supported Formats**: PNG, BMP, and JPG work reliably. **PNG is recommended** for best quality and transparency support.
- **MDG Styling**: Ensure your MDG (e.g., NAFv4) is properly installed in EA. The script will use MDG styling automatically if:
  - The MDG is installed and enabled in your EA installation
  - The model file has the MDG technology applied

  Optionally, you can use `--use-running-ea` to connect to an already-running EA instance, though this is usually not necessary if the MDG is properly installed.

### Examples

List all diagrams:
```sh
./export_diagrams.sh --model path/to/model.qea  --list-only
```

Export all diagrams (PNG format):
```sh
./export_diagrams.sh --model path/to/model.qea  --output ./diagrams
```

Export multiple formats:
```sh
./export_diagrams.sh --model path/to/model.qea  --output ./diagrams --formats png jpg
```

Export diagrams from "Core" package only:
```sh
./export_diagrams.sh --model path/to/model.qea  --output ./diagrams --package-filter "Core"
```

Export a specific diagram by GUID:
```sh
./export_diagrams.sh --model path/to/model.qea  --output ./diagrams --diagram-guid "{GUID-HERE}"
```

Export from a running EA instance (recommended if you encounter issues):
```sh
# First open EA, then:
./export_diagrams.sh --use-running-ea --model ~/model.qea --output ./diagrams
```

### Platform Notes

The script automatically handles platform differences:
- **Path conversion**: On Linux/Wine, Unix paths (`/path/to/file`) are automatically converted to Wine Z: drive format (`Z:\path\to\file`). On Windows, paths are used as-is.
- **Python environment**: The helper script (`export_diagrams.sh`) detects your platform and uses the appropriate Python interpreter.
- **No code changes needed**: The same Python script works on both platforms without modification.

### Output Structure

The exported diagrams are organized in a nested directory structure that mirrors the EA package hierarchy:

```
output_dir/
├── Model1/
│   ├── Package1/
│   │   ├── SubPackage1/
│   │   │   └── diagram1.png
│   │   └── diagram2.png
│   └── Package2/
│       └── diagram3.png
└── Model2/
    └── ...
```

- Each package in the hierarchy becomes a directory
- All package and diagram names are sanitized to be filesystem-safe (removes characters like `<`, `>`, `:`, `"`, `/`, `\`, `|`, `?`, `*`, etc.)
- Windows reserved names (like `CON`, `PRN`, `AUX`, `COM1`, etc.) are prefixed with `_`
