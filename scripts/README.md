# Enterprise Architect Diagram Export

Export diagrams from Enterprise Architect (EA) using the COM API. The scripts support both **native Windows** and **Linux/macOS with Wine**.

## Platform-Specific Setup

### Windows Setup

Requirements:
1. **Python 3.x** (32-bit or 64-bit) - [Download from python.org](https://www.python.org/downloads/)
2. **pywin32** - Install with: `pip install pywin32`
3. **Enterprise Architect** installed
4. Post-install pywin32: `python -m pywin32_postinstall -install`

### Linux/macOS Setup (Wine)

#### Install Wine from WineHQ

Follow instructions at: https://gitlab.winehq.org/wine/wine/-/wikis/Debian-Ubuntu

#### Setup 32-bit Wine Environment

Always set these environment variables:

```sh
export WINEPREFIX=~/.wine32
export WINEARCH=win32
```

#### Installation Steps

```sh
export WINEPREFIX=~/.wine32
export WINEARCH=win32

# Initialize the 32-bit Wine prefix
winecfg
winetricks msxml3 msxml6

# Install Python 3.13 32-bit and Enterprise Architect
wine ~/Downloads/python-3.13.9.exe
# wine ~/Downloads/easetup_x86.exe
wine ~/easetupfull_x86.msi

# Install Python packages (adjust path to your Python installation)
PYTHON_PATH='C:\\users\\${USER}\\AppData\\Local\\Programs\\Python\\Python313-32'
wine "${PYTHON_PATH}\\python.exe" -m ensurepip --upgrade
wine "${PYTHON_PATH}\\python.exe" -m pip install pywin32
wine "${PYTHON_PATH}\\Scripts\\pywin32_postinstall.exe" -install -silent
```

**Note**: Install your MDG (e.g., NAFv4) in EA after installation.

```sh
WINEPREFIX=/home/mmacias/.wine32 WINEARCH=win32  wine 'C:\\\Program Files\\\Sparx Systems\\\EA\\\EA.exe'
```


#### Test Installation

```sh
wine 'C:\\users\\${USER}\\AppData\\Local\\Programs\\Python\\Python313-32\\python.exe'
```

```python
import win32com.client
app = win32com.client.Dispatch('EA.Repository')
path = "Z:\\home\\user\\model.qea"
app.OpenFile2(path, "", "")
print(app.Models.Count)
```

## Export Diagrams via COM API

The `export_diagrams_wine.py` script exports diagrams from EA using the COM API. It supports both native Windows and Linux/Wine environments and automatically detects the platform.

### Usage

**Recommended: Use the helper script**

```sh
./export_diagrams.sh --model /path/to/model.qea --output ./diagrams
```

The helper script automatically detects your platform and uses the appropriate Python interpreter.

**Alternative: Direct Python execution**

Windows:
```sh
python export_diagrams_wine.py --model C:\path\to\model.qea --output .\diagrams
```

Linux with Wine:
```sh
export WINEPREFIX=~/.wine32
export WINEARCH=win32
wine 'C:\\users\\${USER}\\AppData\\Local\\Programs\\Python\\Python313-32\\python.exe' export_diagrams_wine.py --model /path/to/model.qea --output ./diagrams
```

### Options

- `--model PATH` - Path to EA model file (.qea or .eap) - **required**
- `--output DIR` - Output directory for exported diagrams (required unless --list-only)
- `--formats png svg bmp jpg` - Export formats (default: png). Note: SVG may not be supported in all EA versions.
- `--package-filter TEXT` - Only export diagrams from packages containing this text
- `--diagram-filter TEXT` - Only export diagrams with names containing this text
- `--diagram-guid GUID` - Only export diagram(s) with this exact GUID
- `--list-only` - List diagrams without exporting

### Notes

- **SVG Export**: SVG export via COM API is **not supported in most EA builds**. The script defaults to PNG which works reliably. You can try SVG with `--formats svg`, but it will likely fail.
  - Newer EA builds may have better SVG support: https://sparxsystems.com/forums/smf/index.php?topic=47773.0
- **Supported Formats**: PNG, BMP, and JPG work reliably. **PNG is recommended** for best quality and transparency support.
- **MDG Styling**: Ensure your MDG (e.g., NAFv4) is properly installed in EA. The script will use MDG styling automatically if the MDG is installed and enabled in your EA installation and the model file has the MDG technology applied.

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

### Platform Notes

The script automatically handles platform differences:
- **Path conversion**: Unix paths are automatically converted to Wine Z: drive format on Linux
- **Python environment**: The helper script detects your platform and uses the appropriate Python interpreter
- **Cross-platform**: The same Python script works on both platforms without modification

### Output Structure

Exported diagrams are organized in a nested directory structure mirroring the EA package hierarchy:

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

- Each package becomes a directory
- Names are sanitized to be filesystem-safe
- Windows reserved names (CON, PRN, AUX, COM1, etc.) are prefixed with `_`
