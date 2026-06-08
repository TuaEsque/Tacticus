@echo off
REM Build script to create tacticus.exe using PyInstaller

echo Building Tacticus executable...
echo.

REM Check if PyInstaller is installed
python -m pip show pyinstaller >nul 2>&1
if errorlevel 1 (
    echo PyInstaller not found. Installing...
    python -m pip install pyinstaller
)

REM Build the executable
pyinstaller --onefile --console --name tacticus --hidden-import=prompt_toolkit tacticus.py

echo.
echo Build complete! The executable is in the 'dist' folder.
echo You can now run: dist\tacticus.exe
pause
