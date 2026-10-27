import os
import certifi
import requests
from prompt_toolkit import prompt as tk_prompt


API_BASE_URL = "https://api.tacticusgame.com/api/v1"
REQUEST_TIMEOUT_SECONDS = 15


class TacticusApiError(RuntimeError):
    """Raised when an API request fails or returns a non-2xx response."""

    def __init__(self, path, status=None, detail=None):
        self.path = path
        self.status = status
        self.detail = detail
        status_text = f"HTTP {status}" if status is not None else "request failed"
        detail_text = f" ({detail})" if detail else ""
        super().__init__(f"{path}: {status_text}{detail_text}")


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


def get_json(session, path, api_key):
    """
    GET an API path and return the decoded JSON body.

    Raises TacticusApiError on network failure, non-2xx status or a non-JSON
    body. Error bodies look like {"type": "FORBIDDEN"}, so the type is surfaced.
    """
    try:
        response = session.get(
            url=f"{API_BASE_URL}{path}",
            headers={"x-api-key": api_key},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        raise TacticusApiError(path, detail=str(exc)) from exc

    if not response.ok:
        try:
            error_type = response.json().get("type")
        except (ValueError, AttributeError):
            error_type = None
        raise TacticusApiError(path, response.status_code, error_type)

    try:
        return response.json()
    except ValueError as exc:
        raise TacticusApiError(path, response.status_code, "response was not JSON") from exc


def fetch_player(session, player_key):
    """Fetch /player (roster, inventory and raid token state)."""
    return get_json(session, "/player", player_key)


def fetch_guild_raid(session, guild_key):
    """Fetch /guildRaid for the current season."""
    return get_json(session, "/guildRaid", guild_key)


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