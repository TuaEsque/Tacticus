from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import tacticus_raid_advisor as advisor

ME = "me"
NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
SAMPLE_USER_ID = "00000000-0000-4000-8000-000000000001"


def make_entry(**overrides):
    entry = {
        "userId": "ally",
        "tier": 1,
        "set": 0,
        "encounterIndex": 0,
        "encounterType": "Boss",
        "type": "Ghazghkull",
        "rarity": "Legendary",
        "maxHp": 1_000_000,
        "remainingHp": 500_000,
        "damageDealt": 100_000,
        "damageType": "Battle",
        "startedOn": 100,
        "completedOn": 200,
        "heroDetails": [{"unitId": "hero_a", "power": 1}, {"unitId": "hero_b", "power": 1}],
    }
    entry.update(overrides)
    return entry


def make_player(raid_tokens=1, bomb_tokens=1, units=("hero_a", "hero_b"), updated=NOW):
    return {
        "player": {
            "units": [{"id": unit, "name": unit.upper()} for unit in units],
            "progress": {
                "guildRaid": {
                    "tokens": {"current": raid_tokens, "max": 3, "nextTokenInSeconds": 3600, "regenDelayInSeconds": 43200},
                    "bombTokens": {"current": bomb_tokens, "max": 1, "nextTokenInSeconds": 3600, "regenDelayInSeconds": 64800},
                }
            },
        },
        "metaData": {"lastUpdatedOn": int(updated.timestamp())},
    }


# ── Formatting / parsing ───────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "value, expected",
    [
        (1_700_000_000, datetime(2023, 11, 14, 22, 13, 20, tzinfo=timezone.utc)),
        ("1700000000", datetime(2023, 11, 14, 22, 13, 20, tzinfo=timezone.utc)),
        ("2025-03-17T10:00:00Z", datetime(2025, 3, 17, 10, tzinfo=timezone.utc)),
        ("2025-03-17T10:00:00", datetime(2025, 3, 17, 10, tzinfo=timezone.utc)),
        (None, None),
        ("", None),
        ("not a date", None),
        (True, None),
    ],
)
def test_parse_timestamp_accepts_unix_seconds_and_iso(value, expected):
    assert advisor.parse_timestamp(value) == expected


@pytest.mark.parametrize(
    "value, expected",
    [(None, "?"), (0, "0"), (512, "512"), (41_234, "41.2k"), (999_999, "1M"), (1_234_567, "1.23M")],
)
def test_format_number(value, expected):
    assert advisor.format_number(value) == expected


@pytest.mark.parametrize(
    "seconds, expected",
    [(None, "?"), (-5, "0s"), (9, "9s"), (125, "2m 05s"), (3725, "1h 02m")],
)
def test_format_duration(seconds, expected):
    assert advisor.format_duration(seconds) == expected


# ── Raid state ─────────────────────────────────────────────────────────────────

def test_encounter_hp_comes_from_latest_completed_attempt_not_list_order():
    entries = [
        make_entry(remainingHp=300_000, completedOn=500),
        make_entry(remainingHp=800_000, completedOn=100),
    ]

    (encounter,) = advisor.current_encounters(entries)

    assert encounter.remaining_hp == 300_000


def test_only_the_highest_tier_and_set_is_reported():
    entries = [
        make_entry(tier=1, set=0, type="TervigonLeviathan", remainingHp=0),
        make_entry(tier=1, set=1, type="Ghazghkull"),
    ]

    encounters = advisor.current_encounters(entries)

    assert [e.boss_type for e in encounters] == ["Ghazghkull"]


def test_in_progress_attempts_are_counted_but_not_trusted_for_hp():
    entries = [
        make_entry(remainingHp=400_000, completedOn=200),
        make_entry(remainingHp=999, completedOn=None),
        make_entry(encounterIndex=1, encounterType="SideBoss", remainingHp=1, completedOn=None),
    ]

    boss, prime = advisor.current_encounters(entries)

    assert (boss.remaining_hp, boss.battles_in_progress) == (400_000, 1)
    assert (prime.remaining_hp, prime.battles_in_progress) == (None, 1)


def test_defeated_boss_retires_its_primes():
    entries = [
        make_entry(remainingHp=0),
        make_entry(encounterIndex=1, encounterType="SideBoss", remainingHp=50_000),
    ]

    encounters = advisor.current_encounters(entries)

    assert advisor.active_encounters(encounters) == []


# ── Damage statistics ──────────────────────────────────────────────────────────

def test_rank_teams_puts_your_teams_first_and_filters_guild_teams_by_ownership():
    owned_team = [{"unitId": "hero_a"}, {"unitId": "hero_b"}]
    unowned_team = [{"unitId": "hero_a"}, {"unitId": "hero_z"}]
    entries = [
        make_entry(userId=ME, damageDealt=200_000, heroDetails=[{"unitId": "hero_c"}]),
        make_entry(userId=ME, damageDealt=300_000, heroDetails=[{"unitId": "hero_c"}]),
        make_entry(userId="ally", damageDealt=900_000, heroDetails=owned_team),
        make_entry(userId="ally", damageDealt=950_000, heroDetails=unowned_team),
    ]
    (encounter,) = advisor.current_encounters(entries)

    ranked = advisor.rank_teams(entries, encounter, ME, owned_units={"hero_a", "hero_b", "hero_c"})

    assert [(s.team.heroes, s.mean_damage, s.yours) for s in ranked] == [
        (("hero_c",), 250_000, True),
        (("hero_a", "hero_b"), 900_000, False),
    ]


def test_rank_teams_ignores_killing_blows_in_progress_and_other_bosses():
    entries = [
        make_entry(userId=ME, damageDealt=100_000),
        make_entry(userId=ME, damageDealt=40_000, remainingHp=0),
        make_entry(userId=ME, damageDealt=0, completedOn=None),
        make_entry(userId=ME, damageDealt=999_999, type="Other"),
        make_entry(userId=ME, damageDealt=999_999, rarity="Epic"),
    ]
    encounter = advisor.current_encounters(entries[:1])[0]

    (stats,) = advisor.rank_teams(entries, encounter, ME, owned_units=set())

    assert (stats.battles, stats.mean_damage) == (1, 100_000)


def test_bomb_estimate_prefers_same_rarity_and_skips_killing_bombs():
    entries = [
        make_entry(damageType="Bomb", damageDealt=60_000),
        make_entry(damageType="Bomb", damageDealt=70_000),
        make_entry(damageType="Bomb", damageDealt=5_000, remainingHp=0),
        make_entry(damageType="Bomb", damageDealt=20_000, rarity="Epic"),
    ]

    assert advisor.estimate_bomb_damage(entries, "Legendary") == advisor.BombEstimate(60_000, 65_000, 2)
    assert advisor.estimate_bomb_damage(entries, "Mythic") == advisor.BombEstimate(20_000, 50_000, 3)
    assert advisor.estimate_bomb_damage([make_entry()], "Legendary") is None


# ── Tokens ─────────────────────────────────────────────────────────────────────

def test_token_pool_projection_regenerates_and_caps_at_max():
    pool = advisor.TokenPool(current=1, maximum=3, seconds_to_next=100, regen_seconds=1000)

    assert advisor.project_token_pool(pool, 50) == advisor.TokenPool(1, 3, 50, 1000)
    assert advisor.project_token_pool(pool, 600) == advisor.TokenPool(2, 3, 500, 1000)
    assert advisor.project_token_pool(pool, 5000) == advisor.TokenPool(3, 3, None, 1000)


def test_player_token_pools_count_from_the_api_snapshot_time():
    player = make_player(raid_tokens=1, updated=NOW - timedelta(seconds=600))

    raid_tokens, bomb_tokens = advisor.player_token_pools(player, NOW)

    assert raid_tokens == advisor.TokenPool(1, 3, 3000, 43200)
    assert bomb_tokens == advisor.TokenPool(1, 1, 3600, 64800)


# ── Advice ─────────────────────────────────────────────────────────────────────

def test_bomb_finishes_a_low_prime_and_battle_goes_elsewhere():
    entries = [
        make_entry(userId=ME, damageDealt=250_000, remainingHp=2_000_000, maxHp=3_000_000),
        make_entry(encounterIndex=1, encounterType="SideBoss", type="Makari", remainingHp=30_000),
        make_entry(damageType="Bomb", damageDealt=60_000, remainingHp=1_900_000, maxHp=3_000_000, completedOn=300),
    ]

    advice = advisor.build_advice({"season": 7, "entries": entries}, make_player(), ME, now=NOW)

    bomb, battle = advice.actions
    assert (bomb.kind, bomb.target.boss_type) == ("bomb", "Makari")
    assert (battle.kind, battle.target.boss_type) == ("battle", "Ghazghkull")
    assert advice.season == 7


def test_battle_target_maximises_damage_that_counts():
    entries = [
        make_entry(userId=ME, damageDealt=300_000, remainingHp=50_000),
        make_entry(
            userId=ME, encounterIndex=1, encounterType="SideBoss", type="Makari",
            damageDealt=250_000, remainingHp=900_000,
        ),
    ]

    advice = advisor.build_advice({"entries": entries}, make_player(bomb_tokens=0), ME, now=NOW)

    (battle,) = advice.actions
    assert battle.target.boss_type == "Makari"


def test_no_tokens_means_wait():
    advice = advisor.build_advice({"entries": [make_entry()]}, make_player(0, 0), ME, now=NOW)

    (action,) = advice.actions
    assert action.kind == "wait"


def test_missing_player_data_is_reported_and_guild_teams_are_not_guessed():
    entries = [make_entry(userId="ally", damageDealt=500_000)]

    advice = advisor.build_advice({"entries": entries}, None, ME, now=NOW)

    assert any("No player data" in warning for warning in advice.warnings)
    assert advice.raid_tokens is None
    assert all(not teams for teams in advice.teams.values())


def test_example_files_produce_bomb_then_battle():
    raid = advisor.read_json(EXAMPLES / "sample_guild_raid.json")
    player = advisor.read_json(EXAMPLES / "sample_player.json")

    advice = advisor.build_advice(raid, player, SAMPLE_USER_ID)
    text = advisor.format_advice(advice)

    assert [a.headline for a in advice.actions] == [
        "Bomb Legendary Makari (Prime)",
        "Battle Legendary Ghazghkull (Boss)",
    ]
    assert "BEST TEAMS vs Legendary Ghazghkull (Boss)" in text
