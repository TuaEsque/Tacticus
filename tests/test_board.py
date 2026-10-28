from pathlib import Path

import pytest

from tacticus_board import (
    TERRAIN,
    Board,
    Cell,
    Hex,
    Piece,
    attack_options,
    battle_map_from_dict,
    battle_map_to_dict,
    has_line_of_sight,
    hex_line,
    load_unit_profiles,
    piece_from_profile,
    reachable_hexes,
)

ORIGIN = Hex(0, 0)
PROFILES = Path(__file__).resolve().parent.parent / "data" / "unit_profiles.json"


def hexes_within(radius, center=ORIGIN):
    return [
        Hex(center.q + dq, center.r + dr)
        for dq in range(-radius, radius + 1)
        for dr in range(-radius, radius + 1)
        if Hex(center.q + dq, center.r + dr).distance(center) <= radius
    ]


def open_board(radius=4, terrain=None, sight_blockers=(), pieces=()):
    terrain = terrain or {}
    cells = {
        hex_: Cell(TERRAIN[terrain.get(hex_, "Open")], hex_ in sight_blockers)
        for hex_ in hexes_within(radius)
    }
    return Board(cells, tuple(pieces))


def hero(position=ORIGIN, movement=2, ranged_range=0, traits=()):
    return Piece("hero", "player", position, movement, ranged_range, frozenset(traits))


def enemy(position, name="boss"):
    return Piece(name, "enemy", position)


# ── Geometry ───────────────────────────────────────────────────────────────────

def test_neighbors_are_all_one_step_away_and_distinct():
    neighbors = ORIGIN.neighbors()

    assert len(set(neighbors)) == 6
    assert all(ORIGIN.distance(n) == 1 for n in neighbors)


def test_distance_counts_hex_steps():
    assert Hex(0, 0).distance(Hex(3, -1)) == 3
    assert Hex(-2, 1).distance(Hex(1, 1)) == 3


def test_straight_line_passes_through_each_hex():
    assert hex_line(Hex(0, 0), Hex(3, 0)) == [Hex(0, 0), Hex(1, 0), Hex(2, 0), Hex(3, 0)]


@pytest.mark.parametrize("target", [Hex(2, -1), Hex(1, 1), Hex(-1, 2), Hex(-2, 1), Hex(-1, -1), Hex(1, -2)])
def test_edge_lines_reach_both_hexes_either_side(target):
    shared = set(ORIGIN.neighbors()) & set(target.neighbors())

    middles = {hex_line(ORIGIN, target, nudge)[1] for nudge in (1e-6, -1e-6)}

    assert middles == shared


def test_hex_parse_round_trips_and_rejects_bad_text():
    assert Hex.parse(str(Hex(-3, 2))) == Hex(-3, 2)
    with pytest.raises(ValueError, match="expected 'q,r'"):
        Hex.parse("3")


# ── Movement ───────────────────────────────────────────────────────────────────

def test_open_ground_reach_is_every_hex_within_movement():
    reach = reachable_hexes(open_board(), hero(movement=2))

    assert set(reach) == set(hexes_within(2))
    assert reach[Hex(2, 0)] == 2


def test_ground_unit_is_blocked_by_enemies_and_impassable_but_passes_allies():
    # Wall the hero in except for one gap held by an ally.
    neighbors = ORIGIN.neighbors()
    gap = neighbors[0]
    terrain = {hex_: "Impassable" for hex_ in neighbors[1:4]}
    pieces = [enemy(hex_) for hex_ in neighbors[4:]] + [Piece("ally", "player", gap)]

    reach = reachable_hexes(open_board(terrain=terrain, pieces=pieces), hero(movement=2))

    assert gap not in reach  # cannot stop on an ally
    assert Hex(2, 0) in reach  # but can move through it
    assert not set(neighbors) & set(reach)


def test_flying_crosses_enemies_and_impassable_without_stopping_on_them():
    terrain = {Hex(1, 0): "Impassable"}
    pieces = [enemy(Hex(2, 0))]

    reach = reachable_hexes(open_board(terrain=terrain, pieces=pieces), hero(movement=3, traits=["Flying"]))

    assert Hex(3, 0) in reach
    assert Hex(1, 0) not in reach and Hex(2, 0) not in reach


def test_razor_wire_stops_ground_units_but_not_flyers():
    # Ring the hero with razor wire.
    terrain = {hex_: "RazorWire" for hex_ in ORIGIN.neighbors()}
    board = open_board(terrain=terrain)

    ground = reachable_hexes(board, hero(movement=3))
    flyer = reachable_hexes(board, hero(movement=3, traits=["Flying"]))

    assert set(ground) == set(hexes_within(1))
    assert set(flyer) == set(hexes_within(3))


# ── Attacks ────────────────────────────────────────────────────────────────────

def test_ranged_is_unavailable_while_adjacent_to_an_enemy():
    # The prime is in range 2, but the adjacent boss forces melee.
    board = open_board(pieces=[enemy(Hex(1, 0), "boss"), enemy(Hex(-2, 0), "prime")])

    options = attack_options(board, hero(movement=0, ranged_range=2))

    assert [(o.kind, o.target.name) for o in options] == [("melee", "boss")]


def test_moving_away_opens_ranged_attacks():
    boss = enemy(Hex(1, 0))
    board = open_board(pieces=[boss])

    options = attack_options(board, hero(movement=1, ranged_range=2))
    ranged_from = {o.move_to for o in options if o.kind == "ranged"}

    assert ranged_from == {h for h in hexes_within(1) if h.distance(boss.position) == 2}


def test_sight_blocker_stops_ranged_unless_indirect_fire():
    boss = enemy(Hex(2, 0))
    board = open_board(sight_blockers={Hex(1, 0)}, pieces=[boss])

    direct = attack_options(board, hero(movement=0, ranged_range=2))
    indirect = attack_options(board, hero(movement=0, ranged_range=2, traits=["IndirectFire"]))

    assert direct == []
    assert [o.kind for o in indirect] == ["ranged"]


@pytest.mark.parametrize("target", [Hex(2, -1), Hex(1, 1), Hex(-1, 2), Hex(-2, 1), Hex(-1, -1), Hex(1, -2)])
def test_edge_line_is_blocked_only_when_both_sides_are(target):
    sides = set(ORIGIN.neighbors()) & set(target.neighbors())

    for side in sides:
        assert has_line_of_sight(open_board(sight_blockers={side}), ORIGIN, target)
    assert not has_line_of_sight(open_board(sight_blockers=sides), ORIGIN, target)


# ── Map bank and profiles ──────────────────────────────────────────────────────

MAP_DATA = {
    "boss": "Ghazghkull",
    "map": "ghazghkull-1",
    "cells": {"0,0": "Open", "1,0": "RazorWire", "2,0": "Impassable", "0,1": "HighGround"},
    "sightBlockers": ["2,0"],
    "deploy": ["0,0"],
    "spawns": [{"id": "a", "enemies": {"0,1": "Ghazghkull"}}],
}


def test_battle_map_round_trips_through_json_form():
    battle_map = battle_map_from_dict(MAP_DATA)

    assert battle_map.cells[Hex(1, 0)].terrain.stops_movement
    assert battle_map.cells[Hex(2, 0)].blocks_sight
    assert battle_map_from_dict(battle_map_to_dict(battle_map)) == battle_map


def test_battle_map_rejects_unknown_terrain_and_off_map_hexes():
    with pytest.raises(ValueError, match="unknown terrain 'Lava'"):
        battle_map_from_dict({**MAP_DATA, "cells": {"0,0": "Lava"}})
    with pytest.raises(ValueError, match="not on the map: 9,9"):
        battle_map_from_dict({**MAP_DATA, "deploy": ["9,9"]})


def test_team_profiles_build_pieces():
    profiles = load_unit_profiles(PROFILES)

    lhykhis = piece_from_profile("eldarLhykhis", profiles, "player", ORIGIN)

    assert set(profiles) == {"tauCrisis", "tauFarsight", "tauDarkstrider", "eldarLhykhis", "admecManipulus"}
    assert (lhykhis.name, lhykhis.movement, lhykhis.ranged_range) == ("Lhykhis", 4, 2)
    assert lhykhis.has_trait("Flying")
    with pytest.raises(ValueError, match="no profile"):
        piece_from_profile("unknown", profiles, "player", ORIGIN)
