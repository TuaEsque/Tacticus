#!/bin/bash
# Build script to create tacticus executable using PyInstaller

echo "Building Tacticus executable..."
echo

# Check if PyInstaller is installed
python -m pip show pyinstaller > /dev/null 2>&1
if [ $? -ne 0 ]; then
    echo "PyInstaller not found. Installing..."
    python -m pip install pyinstaller
fi

# Build the executable
pyinstaller --onefile --console --name tacticus tacticus.py

echo
echo "Build complete! The executable is in the 'dist' folder."
echo "You can now run: ./dist/tacticus"
