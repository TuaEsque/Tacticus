import argparse
import json
from collections import defaultdict
from xml.etree import ElementTree as ET
from pathlib import Path
from tacticus_api_client import fetch_guild_raid_data


def normalize_guild_raid_payload(payload):
    if isinstance(payload, dict) and "entries" in payload:
        return payload["entries"]
    if isinstance(payload, list):
        return payload
    return []


def get_entry_user_key(entry):
    return entry.get("userId", "<unknown user>")


def get_entry_boss_key(entry):
    return entry.get("type") or entry.get("unitId") or "<unknown boss>"


def get_entry_rarity(entry):
    return entry.get("rarity", "<unknown rarity>")


def get_entry_damage_type(entry):
    return entry.get("damageType", "<unknown damage type>")


def get_damage_value(entry):
    return int(entry.get("damageDealt", 0) or 0)


def filter_entries_by_user_id(entries, user_id_query):
    if not user_id_query:
        return entries

    query = user_id_query.strip().lower()
    return [entry for entry in entries if query in str(entry.get("userId", "")).lower()]


def build_team_details(entry):
    hero_details = entry.get("heroDetails") or []
    machine_of_war = entry.get("machineOfWarDetails")

    heroes = []
    for hero in hero_details:
        heroes.append(
            {
                "unitId": hero.get("unitId"),
                "power": hero.get("power"),
            }
        )

    machine = None
    if machine_of_war:
        machine = {
            "unitId": machine_of_war.get("unitId"),
            "power": machine_of_war.get("power"),
        }

    return {
        "heroes": heroes,
        "machineOfWar": machine,
    }


def format_team(entry):
    hero_details = entry.get("heroDetails") or []
    machine_of_war = entry.get("machineOfWarDetails")

    hero_lines = []
    for hero in hero_details:
        unit_id = hero.get("unitId", "<unknown hero>")
        power = hero.get("power", "?")
        hero_lines.append(f"{unit_id} (power {power})")

    if machine_of_war:
        machine_line = f"{machine_of_war.get('unitId', '<unknown machine>')} (power {machine_of_war.get('power', '?')})"
    else:
        machine_line = "None"

    heroes_text = ", ".join(hero_lines) if hero_lines else "None"
    return f"Heroes: {heroes_text}; Machine of War: {machine_line}"


def build_report(entries):
    grouped = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))

    for entry in entries:
        user_key = get_entry_user_key(entry)
        rarity = get_entry_rarity(entry)
        boss_key = get_entry_boss_key(entry)
        damage_type = get_entry_damage_type(entry)

        grouped[user_key][rarity][boss_key].append((damage_type, entry))

    return grouped


def build_analysis(entries, user_id_filter=None):
    grouped = build_report(entries)

    analysis = {
        "source": "guildRaid",
        "userIdFilter": user_id_filter,
        "users": {},
    }

    for user_key in sorted(grouped):
        user_total = 0

        user_data = {
            "totalDamage": 0,
            "rarities": {},
        }

        for rarity in sorted(grouped[user_key]):
            rarity_total = 0

            rarity_data = {
                "totalDamage": 0,
                "bosses": {},
            }

            for boss_key in sorted(grouped[user_key][rarity]):
                entries_for_boss = grouped[user_key][rarity][boss_key]

                boss_total = sum(
                    get_damage_value(entry)
                    for _, entry in entries_for_boss
                )

                rarity_total += boss_total
                user_total += boss_total

                damage_type_buckets = defaultdict(list)

                for damage_type, entry in entries_for_boss:
                    damage_type_buckets[damage_type].append(entry)

                boss_data = {
                    "totalDamage": boss_total,
                    "damageTypes": {},
                }

                for damage_type in sorted(damage_type_buckets):
                    damage_type_entries = damage_type_buckets[damage_type]

                    damage_type_total = sum(
                        get_damage_value(entry)
                        for entry in damage_type_entries
                    )

                    damage_type_data = {
                        "totalDamage": damage_type_total,
                        "entries": [],
                    }

                    for entry in damage_type_entries:
                        entry_data = {
                            "damageDealt": get_damage_value(entry),
                            "damageType": get_entry_damage_type(entry),
                            "encounterType": entry.get("encounterType"),
                            "unitId": entry.get("unitId"),
                            "type": entry.get("type"),
                            "rarity": entry.get("rarity"),
                            "startedOn": entry.get("startedOn"),
                            "completedOn": entry.get("completedOn"),
                        }

                        if damage_type.lower() == "battle":
                            entry_data["team"] = build_team_details(entry)

                        damage_type_data["entries"].append(entry_data)

                    boss_data["damageTypes"][damage_type] = damage_type_data

                rarity_data["bosses"][boss_key] = boss_data

            rarity_data["totalDamage"] = rarity_total
            user_data["rarities"][rarity] = rarity_data

        user_data["totalDamage"] = user_total
        analysis["users"][user_key] = user_data

    return analysis


def export_analysis_to_json(analysis, output_path):
    path = Path(output_path)
    path.write_text(json.dumps(analysis, indent=2), encoding="utf-8")
    return path


def _append_text_element(parent, tag_name, value):
    child = ET.SubElement(parent, tag_name)
    if value is None:
        child.set("nil", "true")
    else:
        child.text = str(value)
    return child


def _append_team(parent, team_data):
    team_element = ET.SubElement(parent, "team")

    heroes_element = ET.SubElement(team_element, "heroes")
    for hero in team_data.get("heroes", []):
        hero_element = ET.SubElement(heroes_element, "hero")
        _append_text_element(hero_element, "unitId", hero.get("unitId"))
        _append_text_element(hero_element, "power", hero.get("power"))

    machine_data = team_data.get("machineOfWar")
    machine_element = ET.SubElement(team_element, "machineOfWar")
    if machine_data is None:
        machine_element.set("nil", "true")
    else:
        _append_text_element(machine_element, "unitId", machine_data.get("unitId"))
        _append_text_element(machine_element, "power", machine_data.get("power"))


def export_analysis_to_xml(analysis, output_path):
    path = Path(output_path)
    xml_path = path.with_suffix(".xml") if path.suffix else Path(f"{path}.xml")

    root = ET.Element("guildRaidAnalysis")
    _append_text_element(root, "source", analysis.get("source"))
    _append_text_element(root, "userIdFilter", analysis.get("userIdFilter"))

    users_element = ET.SubElement(root, "users")
    for user_id, user_data in analysis.get("users", {}).items():
        user_element = ET.SubElement(users_element, "user", id=user_id)
        _append_text_element(user_element, "totalDamage", user_data.get("totalDamage"))

        rarities_element = ET.SubElement(user_element, "rarities")

        for rarity_name, rarity_data in user_data.get("rarities", {}).items():
            rarity_element = ET.SubElement(
                rarities_element,
                "rarity",
                name=rarity_name
            )

            _append_text_element(
                rarity_element,
                "totalDamage",
                rarity_data.get("totalDamage")
            )

            bosses_element = ET.SubElement(rarity_element, "bosses")

            for boss_name, boss_data in rarity_data.get("bosses", {}).items():
                boss_element = ET.SubElement(
                    bosses_element,
                    "boss",
                    name=boss_name
                )

                _append_text_element(
                    boss_element,
                    "totalDamage",
                    boss_data.get("totalDamage")
                )

                damage_types_element = ET.SubElement(
                    boss_element,
                    "damageTypes"
                )
            boss_element = ET.SubElement(bosses_element, "boss", name=boss_name)
            _append_text_element(boss_element, "totalDamage", boss_data.get("totalDamage"))

            rarities_element = ET.SubElement(boss_element, "rarities")
            for rarity_name, rarity_data in boss_data.get("rarities", {}).items():
                rarity_element = ET.SubElement(rarities_element, "rarity", name=rarity_name)
                _append_text_element(rarity_element, "totalDamage", rarity_data.get("totalDamage"))

                damage_types_element = ET.SubElement(rarity_element, "damageTypes")
                for damage_type_name, damage_type_data in rarity_data.get("damageTypes", {}).items():
                    damage_type_element = ET.SubElement(damage_types_element, "damageType", name=damage_type_name)
                    _append_text_element(damage_type_element, "totalDamage", damage_type_data.get("totalDamage"))

                    entries_element = ET.SubElement(damage_type_element, "entries")
                    for entry in damage_type_data.get("entries", []):
                        entry_element = ET.SubElement(entries_element, "entry")
                        _append_text_element(entry_element, "damageDealt", entry.get("damageDealt"))
                        _append_text_element(entry_element, "damageType", entry.get("damageType"))
                        _append_text_element(entry_element, "encounterType", entry.get("encounterType"))
                        _append_text_element(entry_element, "unitId", entry.get("unitId"))
                        _append_text_element(entry_element, "type", entry.get("type"))
                        _append_text_element(entry_element, "rarity", entry.get("rarity"))
                        _append_text_element(entry_element, "startedOn", entry.get("startedOn"))
                        _append_text_element(entry_element, "completedOn", entry.get("completedOn"))

                        team_data = entry.get("team")
                        if team_data is not None:
                            _append_team(entry_element, team_data)

    ET.indent(root, space="  ")
    tree = ET.ElementTree(root)
    tree.write(xml_path, encoding="utf-8", xml_declaration=True)
    return xml_path


def print_report(grouped):
    for user_key in sorted(grouped):
        print("=" * 80)
        print(f"User: {user_key}")
        print("=" * 80)

        user_total = 0
        for rarity in sorted(grouped[user_key]):
            print(f"\nRarity: {rarity}")

            rarity_total = 0

            for boss_key in sorted(grouped[user_key][rarity]):
                print(f"  Boss: {boss_key}")

                entries = grouped[user_key][rarity][boss_key]
                boss_total = sum(get_damage_value(entry) for _, entry in entries)
                rarity_total += boss_total
                user_total += boss_total

                print(f"  Rarity: {rarity} | Damage: {rarity_total} | Entries: {len(entries)}")

                by_damage_type = defaultdict(list)
                for damage_type, entry in entries:
                    by_damage_type[damage_type].append(entry)

                for damage_type in sorted(by_damage_type):
                    damage_type_entries = by_damage_type[damage_type]
                    damage_type_total = sum(get_damage_value(entry) for entry in damage_type_entries)
                    print(f"    Damage Type: {damage_type} | Damage: {damage_type_total} | Entries: {len(damage_type_entries)}")

                    if damage_type.lower() == "battle":
                        for index, entry in enumerate(damage_type_entries, 1):
                            print(f"      Battle #{index}: damage={get_damage_value(entry)}")
                            print(f"        Team: {format_team(entry)}")
                    elif damage_type.lower() == "bomb":
                        for index, entry in enumerate(damage_type_entries, 1):
                            print(f"      Bomb #{index}: damage={get_damage_value(entry)}")
                    else:
                        for index, entry in enumerate(damage_type_entries, 1):
                            print(f"      Entry #{index}: damage={get_damage_value(entry)}")

            print(f"    Boss Total: {boss_total}")

        print(f"  Rarity Total: {rarity_total}")
        print()


def main():
    parser = argparse.ArgumentParser(description="Analyze Tacticus guild raid data.")
    parser.add_argument(
        "--user-id",
        dest="user_id",
        help="Filter the report to entries whose userId matches the provided text.",
    )
    parser.add_argument(
        "--output",
        dest="output",
        default="guild_raid_analysis.json",
        help="Write the full analysis to a local JSON file; an XML file is written beside it.",
    )
    args = parser.parse_args()

    payload = fetch_guild_raid_data()
    entries = normalize_guild_raid_payload(payload)

    if not entries:
        print("No guild raid entries found.")
        return

    filtered_entries = filter_entries_by_user_id(entries, args.user_id)

    if args.user_id and not filtered_entries:
        print(f"No guild raid entries found for userId matching '{args.user_id}'.")
        return

    analysis = build_analysis(filtered_entries, args.user_id)
    export_path = export_analysis_to_json(analysis, args.output)
    xml_export_path = export_analysis_to_xml(analysis, args.output)

    grouped = build_report(filtered_entries)
    print_report(grouped)
    print(f"Exported analysis to {export_path}")
    print(f"Exported analysis to {xml_export_path}")


if __name__ == "__main__":
    main()
