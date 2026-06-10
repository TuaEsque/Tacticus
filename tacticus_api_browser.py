import requests
import certifi
import os
import sys
from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion

def SetKeys(key_name):
    key = os.environ.get(key_name)
    return key

url = "https://api.tacticusgame.com/api/v1"
s = requests.Session()
s.verify = certifi.where()


def get_api_keys():
    """
    Gets API keys from environment variables or prompts user for input.
    Checks environment variables first, then prompts user if not found.
    Returns tuple of (player_key, guild_key)
    """
    from prompt_toolkit import prompt as tk_prompt
    
    print("\n" + "=" * 50)
    print("API Key Configuration")
    print("=" * 50)
    
    # Try to get from environment first
    player_key = os.environ.get("TACTICUS_PLAYER_KEY")
    guild_key = os.environ.get("TACTICUS_GUILD_KEY")
    
    # Prompt for player key if not found in env
    if not player_key:
        print("\nTACTICUS_PLAYER_KEY not found in environment variables.")
        player_key = tk_prompt("Enter your Tacticus Player API Key: ", is_password=True)
    else:
        print("TACTICUS_PLAYER_KEY found in environment variables")
    
    # Prompt for guild key if not found in env
    if not guild_key:
        print("TACTICUS_GUILD_KEY not found in environment variables.")
        guild_key = tk_prompt("Enter your Tacticus Guild API Key: ", is_password=True)
    else:
        print("TACTICUS_GUILD_KEY found in environment variables")
    
    if not player_key or not guild_key:
        print("\nError: API keys are required to proceed.")
        sys.exit(1)
    
    print("\n" + "=" * 50)
    print("Connecting to API...\n")
    
    return player_key, guild_key


def get_item_label(item, fallback_idx):
    """
    Looks for a descriptive key inside a dictionary to use as a label.
    Returns a string identifier and a boolean indicating if it found a real key name.
    """
    if not isinstance(item, dict):
        return str(item)[:15], False

    # High-priority keys to check for human-readable labels
    priority_keys = ["name", "battleindex"]

    # Case-insensitive check for common identifier keys
    for key in item.keys():
        if str(key).lower() == "battleindex":
            return f"Battle #{fallback_idx}", True
        elif str(key).lower() in priority_keys:
            return str(item[key]), True

    # Lower-priority fallback: pick the first key available in the dictionary
    if item:
        first_key = next(iter(item))
        return f"{first_key}:{item[first_key]}", True

    return f"Item #{fallback_idx}", False


class PathCompleter(Completer):
    """
    A completer that suggests paths based on the current node in the menu.
    Works cross-platform on Windows, Linux, and macOS.
    """
    def __init__(self, data, current_node=None):
        self.data = data
        self.current_node = current_node if current_node is not None else data
    
    def update_current_node(self, current_node):
        """Update the current node context for completions."""
        self.current_node = current_node
    
    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        prefix = text.strip()
        
        try:
            # Complete from the current node if the input is just a key/label
            if '/' not in text:
                target_node = self.current_node
            else:
                # If input contains '/', navigate from current node
                target_node, _ = parse_path(self.data, text, self.current_node)
                if target_node is None:
                    return
                prefix = ""
            
            # Get available completions
            if isinstance(target_node, dict):
                for key in target_node.keys():
                    if key.lower().startswith(prefix.lower()):
                        completion_text = key[len(prefix):]
                        yield Completion(completion_text, start_position=-len(prefix))
            elif isinstance(target_node, list):
                for idx, item in enumerate(target_node):
                    label, is_attr = get_item_label(item, idx + 1)
                    if label.lower().startswith(prefix.lower()):
                        completion_text = label[len(prefix):]
                        yield Completion(completion_text, start_position=-len(prefix))
        except Exception:
            # Silently handle any errors during completion
            return


def create_path_completer(data, current_node=None):
    """
    Creates a PathCompleter instance for the given data structure.
    """
    return PathCompleter(data, current_node)


def parse_path(data, path_str, current_node=None, current_path=""):
    """
    Navigates to a specific path in the data structure using generated path format.
    Path format: "/key1/itemLabel/key2" where list items are identified by their label.
    Relative paths are resolved from current_node if provided.
    Returns a tuple: (target_node, normalized_path) or (None, "") on failure.
    """
    if not path_str or path_str == "/":
        return data, ""
    
    # If path starts with "/", it's absolute; otherwise it's relative to current_node
    if path_str.startswith("/"):
        start_node = data
        start_path = ""
        parts = [p for p in path_str.split("/") if p]
    else:
        start_node = current_node if current_node is not None else data
        start_path = current_path if current_path else ""
        parts = [p for p in path_str.split("/") if p]
    
    current_node = start_node
    current_path = start_path
    
    for part in parts:
        # Try to interpret as a list
        if isinstance(current_node, list):
            # First try as numeric index
            try:
                idx = int(part)
                if 0 <= idx < len(current_node):
                    label, is_attr = get_item_label(current_node[idx], idx + 1)
                    current_node = current_node[idx]
                    current_path += f"/{label}" if is_attr else f"/{idx}"
                else:
                    print(f"Error: Index {idx} out of range for list of length {len(current_node)}")
                    return None, ""
            except ValueError:
                # Not a number, search for matching label
                found = False
                for idx, item in enumerate(current_node):
                    label, is_attr = get_item_label(item, idx + 1)
                    if label == part:
                        current_node = item
                        current_path += f"/{label}"
                        found = True
                        break
                
                if not found:
                    print(f"Error: No item with label '{part}' found in list")
                    return None, ""
        
        # Try dictionary key
        elif isinstance(current_node, dict):
            if part in current_node:
                current_node = current_node[part]
                current_path += f"/{part}"
            else:
                print(f"Error: Key '{part}' not found in current dictionary")
                return None, ""
        
        # Can't navigate further if not dict or list
        else:
            print(f"Error: Cannot navigate into leaf node at '{current_path}'")
            return None, ""
    
    return current_node, current_path


def run_cli_menu(data):
    history = []
    current_node = data
    current_path = ""
    
    # Set up tab completion with prompt_toolkit (cross-platform)
    completer = create_path_completer(data, current_node)
    session = PromptSession(completer=completer)

    while True:
        # Update completer with current node
        completer.update_current_node(current_node)
        
        print("\n" + "=" * 50)
        display_path = current_path if current_path else "/"
        print(f"Location: {display_path}")
        print("=" * 50)

        # --- SCENARIO 1: DICTIONARY ---
        if isinstance(current_node, dict):
            keys = list(current_node.keys())
            print("Available categories:")
            for key in keys:
                print(f"  • {key}")
            print()

        # --- SCENARIO 2: LIST ---
        elif isinstance(current_node, list):
            print(f"List of {len(current_node)} item(s):")
            for idx, item in enumerate(current_node, 1):
                label, is_attr = get_item_label(item, idx)
                if is_attr:
                    print(f"  • {label}")
                else:
                    print(f"  • Item #{idx} ({label})")
            print()

        # --- SCENARIO 3: LEAF NODE ---
        else:
            print(f"Value: {current_node}")
            print()

        # Standard Navigation Options
        if history:
            print(" B) Go Back")
        print(" M) Main Menu")
        print(" Q) Quit")
        print(" Or enter a path (e.g., /player/units/Tigurius/xpLevel)")

        choice = session.prompt("\nEnter command or path: ").strip()
        choice_upper = choice.upper()

        # Handle Global Navigation Commands
        if choice_upper == 'Q':
            sys.exit("Goodbye!")
        elif choice_upper == 'M':
            current_node = data
            current_path = ""
            history.clear()
            continue
        elif choice_upper == 'B' and history:
            current_node, current_path = history.pop()
            continue
        else:
            # Treat input as a path
            target_node, target_path = parse_path(data, choice, current_node, current_path)
            if target_node is not None:
                history.append((current_node, current_path))
                current_node = target_node
                current_path = target_path
            continue


def main():
    # Get API keys (from env vars or user input)
    player_key, guild_key = get_api_keys()
    
    # Create headers with the retrieved keys
    player_headers = {
        "x-api-key": player_key
    }
    guild_headers = {
        "x-api-key": guild_key
    }
    
    # Fetch data from API
    playerData = s.get(url=f"{url}/player", headers=player_headers).json()
    guildData = s.get(url=f"{url}/guild", headers=guild_headers).json()
    guildRaidData = s.get(url=f"{url}/guildRaid", headers=guild_headers).json()
    
    # Create a parent menu structure containing all three data sources
    parent_data = {
        "Player Data": playerData,
        "Guild Data": guildData,
        "Guild Raid Data": guildRaidData
    }
    
    run_cli_menu(parent_data)


if __name__ == "__main__":
    main()
    quit()