"""
Guild raid advisor: turns Tacticus API data into "what should I do next" advice.

The advice covers the decisions the API can actually inform:
  * which encounter (boss or prime) to attack next,
  * which of your teams has done the most damage against it,
  * whether to use a bomb (to finish an encounter) or a raid token,
  * when you are wasting token regeneration.

The API does not expose live battlefield state, so this does not suggest
per-turn moves inside a battle.

Everything above the "Data loading / CLI" section is pure logic with no I/O,
shared by this CLI and by tacticus_raid_overlay.py.
"""
from __future__ import annotations

import argparse
import json
import os
from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Dict, List, Optional, Tuple

from tacticus_api_client import TacticusApiError, create_session, fetch_guild_raid, fetch_player, get_api_keys

TOP_TEAMS = 3
EncounterKey = Tuple[int, int, int]


# ── Models ─────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class TokenPool:
    current: int
    maximum: int
    seconds_to_next: Optional[int]
    regen_seconds: Optional[int]

    @property
    def is_full(self) -> bool:
        return self.current >= self.maximum


@dataclass(frozen=True)
class Encounter:
    tier: int
    set_index: int
    index: int
    encounter_type: str
    boss_type: str
    rarity: str
    remaining_hp: Optional[int]
    max_hp: Optional[int]
    battles_in_progress: int

    @property
    def key(self) -> EncounterKey:
        return (self.tier, self.set_index, self.index)

    @property
    def is_boss(self) -> bool:
        return self.encounter_type == "Boss"

    @property
    def is_defeated(self) -> bool:
        return self.remaining_hp is not None and self.remaining_hp <= 0

    @property
    def name(self) -> str:
        role = "Boss" if self.is_boss else "Prime"
        return f"{self.rarity} {self.boss_type} ({role})"


@dataclass(frozen=True)
class Team:
    heroes: Tuple[str, ...]
    machine_of_war: Optional[str]


@dataclass(frozen=True)
class TeamStats:
    team: Team
    battles: int
    mean_damage: int
    best_damage: int
    yours: bool


@dataclass(frozen=True)
class BombEstimate:
    minimum: int
    average: int
    samples: int


@dataclass(frozen=True)
class Action:
    kind: str  # "bomb" | "battle" | "wait"
    headline: str
    reason: str
    target: Optional[Encounter] = None
    team: Optional[TeamStats] = None


@dataclass(frozen=True)
class RaidAdvice:
    season: Optional[int]
    generated_at: datetime
    encounters: List[Encounter]
    actions: List[Action]
    teams: Dict[EncounterKey, List[TeamStats]]
    raid_tokens: Optional[TokenPool]
    bomb_tokens: Optional[TokenPool]
    unit_names: Dict[str, str]
    warnings: List[str]

    @property
    def battle_target(self) -> Optional[Encounter]:
        return next((a.target for a in self.actions if a.kind == "battle" and a.target), None)


# ── Parsing helpers ────────────────────────────────────────────────────────────

def _optional_int(value) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_int(value, default: int = 0) -> int:
    parsed = _optional_int(value)
    return default if parsed is None else parsed


def parse_timestamp(value) -> Optional[datetime]:
    """
    Parse an API timestamp into an aware UTC datetime.

    The OpenAPI spec types these as date-time strings but describes them as
    unix seconds, so both forms are accepted. Returns None when absent/invalid.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc)

    text = str(value).strip()
    if not text:
        return None
    if text.lstrip("-").isdigit():
        return datetime.fromtimestamp(int(text), tz=timezone.utc)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def raid_entries(raid_payload) -> List[dict]:
    """Return the entry list from a /guildRaid response (or a bare list)."""
    if isinstance(raid_payload, dict):
        return list(raid_payload.get("entries") or [])
    if isinstance(raid_payload, list):
        return raid_payload
    return []


def _is_damage_type(entry, damage_type: str) -> bool:
    return str(entry.get("damageType", "")).lower() == damage_type


def _is_completed(entry) -> bool:
    return parse_timestamp(entry.get("completedOn")) is not None


def _defeated_target(entry) -> bool:
    remaining = _optional_int(entry.get("remainingHp"))
    return remaining is not None and remaining <= 0


def _encounter_key(entry) -> EncounterKey:
    return (_as_int(entry.get("tier")), _as_int(entry.get("set")), _as_int(entry.get("encounterIndex")))


def _encounter_identity(entry) -> Tuple[str, str, str]:
    """(boss type, rarity, encounter type): what makes past damage comparable."""
    return (
        entry.get("type") or entry.get("unitId") or "Unknown",
        entry.get("rarity") or "Unknown",
        entry.get("encounterType") or "Boss",
    )


def _matches_encounter(entry, encounter: Encounter) -> bool:
    return _encounter_identity(entry) == (encounter.boss_type, encounter.rarity, encounter.encounter_type)


def team_from_entry(entry) -> Optional[Team]:
    heroes = tuple(sorted(h["unitId"] for h in entry.get("heroDetails") or [] if h.get("unitId")))
    if not heroes:
        return None
    machine = (entry.get("machineOfWarDetails") or {}).get("unitId")
    return Team(heroes, machine)


# ── Raid state ─────────────────────────────────────────────────────────────────

def current_encounters(entries) -> List[Encounter]:
    """
    Latest known state of every encounter in the guild's current boss set.

    The current set is the highest (tier, set) seen. HP comes from the most
    recently completed attempt on each encounter; attempts without completedOn
    are still being fought, so they are counted but not trusted for HP.
    """
    if not entries:
        return []

    front = max((_as_int(e.get("tier")), _as_int(e.get("set"))) for e in entries)
    latest_completed = {}
    sample_entry = {}
    in_progress = defaultdict(int)

    for position, entry in enumerate(entries):
        key = _encounter_key(entry)
        if key[:2] != front:
            continue
        sample_entry.setdefault(key, entry)

        completed_on = parse_timestamp(entry.get("completedOn"))
        if completed_on is None:
            in_progress[key] += 1
            continue
        # Position breaks timestamp ties so the later record in the list wins.
        order = (completed_on, position)
        if key not in latest_completed or order > latest_completed[key][0]:
            latest_completed[key] = (order, entry)

    encounters = []
    for key, first_entry in sample_entry.items():
        entry = latest_completed[key][1] if key in latest_completed else first_entry
        remaining_hp = _optional_int(entry.get("remainingHp")) if key in latest_completed else None
        boss_type, rarity, encounter_type = _encounter_identity(entry)
        encounters.append(
            Encounter(
                tier=key[0],
                set_index=key[1],
                index=key[2],
                encounter_type=encounter_type,
                boss_type=boss_type,
                rarity=rarity,
                remaining_hp=remaining_hp,
                max_hp=_optional_int(entry.get("maxHp")),
                battles_in_progress=in_progress[key],
            )
        )

    return sorted(encounters, key=lambda e: (not e.is_boss, e.index))


def active_encounters(encounters) -> List[Encounter]:
    """
    Encounters that can still be attacked.

    Once the main boss of a set falls the guild moves on, so the set's primes
    are no longer targets even if they still have HP.
    """
    if any(e.is_boss and e.is_defeated for e in encounters):
        return []
    return [e for e in encounters if not e.is_defeated]


# ── Damage statistics ──────────────────────────────────────────────────────────

def _summarise(damage_by_team, yours: bool) -> List[TeamStats]:
    stats = [
        TeamStats(team, len(damages), round(mean(damages)), max(damages), yours)
        for team, damages in damage_by_team.items()
    ]
    return sorted(stats, key=lambda s: (s.mean_damage, s.battles), reverse=True)


def rank_teams(entries, encounter: Encounter, user_id=None, owned_units=None, limit=TOP_TEAMS) -> List[TeamStats]:
    """
    Teams ranked by mean damage against this encounter's boss type and rarity.

    Your own teams come first because they reflect your roster's real power.
    Guild mates' teams are added only when you own every hero in them (the
    API docs don't confirm Machines of War appear in player.units, so the
    MoW is not checked). Killing blows are excluded: their damage is capped
    by the HP that was left, which would understate the team.
    """
    yours = defaultdict(list)
    guild = defaultdict(list)

    for entry in entries:
        if not _is_damage_type(entry, "battle") or not _matches_encounter(entry, encounter):
            continue
        if not _is_completed(entry) or _defeated_target(entry):
            continue
        team = team_from_entry(entry)
        if team is None:
            continue

        damage = _as_int(entry.get("damageDealt"))
        if user_id and entry.get("userId") == user_id:
            yours[team].append(damage)
        elif owned_units is not None and set(team.heroes) <= owned_units:
            guild[team].append(damage)

    suggestions = [s for s in _summarise(guild, yours=False) if s.team not in yours]
    return (_summarise(yours, yours=True) + suggestions)[:limit]


def estimate_bomb_damage(entries, rarity: str) -> Optional[BombEstimate]:
    """
    Observed bomb damage, preferring bombs thrown at the same rarity.

    Bomb damage scales with guild level rather than your roster, so every
    guild member's bombs are a valid sample. Killing bombs are excluded
    because their damage is capped by the HP that was left.
    """
    bombs = [
        (entry.get("rarity"), _as_int(entry.get("damageDealt")))
        for entry in entries
        if _is_damage_type(entry, "bomb") and _is_completed(entry) and not _defeated_target(entry)
    ]
    same_rarity = [damage for bomb_rarity, damage in bombs if bomb_rarity == rarity]
    sample = same_rarity or [damage for _, damage in bombs]
    if not sample:
        return None
    return BombEstimate(minimum=min(sample), average=round(mean(sample)), samples=len(sample))


# ── Tokens ─────────────────────────────────────────────────────────────────────

def parse_token_pool(raw) -> Optional[TokenPool]:
    if not isinstance(raw, dict) or raw.get("max") is None:
        return None
    return TokenPool(
        current=_as_int(raw.get("current")),
        maximum=_as_int(raw.get("max")),
        seconds_to_next=_optional_int(raw.get("nextTokenInSeconds")),
        regen_seconds=_optional_int(raw.get("regenDelayInSeconds")),
    )


def project_token_pool(pool: Optional[TokenPool], elapsed_seconds: float) -> Optional[TokenPool]:
    """
    Advance a token pool by the time elapsed since the API snapshot.

    Player data is cached server-side: nextTokenInSeconds counts from
    metaData.lastUpdatedOn, not from when we fetched it.
    """
    if pool is None or pool.is_full or pool.seconds_to_next is None or elapsed_seconds <= 0:
        return pool

    current = pool.current
    remaining = pool.seconds_to_next - int(elapsed_seconds)
    regen = pool.regen_seconds or 0
    while remaining <= 0 and current < pool.maximum:
        current += 1
        if regen <= 0:
            break
        remaining += regen

    if current >= pool.maximum:
        return replace(pool, current=pool.maximum, seconds_to_next=None)
    return replace(pool, current=current, seconds_to_next=max(remaining, 0))


def player_token_pools(player_payload, now: datetime) -> Tuple[Optional[TokenPool], Optional[TokenPool]]:
    """Return (raid tokens, bomb tokens) projected to `now`, or None when unknown."""
    payload = player_payload or {}
    progress = (payload.get("player") or {}).get("progress") or {}
    guild_raid = progress.get("guildRaid") or {}

    snapshot = _optional_int((payload.get("metaData") or {}).get("lastUpdatedOn"))
    elapsed = max(0.0, now.timestamp() - snapshot) if snapshot else 0.0

    return (
        project_token_pool(parse_token_pool(guild_raid.get("tokens")), elapsed),
        project_token_pool(parse_token_pool(guild_raid.get("bombTokens")), elapsed),
    )


# ── Formatting ─────────────────────────────────────────────────────────────────

def format_number(value: Optional[int]) -> str:
    """Compact 3-significant-figure form: 41234 -> 41.2k, 999999 -> 1M."""
    if value is None:
        return "?"
    # Round first so values like 999999 move up to the next suffix.
    rounded = float(f"{value:.3g}")
    for threshold, suffix in ((1_000_000_000, "B"), (1_000_000, "M"), (1_000, "k")):
        if abs(rounded) >= threshold:
            return f"{rounded / threshold:g}{suffix}"
    return f"{rounded:g}"


def format_duration(seconds: Optional[int]) -> str:
    if seconds is None:
        return "?"
    seconds = max(0, int(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes:02d}m"
    if minutes:
        return f"{minutes}m {secs:02d}s"
    return f"{secs}s"


def describe_team(team: Team, unit_names: Dict[str, str]) -> str:
    heroes = ", ".join(unit_names.get(hero, hero) for hero in team.heroes)
    if team.machine_of_war:
        return f"{heroes} + {unit_names.get(team.machine_of_war, team.machine_of_war)}"
    return heroes


def describe_token_pool(label: str, pool: Optional[TokenPool]) -> str:
    if pool is None:
        return f"{label} ?"
    if pool.is_full:
        return f"{label} {pool.current}/{pool.maximum} (full)"
    return f"{label} {pool.current}/{pool.maximum} (next in {format_duration(pool.seconds_to_next)})"


# ── Decision making ────────────────────────────────────────────────────────────

def _has_token(pool: Optional[TokenPool]) -> bool:
    # Unknown token state (no player data) is treated as available so advice is still shown.
    return pool is None or pool.current > 0


def _in_progress_note(encounter: Encounter) -> str:
    if not encounter.battles_in_progress:
        return ""
    count = encounter.battles_in_progress
    return f" {count} battle{'s' if count > 1 else ''} in progress on it, so check it's still standing."


def _pick_bomb_finisher(active, bomb_estimates) -> Optional[Encounter]:
    """
    The encounter with the most HP that even the weakest bomb seen so far would finish.

    Bomb damage is random within a range, so the observed minimum is the
    safest available estimate of what the next bomb will do.
    """
    finishable = [
        e for e in active
        if e.remaining_hp is not None
        and bomb_estimates.get(e.key) is not None
        and e.remaining_hp <= bomb_estimates[e.key].minimum
    ]
    return max(finishable, key=lambda e: e.remaining_hp, default=None)


def _expected_damage(encounter: Encounter, teams) -> Optional[int]:
    ranked = teams.get(encounter.key) or []
    return ranked[0].mean_damage if ranked else None


def _pick_battle_target(candidates, teams) -> Optional[Encounter]:
    """
    Maximise the damage that counts: min(expected damage, HP remaining).

    Damage beyond an encounter's remaining HP is wasted, so a nearly-dead
    encounter scores lower than one that can absorb a full attack. Ties go to
    the encounter closer to defeat. With no damage data at all, aim at the
    encounter with the lowest share of HP left.
    """
    scored = [
        (e, _expected_damage(e, teams)) for e in candidates if e.remaining_hp is not None
    ]
    with_data = [(e, expected) for e, expected in scored if expected is not None]
    if with_data:
        best = max(with_data, key=lambda pair: (min(pair[1], pair[0].remaining_hp), -pair[0].remaining_hp))
        return best[0]

    with_max = [e for e, _ in scored if e.max_hp]
    if with_max:
        return min(with_max, key=lambda e: e.remaining_hp / e.max_hp)
    return candidates[0] if candidates else None


def _battle_reason(target: Encounter, team: Optional[TeamStats], unit_names, raid_tokens) -> str:
    parts = []
    if raid_tokens is not None and raid_tokens.is_full:
        parts.append("Raid tokens are full, so regeneration is being wasted.")

    if team is None:
        parts.append(f"No battle data for this encounter yet; {format_number(target.remaining_hp)} HP left.")
    else:
        source = "yours" if team.yours else "guild mates'"
        plural = "s" if team.battles > 1 else ""
        parts.append(
            f"Use {describe_team(team.team, unit_names)}: avg {format_number(team.mean_damage)} "
            f"across {team.battles} battle{plural} ({source})."
        )
        if target.remaining_hp is not None and team.mean_damage >= target.remaining_hp:
            # Only a kill depends on the HP still being there, so only then mention live battles.
            parts.append(
                f"That should defeat it ({format_number(target.remaining_hp)} HP left).{_in_progress_note(target)}"
            )
    return " ".join(parts)


def plan_actions(active, teams, bomb_estimates, raid_tokens, bomb_tokens, unit_names) -> List[Action]:
    """Order the next moves: bomb finisher, then battle, then bomb advice, then wait."""
    actions = []
    has_bomb = _has_token(bomb_tokens)
    has_raid_token = _has_token(raid_tokens)

    finisher = _pick_bomb_finisher(active, bomb_estimates) if has_bomb else None
    if finisher is not None:
        estimate = bomb_estimates[finisher.key]
        actions.append(
            Action(
                kind="bomb",
                headline=f"Bomb {finisher.name}",
                reason=(
                    f"{format_number(finisher.remaining_hp)} HP left and bombs have dealt at least "
                    f"{format_number(estimate.minimum)} ({estimate.samples} bomb{'s' if estimate.samples > 1 else ''}), "
                    f"so a bomb should finish it without spending a raid token." + _in_progress_note(finisher)
                ),
                target=finisher,
            )
        )

    if has_raid_token:
        candidates = [e for e in active if e != finisher]
        target = _pick_battle_target(candidates, teams)
        if target is not None:
            ranked = teams.get(target.key) or []
            best_team = ranked[0] if ranked else None
            actions.append(
                Action(
                    kind="battle",
                    headline=f"Battle {target.name}",
                    reason=_battle_reason(target, best_team, unit_names, raid_tokens),
                    target=target,
                    team=best_team,
                )
            )
        elif not active:
            actions.append(
                Action(
                    kind="battle",
                    headline="Battle the next boss",
                    reason="Nobody has attacked it yet, so there is no HP or team data for it.",
                )
            )

    if has_bomb and finisher is None and active:
        known = [bomb_estimates[e.key] for e in active if bomb_estimates.get(e.key)]
        if known:
            reach = format_number(min(estimate.minimum for estimate in known))
            reason = (
                f"No encounter is within reliable bomb range (about {reach}). "
                "Bomb regeneration is paused while you hold it, so don't hold it for long."
            )
        else:
            reason = "No guild bombs recorded this season, so finisher range is unknown."
        actions.append(Action(kind="bomb", headline="Hold your bomb for a finisher", reason=reason))

    if not actions:
        actions.append(
            Action(
                kind="wait",
                headline="Wait for tokens",
                reason=(
                    f"{describe_token_pool('Raid tokens', raid_tokens)}; "
                    f"{describe_token_pool('Bombs', bomb_tokens)}."
                ),
            )
        )
    return actions


def build_advice(raid_payload, player_payload=None, user_id=None, now=None) -> RaidAdvice:
    """Combine /guildRaid and /player data into ranked next-move advice."""
    now = now or datetime.now(timezone.utc)
    entries = raid_entries(raid_payload)
    encounters = current_encounters(entries)
    active = active_encounters(encounters)

    player = (player_payload or {}).get("player") or {}
    units = player.get("units")
    owned_units = {u["id"] for u in units if u.get("id")} if units is not None else None
    unit_names = {u["id"]: u.get("name") or u["id"] for u in units or [] if u.get("id")}
    raid_tokens, bomb_tokens = player_token_pools(player_payload, now)

    teams = {e.key: rank_teams(entries, e, user_id, owned_units) for e in active}
    bomb_estimates = {e.key: estimate_bomb_damage(entries, e.rarity) for e in active}
    actions = plan_actions(active, teams, bomb_estimates, raid_tokens, bomb_tokens, unit_names)

    warnings = []
    if not entries:
        warnings.append("No guild raid entries this season yet.")
    elif not active:
        warnings.append("The current boss is defeated; the next one has no attack data yet.")
    if not user_id:
        warnings.append("No user id set, so only guild mates' teams can be ranked.")
    if player_payload is None:
        warnings.append("No player data: token counts and hero ownership are unknown.")

    season = raid_payload.get("season") if isinstance(raid_payload, dict) else None
    return RaidAdvice(
        season=_optional_int(season),
        generated_at=now,
        encounters=encounters,
        actions=actions,
        teams=teams,
        raid_tokens=raid_tokens,
        bomb_tokens=bomb_tokens,
        unit_names=unit_names,
        warnings=warnings,
    )


def hp_bar(encounter: Encounter, width: int = 12) -> str:
    if encounter.remaining_hp is None or not encounter.max_hp:
        return "?" * width
    filled = round(width * max(0, encounter.remaining_hp) / encounter.max_hp)
    return "█" * filled + "░" * (width - filled)


def format_advice(advice: RaidAdvice) -> str:
    """Plain-text rendering of the advice for the terminal."""
    season = f"season {advice.season}" if advice.season is not None else "current season"
    lines = [
        f"Guild Raid, {season} (as of {advice.generated_at:%Y-%m-%d %H:%M} UTC)",
        f"{describe_token_pool('Raid tokens', advice.raid_tokens)} · {describe_token_pool('Bombs', advice.bomb_tokens)}",
        "",
        "NEXT MOVES",
    ]
    for number, action in enumerate(advice.actions, 1):
        lines.append(f" {number}. {action.headline}")
        lines.append(f"    {action.reason}")

    if advice.encounters:
        first = advice.encounters[0]
        lines += ["", f"ENCOUNTERS (tier {first.tier}, set {first.set_index})"]
        for encounter in advice.encounters:
            status = "defeated" if encounter.is_defeated else (
                f"{format_number(encounter.remaining_hp)} / {format_number(encounter.max_hp)}"
            )
            fighting = f"  ({encounter.battles_in_progress} in progress)" if encounter.battles_in_progress else ""
            lines.append(f"  {encounter.name:<40} {hp_bar(encounter)}  {status}{fighting}")

    target = advice.battle_target
    if target is not None and advice.teams.get(target.key):
        lines += ["", f"BEST TEAMS vs {target.name}"]
        for stats in advice.teams[target.key]:
            source = "you" if stats.yours else "guild"
            lines.append(
                f"  {format_number(stats.mean_damage):>6} avg ×{stats.battles:<3} [{source:<5}] "
                f"{describe_team(stats.team, advice.unit_names)}"
            )

    if advice.warnings:
        lines += [""] + [f"! {warning}" for warning in advice.warnings]
    return "\n".join(lines)


# ── Data loading / CLI ─────────────────────────────────────────────────────────

def read_json(path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def make_payload_source(raid_file=None, player_file=None):
    """
    Return a zero-argument callable producing (raid_payload, player_payload).

    With raid_file the data is read from saved API responses (no keys needed);
    otherwise API keys are requested once and each call hits the live API.
    """
    if raid_file:
        return lambda: (read_json(raid_file), read_json(player_file) if player_file else None)

    player_key, guild_key = get_api_keys()
    session = create_session()
    return lambda: (fetch_guild_raid(session, guild_key), fetch_player(session, player_key))


def add_common_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--user-id",
        default=os.environ.get("TACTICUS_USER_ID"),
        help="Your guild raid userId, used to rank your own teams (or set TACTICUS_USER_ID).",
    )
    parser.add_argument("--raid-file", help="Read a saved /guildRaid JSON response instead of calling the API.")
    parser.add_argument("--player-file", help="Read a saved /player JSON response (used with --raid-file).")


def main():
    parser = argparse.ArgumentParser(description="Recommend your next guild raid moves.")
    add_common_arguments(parser)
    args = parser.parse_args()

    try:
        raid_payload, player_payload = make_payload_source(args.raid_file, args.player_file)()
    except (TacticusApiError, OSError, ValueError) as exc:
        raise SystemExit(f"Could not load guild raid data: {exc}") from exc
    print(format_advice(build_advice(raid_payload, player_payload, args.user_id)))


if __name__ == "__main__":
    main()
