import os
import certifi
import requests
from prompt_toolkit import prompt as tk_prompt


API_BASE_URL = "https://api.tacticusgame.com/api/v1"


def get_api_keys():
    """
    Gets API keys from environment variables or prompts the user for input.
    Checks environment variables first, then prompts the user if not found.
    Returns a tuple of (player_key, guild_key).
    """
    print("\n" + "=" * 50)
    print("API Key Configuration")
    print("=" * 50)

    player_key = os.environ.get("TACTICUS_PLAYER_KEY")
    guild_key = os.environ.get("TACTICUS_GUILD_KEY")

    if not player_key:
        print("\nTACTICUS_PLAYER_KEY not found in environment variables.")
        player_key = tk_prompt("Enter your Tacticus Player API Key: ", is_password=True)
    else:
        print("TACTICUS_PLAYER_KEY found in environment variables")

    if not guild_key:
        print("TACTICUS_GUILD_KEY not found in environment variables.")
        guild_key = tk_prompt("Enter your Tacticus Guild API Key: ", is_password=True)
    else:
        print("TACTICUS_GUILD_KEY found in environment variables")

    if not player_key or not guild_key:
        print("\nError: API keys are required to proceed.")
        raise SystemExit(1)

    print("\n" + "=" * 50)
    print("Connecting to API...\n")

    return player_key, guild_key


def create_session():
    """Create a requests session configured for the Tacticus API."""
    session = requests.Session()
    session.verify = certifi.where()
    return session


def fetch_guild_raid_data():
    """Fetch only the guild raid endpoint data."""
    _, guild_key = get_api_keys()
    session = create_session()
    guild_headers = {"x-api-key": guild_key}
    return session.get(url=f"{API_BASE_URL}/guildRaid", headers=guild_headers).json()


def fetch_tacticus_data():
    """Fetch the core Tacticus API data used by the browser."""
    player_key, guild_key = get_api_keys()
    session = create_session()

    player_headers = {"x-api-key": player_key}
    guild_headers = {"x-api-key": guild_key}

    player_data = session.get(url=f"{API_BASE_URL}/player", headers=player_headers).json()
    guild_data = session.get(url=f"{API_BASE_URL}/guild", headers=guild_headers).json()
    guild_raid_data = session.get(url=f"{API_BASE_URL}/guildRaid", headers=guild_headers).json()

    return {
        "Player Data": player_data,
        "Guild Data": guild_data,
        "Guild Raid Data": guild_raid_data,
    }