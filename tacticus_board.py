"""
Hex board model for planning guild raid turns: where each unit can move and
what it can attack from there.

Pure logic, no UI. Hexes use axial coordinates (q, r); see
https://www.redblobgames.com/grids/hexagons/ for the maths. Axial maths is
the same for pointy- and flat-topped grids; orientation only matters when
drawing.

Rules come from the Tacticus wiki (Combat Basics, Terrain) and the in-game
trait descriptions. Not modelled yet: elevation/cliffs, bridges, Overwatch,
abilities. Assumed until checked in-game: units do not block line of sight,
and a line passing exactly between two hexes is blocked only if both are.
"""
from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, FrozenSet, List, Optional, Tuple

# ── Hex geometry ───────────────────────────────────────────────────────────────

AXIAL_DIRECTIONS = ((1, 0), (1, -1), (0, -1), (-1, 0), (-1, 1), (0, 1))


@dataclass(frozen=True, order=True)
class Hex:
    q: int
    r: int

    @property
    def s(self) -> int:
        """Third cube coordinate; q + r + s is always 0."""
        return -self.q - self.r

    def neighbors(self) -> List["Hex"]:
        return [Hex(self.q + dq, self.r + dr) for dq, dr in AXIAL_DIRECTIONS]

    def distance(self, other: "Hex") -> int:
        return (abs(self.q - other.q) + abs(self.r - other.r) + abs(self.s - other.s)) // 2

    @classmethod
    def parse(cls, text: str) -> "Hex":
        """Parse the "q,r" form used as JSON keys."""
        try:
            q, r = (int(part) for part in text.split(","))
        except ValueError as exc:
            raise ValueError(f"invalid hex {text!r}: expected 'q,r'") from exc
        return cls(q, r)

    def __str__(self) -> str:
        return f"{self.q},{self.r}"


def _cube_round(x: float, y: float, z: float) -> Hex:
    rx, ry, rz = round(x), round(y), round(z)
    dx, dy, dz = abs(rx - x), abs(ry - y), abs(rz - z)
    # Rounding can break q + r + s == 0; fix the coordinate that moved most.
    if dx > dy and dx > dz:
        rx = -ry - rz
    elif dy > dz:
        ry = -rx - rz
    return Hex(rx, ry)


def hex_line(start: Hex, end: Hex, nudge: float = 1e-6) -> List[Hex]:
    """
    Hexes on the straight line from start to end, inclusive.

    The nudge shifts the line slightly so points landing exactly on a hex
    edge round consistently; flipping its sign picks the other side.
    """
    steps = start.distance(end)
    if steps == 0:
        return [start]
    a = (start.q + nudge, start.r + nudge, start.s - 2 * nudge)
    b = (end.q + nudge, end.r + nudge, end.s - 2 * nudge)
    return [
        _cube_round(*(a[axis] + (b[axis] - a[axis]) * i / steps for axis in range(3)))
        for i in range(steps + 1)
    ]


# ── Terrain and units ──────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Terrain:
    name: str
    passable: bool = True
    stops_movement: bool = False


# Movement effects only; damage modifiers (high ground, trench...) come with the damage model.
TERRAIN = {
    terrain.name: terrain
    for terrain in (
        Terrain("Open"),
        Terrain("HighGround"),
        Terrain("Trench"),
        Terrain("TallGrass"),
        Terrain("RazorWire", stops_movement=True),
        Terrain("Ice", stops_movement=True),
        Terrain("Fire", stops_movement=True),
        Terrain("Impassable", passable=False),
    )
}

IGNORE_STOP_HEXES = frozenset({"Flying", "Unstoppable", "Vehicle"})


@dataclass(frozen=True)
class Cell:
    terrain: Terrain = TERRAIN["Open"]
    blocks_sight: bool = False


@dataclass(frozen=True)
class Piece:
    name: str
    side: str  # "player" or "enemy"
    position: Hex
    movement: int = 0
    ranged_range: int = 0  # 0 means no ranged attack
    traits: FrozenSet[str] = frozenset()

    def has_trait(self, trait: str) -> bool:
        return trait in self.traits


@dataclass(frozen=True)
class Board:
    cells: Dict[Hex, Cell]
    pieces: Tuple[Piece, ...] = ()

    def occupant(self, hex_: Hex) -> Optional[Piece]:
        return next((p for p in self.pieces if p.position == hex_), None)

    def enemies_of(self, piece: Piece) -> List[Piece]:
        return [p for p in self.pieces if p.side != piece.side]

    def blocks_sight(self, hex_: Hex) -> bool:
        cell = self.cells.get(hex_)
        return cell is not None and cell.blocks_sight


# ── Movement ───────────────────────────────────────────────────────────────────

def reachable_hexes(board: Board, piece: Piece) -> Dict[Hex, int]:
    """
    Hexes the piece can end its move on, mapped to the steps needed.

    One move per turn, up to the movement stat. Allies can be passed through
    but not stopped on. Enemies and impassable hexes block, unless the piece
    is Flying (it may cross them, never end on them). Razor wire, ice and fire
    end the move unless the piece is Flying, Unstoppable or a Vehicle.
    """
    flying = piece.has_trait("Flying")
    ignores_stops = bool(piece.traits & IGNORE_STOP_HEXES)
    occupants = {p.position: p for p in board.pieces}

    destinations = {piece.position: 0}
    seen = {piece.position}
    frontier = deque([(piece.position, 0)])
    # Every step costs 1, so breadth-first search finds the fewest steps to each hex.
    while frontier:
        current, steps = frontier.popleft()
        if steps >= piece.movement:
            continue
        for nxt in current.neighbors():
            cell = board.cells.get(nxt)
            if cell is None or nxt in seen:
                continue
            occupant = occupants.get(nxt)
            hostile = occupant is not None and occupant.side != piece.side
            if not flying and (not cell.terrain.passable or hostile):
                continue
            seen.add(nxt)

            if cell.terrain.passable and occupant is None:
                destinations[nxt] = steps + 1
            if not (cell.terrain.stops_movement and not ignores_stops):
                frontier.append((nxt, steps + 1))
    return destinations


# ── Attacks ────────────────────────────────────────────────────────────────────

def has_line_of_sight(board: Board, origin: Hex, target: Hex) -> bool:
    """
    True unless sight-blocking hexes lie between origin and target.

    A line running exactly along a hex edge touches two hexes; it is treated
    as blocked only when both lines (nudged either way) are blocked.
    """
    for nudge in (1e-6, -1e-6):
        between = hex_line(origin, target, nudge)[1:-1]
        if not any(board.blocks_sight(hex_) for hex_ in between):
            return True
    return False


@dataclass(frozen=True)
class AttackOption:
    move_to: Hex
    steps: int
    target: Piece
    kind: str  # "melee" or "ranged"


def attack_options(board: Board, piece: Piece) -> List[AttackOption]:
    """
    Every (move, target, attack type) the piece can make this turn.

    Melee hits adjacent enemies. Ranged needs the target within range and in
    line of sight (Indirect Fire ignores sight), and is unavailable while an
    enemy is adjacent. A unit cannot move after attacking, so the move always
    comes first.
    """
    enemies = board.enemies_of(piece)
    indirect = piece.has_trait("IndirectFire")
    options = []

    for destination, steps in sorted(reachable_hexes(board, piece).items()):
        adjacent = [e for e in enemies if e.position.distance(destination) == 1]
        options += [AttackOption(destination, steps, enemy, "melee") for enemy in adjacent]
        if adjacent or not piece.ranged_range:
            continue
        for enemy in enemies:
            in_range = 1 < enemy.position.distance(destination) <= piece.ranged_range
            if in_range and (indirect or has_line_of_sight(board, destination, enemy.position)):
                options.append(AttackOption(destination, steps, enemy, "ranged"))
    return options


# ── Map bank ───────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class SpawnLayout:
    spawn_id: str
    enemies: Dict[Hex, str]


@dataclass(frozen=True)
class BattleMap:
    """One boss map: its hexes and terrain, deployment hexes and known enemy spawns."""

    boss: str
    map_id: str
    cells: Dict[Hex, Cell]
    deploy: Tuple[Hex, ...]
    spawns: Tuple[SpawnLayout, ...] = field(default_factory=tuple)

    def board(self, pieces=()) -> Board:
        return Board(self.cells, tuple(pieces))


def _terrain(name: str) -> Terrain:
    try:
        return TERRAIN[name]
    except KeyError:
        raise ValueError(f"unknown terrain {name!r}; expected one of {sorted(TERRAIN)}") from None


def battle_map_from_dict(data: dict) -> BattleMap:
    """
    Build a BattleMap from its JSON form:

    {"boss": "...", "map": "...",
     "cells": {"q,r": "Terrain", ...},
     "sightBlockers": ["q,r", ...],
     "deploy": ["q,r", ...],
     "spawns": [{"id": "a", "enemies": {"q,r": "Unit name"}}]}
    """
    blockers = {Hex.parse(text) for text in data.get("sightBlockers", [])}
    cells = {
        Hex.parse(text): Cell(_terrain(name), Hex.parse(text) in blockers)
        for text, name in data["cells"].items()
    }
    deploy = tuple(Hex.parse(text) for text in data.get("deploy", []))
    spawns = tuple(
        SpawnLayout(spawn["id"], {Hex.parse(text): name for text, name in spawn["enemies"].items()})
        for spawn in data.get("spawns", [])
    )

    placed = list(deploy) + [hex_ for spawn in spawns for hex_ in spawn.enemies] + list(blockers)
    off_map = sorted(str(hex_) for hex_ in placed if hex_ not in cells)
    if off_map:
        raise ValueError(f"hexes not on the map: {', '.join(off_map)}")
    return BattleMap(data["boss"], data["map"], cells, deploy, spawns)


def battle_map_to_dict(battle_map: BattleMap) -> dict:
    return {
        "boss": battle_map.boss,
        "map": battle_map.map_id,
        "cells": {str(hex_): cell.terrain.name for hex_, cell in sorted(battle_map.cells.items())},
        "sightBlockers": [str(hex_) for hex_, cell in sorted(battle_map.cells.items()) if cell.blocks_sight],
        "deploy": [str(hex_) for hex_ in battle_map.deploy],
        "spawns": [
            {"id": spawn.spawn_id, "enemies": {str(hex_): name for hex_, name in sorted(spawn.enemies.items())}}
            for spawn in battle_map.spawns
        ],
    }


def load_battle_map(path) -> BattleMap:
    return battle_map_from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


def save_battle_map(battle_map: BattleMap, path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(battle_map_to_dict(battle_map), indent=2) + "\n", encoding="utf-8")
    return path


# ── Unit profiles ──────────────────────────────────────────────────────────────

def load_unit_profiles(path) -> Dict[str, dict]:
    """Movement, range and traits per unit id, from a JSON file you can check in-game."""
    return json.loads(Path(path).read_text(encoding="utf-8"))["units"]


def piece_from_profile(unit_id: str, profiles: Dict[str, dict], side: str, position: Hex) -> Piece:
    try:
        profile = profiles[unit_id]
    except KeyError:
        raise ValueError(f"no profile for unit {unit_id!r}") from None
    return Piece(
        name=profile.get("name", unit_id),
        side=side,
        position=position,
        movement=int(profile.get("movement", 0)),
        ranged_range=int(profile.get("range", 0)),
        traits=frozenset(profile.get("traits", [])),
    )
