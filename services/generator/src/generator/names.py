"""Seeded fictional team and player names, with a blocklist safety check."""

from __future__ import annotations

import random

REAL_NAME_BLOCKLIST = frozenset(
    {
        "arsenal",
        "barcelona",
        "chelsea",
        "cristiano ronaldo",
        "erling haaland",
        "kylian mbappe",
        "liverpool",
        "lionel messi",
        "manchester city",
        "manchester united",
        "mohamed salah",
        "real madrid",
    }
)

_TEAM_STEMS = (
    "Aurelith",
    "Brindlefen",
    "Dunsmere",
    "Velmora",
    "Keldran",
    "Ossendale",
    "Rivenholt",
    "Caldrin",
    "Marroway",
    "Fallowmere",
    "Tarnwick",
    "Veynhurst",
)
_FIRST_NAMES = (
    "Aven", "Mirel", "Tovan", "Selvi", "Ordan", "Neris", "Veyla", "Calven",
    "Daro", "Ysol", "Peren", "Lunet", "Brelan", "Korin", "Evara", "Mavren",
    "Sorin", "Talar", "Orren", "Vessa", "Rovel", "Ilyan", "Noma", "Teren",
    "Savel", "Ovara", "Delsin", "Varo", "Kelm", "Etrin", "Mireva", "Jorin",
)
_LAST_NAMES = (
    "Vellorin", "Maroven", "Delsari", "Quenlow", "Ravelle", "Tervan", "Varnet",
    "Caldovar", "Mirev", "Ostrel", "Norvale", "Hadrin", "Selvaren", "Kavell",
    "Rostane", "Velorin", "Tandrel", "Orrivan", "Fensari", "Kelvaro", "Norell",
    "Veskar", "Dovren", "Salven", "Tervell", "Lurane", "Brelor", "Yavren",
    "Cenvar", "Odelin", "Marvek", "Sorevan",
)


def ensure_fictional(names: list[str]) -> None:
    """Fail closed when a generated name matches a bundled real-world name."""
    normalized = {name.casefold() for name in names}
    matches = sorted(normalized & REAL_NAME_BLOCKLIST)
    if matches:
        raise ValueError(f"generated name appears on the real-name blocklist: {matches[0]}")


def make_team_names(rng: random.Random) -> tuple[str, str]:
    stems = rng.sample(_TEAM_STEMS, 2)
    names = (f"{stems[0]} Athletic", f"{stems[1]} Rovers")
    ensure_fictional(list(names))
    return names


def make_player_names(rng: random.Random, count: int) -> list[str]:
    pairs = [(first, last) for first in _FIRST_NAMES for last in _LAST_NAMES]
    chosen = rng.sample(pairs, count)
    names = [f"{first} {last}" for first, last in chosen]
    ensure_fictional(names)
    return names