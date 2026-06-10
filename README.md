# Tacticus

A cross-platform CLI tool to browse and explore Tacticus game API data in an interactive menu interface.

## Features

- **Interactive Data Browser** - Navigate player data, guild data, and raid data with an intuitive CLI menu
- **Tab Completion** - Cross-platform (Windows, Linux, macOS) tab completion for quick navigation
- **Secure API Keys** - Supports environment variables or interactive input for API keys
- **Guild Raid Analyzer** - Export and review guild raid damage by user, boss type, rarity, and damage type

## Structure

The project is split into three small scripts:

- [tacticus_api_client.py](tacticus_api_client.py) - shared API access layer with `get_api_keys()`, `create_session()`, `fetch_tacticus_data()`, and `fetch_guild_raid_data()`
- [tacticus_api_browser.py](tacticus_api_browser.py) - interactive menu browser for the player, guild, and raid data trees
- [tacticus_guild_raid_analyzer.py](tacticus_guild_raid_analyzer.py) - guild raid reporting tool with optional user filtering and local JSON/XML export

## Installation

### API Browser

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
   python tacticus_api_browser.py
   ```

### Guild Raid Analysis

The analyzer fetches the `guildRaid` endpoint through the shared API client, groups the data by user, boss type, rarity, and damage type, and writes the full analysis to local JSON and XML files.

Run it with:

```bash
python tacticus_guild_raid_analyzer.py
```

Filter the report to one userId:

```bash
python tacticus_guild_raid_analyzer.py --user-id 75bcd109-9822-43fa-a75e-f9a8e251338e
```

Choose a different export file base name if needed:

```bash
python tacticus_guild_raid_analyzer.py --output my_guild_raid_analysis.json
```

Battle entries include the team composition in the exported JSON and XML, using `heroDetails` and `machineOfWarDetails`.

## Usage

Once running, the CLI presents three main data sources:
- **Player Data** - Your character, units, inventory, etc.
- **Guild Data** - Guild members, treasury, etc.
- **Guild Raid Data** - Raid statistics and information

The browser uses `fetch_tacticus_data()` from [tacticus_api_client.py](tacticus_api_client.py) to load the three top-level data trees at runtime.

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