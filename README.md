# Tacticus

A cross-platform CLI tool to browse and explore Tacticus game API data in an interactive menu interface.

## Features

- **Interactive Data Browser** - Navigate player data, guild data, and raid data with an intuitive CLI menu
- **Tab Completion** - Cross-platform (Windows, Linux, macOS) tab completion for quick navigation
- **Secure API Keys** - Supports environment variables or interactive input for API keys
- **Standalone Executable** - Build into a `.exe` that doesn't require Python to be installed

## Installation

### Option 1: Run as Python Script

1. Clone or download this repository
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Set environment variables for your API keys:
   ```bash
   # Windows (PowerShell)
   $env:TACTICUS_PLAYER_KEY = "your_player_key"
   $env:TACTICUS_GUILD_KEY = "your_guild_key"
   
   # Linux/macOS
   export TACTICUS_PLAYER_KEY="your_player_key"
   export TACTICUS_GUILD_KEY="your_guild_key"
   ```
4. Run the script:
   ```bash
   python tacticus.py
   ```

### Option 2: Build as Standalone Executable

Build a `.exe` (Windows) or standalone executable (Linux/macOS) that doesn't require Python:

**Windows:**
```bash
build.bat
```

**Linux/macOS:**
```bash
chmod +x build.sh
./build.sh
```

The executable will be in the `dist` folder and can be shared with others.

### Option 3: Manual Build with PyInstaller

```bash
pyinstaller --onefile --console --name tacticus tacticus.py
```

## Usage

Once running, the CLI presents three main data sources:
- **Player Data** - Your character, units, inventory, etc.
- **Guild Data** - Guild members, treasury, etc.
- **Guild Raid Data** - Raid statistics and information

### Navigation

- **Type a path** - Enter dictionary keys or list item labels (e.g., `Player Data` or `/player/units`)
- **Press Tab** - Auto-complete available options from the current menu
- **B** - Go back to the previous menu
- **M** - Return to main menu
- **Q** - Quit

### API Key Input

On first run, the tool will:
1. Check for `TACTICUS_PLAYER_KEY` and `TACTICUS_GUILD_KEY` in environment variables
2. Prompt you to enter any missing keys (input is password-masked)
3. Connect to the API and start browsing

## Requirements

- Python 3.7+
- requests
- certifi
- prompt_toolkit

## Built With

This project was built in collaboration with **GitHub Copilot**, leveraging AI-assisted development for rapid prototyping and implementation.

## License

See LICENSE file for details.