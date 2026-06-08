# Building Tacticus as an Executable

To build a standalone `.exe` file (on Windows) or executable (on Linux/macOS), follow these steps:

## Prerequisites

1. Install dependencies:
```bash
pip install -r requirements.txt
```

## Building on Windows

Simply run the build script:
```bash
build.bat
```

The executable will be created in the `dist` folder as `tacticus.exe`.

You can then run it directly:
```bash
dist\tacticus.exe
```

## Building on Linux/macOS

Make the script executable and run it:
```bash
chmod +x build.sh
./build.sh
```

The executable will be created in the `dist` folder as `tacticus`.

You can then run it:
```bash
./dist/tacticus
```

## Manual Build

If the scripts don't work, you can manually build with PyInstaller:

```bash
pyinstaller --onefile --console --name tacticus tacticus.py
```

This creates a self-contained executable that doesn't require Python to be installed on the end user's machine.

## Distributing

The executable in the `dist` folder can be shared with others. They don't need to have Python installed to run it!

**Note:** On first run, the executable will take a moment longer to start as it unpacks the bundled Python environment.
