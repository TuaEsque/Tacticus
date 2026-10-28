# Tacticus

A cross-platform CLI tool to browse and explore Tacticus game API data in an interactive menu interface.

## Features

- **Interactive Data Browser** - Navigate player data, guild data, and raid data with an intuitive CLI menu
- **Tab Completion** - Cross-platform (Windows, Linux, macOS) tab completion for quick navigation
- **Secure API Keys** - Supports environment variables or interactive input for API keys
- **Guild Raid Analyzer** - Export and review guild raid damage by user, boss type, rarity, and damage type
- **Guild Raid Advisor & Overlay** - Always-on-top window that recommends your next raid move: what to attack, which team to use, and when to bomb

## Structure

The project is split into small scripts:

- [tacticus_api_client.py](tacticus_api_client.py) - shared API access layer with `get_api_keys()`, `create_session()`, `fetch_tacticus_data()`, `fetch_guild_raid_data()`, and the error-checked `get_json()`, `fetch_player()` and `fetch_guild_raid()`
- [tacticus_api_browser.py](tacticus_api_browser.py) - interactive menu browser for the player, guild, and raid data trees
- [tacticus_guild_raid_analyzer.py](tacticus_guild_raid_analyzer.py) - guild raid reporting tool with optional user filtering and local JSON/XML export
- [tacticus_raid_advisor.py](tacticus_raid_advisor.py) - pure decision logic (no network or UI) plus a terminal CLI
- [tacticus_raid_overlay.py](tacticus_raid_overlay.py) - Tkinter overlay window that displays the advisor's output and refreshes it

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

Before running the analyzer, install the project dependencies:

```bash
pip install -r requirements.txt
```

The analyzer uses the same dependencies as the browser, so no extra packages are required beyond `requests`, `certifi`, and `prompt_toolkit`.

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

### Raid to XLSX

Using the XML data fetched by the Guild Raid Analyzer script, this script generates an Excel (or Google Sheets) spreadsheet that visualises the data.

Before running the analyzer, install the project dependencies:

```bash
pip install -r requirements.txt
```

Run it with:

```bash
python tacticus_raid_to_xlsx.py.py
```

### Guild Raid Advisor & Overlay

The overlay is a small borderless window that stays on top of the game. It polls the API and shows:

- **Next moves**: a bomb finisher if one is available, which encounter to battle, and whether to hold your bomb
- **Encounters**: HP of the current boss and its primes, including battles still in progress
- **Best teams** against the recommended target, ranked by average damage
- **Live token countdown** for raid tokens and bombs

**Requirements**

- **Both API keys.** The player key supplies your token counts and roster. The guild key needs the *Guild Raid* scope, which only a guild **Leader or Co-leader** can create.
- **Your userId**, so the advisor can rank your own teams. It is the `userId` shown in the Guild Raid Analyzer output. Pass it with `--user-id` or set `TACTICUS_USER_ID`.
- **Tkinter.** It ships with Python on Windows and macOS. On Debian/Ubuntu, install it with `sudo apt install python3-tk`.

Run the overlay:

```bash
python tacticus_raid_overlay.py --user-id <your-user-id>
```

Options: `--refresh 120` (seconds between API calls, minimum 30), `--opacity 0.9`, and `--framed` (keeps the normal window frame, useful where a borderless window misbehaves). Drag the title bar to move the window. **F5** refreshes and **Esc** closes it. Run the game windowed or borderless; exclusive fullscreen draws over every other window.

To print the same advice once in the terminal (handy on mobile, or for scripting):

```bash
python tacticus_raid_advisor.py --user-id <your-user-id>
```

To try either script without API keys, use the bundled synthetic sample data:

```bash
python tacticus_raid_overlay.py --raid-file examples/sample_guild_raid.json --player-file examples/sample_player.json --user-id 00000000-0000-4000-8000-000000000001
```

**How it decides**

The aim is to get the most useful damage from every token:

1. **Current encounters** come from the highest `tier`/`set` in this season's raid log. HP comes from the most recently completed attempt. Battles with no `completedOn` are shown as in progress. Once the main boss falls, its primes are no longer targets.
2. **Bomb finisher.** If you have a bomb and an encounter's HP is at or below the *smallest* bomb your guild has thrown at that rarity, the advisor says to bomb it. That kill costs no raid token.
3. **Battle target.** The advisor picks the encounter with the highest `min(expected damage, HP left)`. Damage beyond the HP left is wasted, so a nearly dead encounter scores lower than one that can take your full attack.
4. **Expected damage** is your best team's average against that boss type and rarity. Guild mates' teams are suggested too, but only if you own every hero in them. Killing blows are left out of the averages, because their damage is capped by the HP that was left.
5. **Token hygiene.** It warns when raid tokens are full (regeneration is being wasted). Token timers are projected forward from the API's `lastUpdatedOn`, because player data is cached server-side.

**Limits**

- The API has no live battlefield state, so the advisor cannot suggest moves inside a battle (positioning or ability order).
- The API does not say which heroes you have already used. It also skips faction restrictions, though any team that appears in the raid log was legal against that boss.
- Averages built from one or two battles are noisy, so check the `×N` sample count next to each team.
- Nothing here touches the game client: it reads the official public API and draws its own window. There is no memory reading and no input automation.

### Battle Planner (in progress)

[tacticus_board.py](tacticus_board.py) models a raid battle board that you enter by hand. Nothing is read from the game screen. It currently works out, for each unit:

- **Where it can move:** one move per turn, up to its movement stat. It can pass through allies but not stop on them. Enemies and impassable hexes block, unless it has Flying. Razor wire, ice and fire end the move, unless it has Flying, Unstoppable or Vehicle.
- **What it can attack from there:** melee on adjacent enemies. Ranged needs the target in range and in line of sight, and is unavailable while an enemy is adjacent. Indirect Fire ignores line of sight.

Boss maps are stored as JSON in a growing map bank: terrain per hex, sight-blocking hexes, deployment hexes and known enemy spawn layouts. Hero movement, range and traits are in [data/unit_profiles.json](data/unit_profiles.json); check them against the in-game info panels.

Not modelled yet: elevation and cliffs, bridges, Overwatch, damage, and abilities. Two rules are assumptions until checked in-game:
- units don't block line of sight;
- a line passing exactly between two hexes is blocked only if both hexes block sight.

### Running the tests

```bash
pip install pytest
pytest
```

The overlay tests are skipped automatically when Tkinter or a display is unavailable.

## Usage

Once running the API Browser, the CLI presents three main data sources:
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

This project was built in collaboration with **GitHub Copilot** and **Claude**, leveraging AI-assisted development for rapid prototyping and implementation.

## License

See LICENSE file for details.