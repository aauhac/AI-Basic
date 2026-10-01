"""2D grid maze data.

좌표는 프로젝트 전체에서 (row, col) 로 통일한다.
TXT 파일의 한 줄이 그대로 하나의 row 이므로 grid[row][col] 로 바로 접근할 수 있고,
(x, y) 를 쓰면 파일/렌더러 경계마다 축을 뒤집는 변환이 생겨서 실수가 나기 쉽다.
"""

from dataclasses import dataclass

WALL = "#"
FLOOR = "."
START = "S"
EXIT = "E"
KEY = "K"
DOOR = "D"
TRAP = "T"
CREATURE = "G"
# 과제 기호의 P. runtime player 위치 표시에만 쓰고 TXT 에는 절대 저장하지 않는다.
PLAYER_TILE = "P"

LEGAL_TILES = frozenset("#.SEKDTG")
# D 는 열쇠 상태에 따라 달라지므로 여기에 넣지 않는다.
WALKABLE_TILES = frozenset(".SEKTG")

MIN_SIZE = 10


@dataclass(frozen=True)
class Maze:
    """원본 미로. frozen + tuple 이므로 게임 중 수정할 수 없다."""

    grid: tuple[str, ...]

    @property
    def height(self) -> int:
        return len(self.grid)

    @property
    def width(self) -> int:
        return len(self.grid[0]) if self.grid else 0

    def in_bounds(self, pos: tuple[int, int]) -> bool:
        row, col = pos
        return 0 <= row < self.height and 0 <= col < len(self.grid[row])

    def tile(self, pos: tuple[int, int]) -> str:
        row, col = pos
        return self.grid[row][col]

    def positions_of(self, tile: str) -> list[tuple[int, int]]:
        return [
            (row, col)
            for row, line in enumerate(self.grid)
            for col, ch in enumerate(line)
            if ch == tile
        ]

    def first_of(self, tile: str) -> tuple[int, int] | None:
        found = self.positions_of(tile)
        return found[0] if found else None

    @property
    def start(self) -> tuple[int, int] | None:
        return self.first_of(START)

    @property
    def exit(self) -> tuple[int, int] | None:
        return self.first_of(EXIT)

    @property
    def keys(self) -> list[tuple[int, int]]:
        return self.positions_of(KEY)

    @property
    def doors(self) -> list[tuple[int, int]]:
        return self.positions_of(DOOR)

    @property
    def traps(self) -> list[tuple[int, int]]:
        return self.positions_of(TRAP)

    @property
    def creature_spawns(self) -> list[tuple[int, int]]:
        return self.positions_of(CREATURE)

    def as_text(self) -> str:
        return "\n".join(self.grid) + "\n"


def blocks(maze: Maze, pos: tuple[int, int], opened_doors=(), opened_walls=()) -> bool:
    """이 칸이 통과를 막는가. 이동 / Ray / LOS 가 전부 이 한 규칙만 쓴다.

    맵 밖은 벽으로 친다. Door 는 runtime 에 열린 것만 지나갈 수 있고, Wall 도
    runtime 에 개방된 것(opened_walls)은 통로가 된다. 원본 Maze 는 그대로 '#' 이다.
    (Player 는 열쇠를 들고 문에 '들어가면서' 여는 별개 규칙이라 Game.is_passable 을 쓴다.)
    """
    if not maze.in_bounds(pos):
        return True
    tile = maze.tile(pos)
    if tile == WALL:
        return pos not in opened_walls
    return tile == DOOR and pos not in opened_doors


def neighbors(pos: tuple[int, int]) -> list[tuple[int, int]]:
    """4방향 인접 좌표 (북, 서, 남, 동)."""
    row, col = pos
    return [(row - 1, col), (row, col - 1), (row + 1, col), (row, col + 1)]
