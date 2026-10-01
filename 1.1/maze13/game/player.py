"""Player runtime state."""

from dataclasses import dataclass


@dataclass
class Player:
    position: tuple[int, int]
    has_key: bool = False
    move_count: int = 0
