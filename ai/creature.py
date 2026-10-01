"""Creature FSM. 입력은 Observation 하나뿐이다.

update() 는 Player 객체도 Player 좌표도 받지 않는다. 지금 보이는 위치와 마지막으로
본 위치의 기억만으로 행동한다. 그래서 '몰래 실제 위치를 참조하는' 추적이 구조적으로
불가능하다.

    DORMANT ──(Key 획득)──▶ PATROL ──(발견)──▶ CHASE
                              ▲                  │
                              │ (기억 만료/탐색 실패) │ (시야 상실)
                              └──────── SEARCH ◀──┘
"""

import random
from dataclasses import dataclass, field

from ai.pathfinding import grid_astar, grid_distances, walkable_neighbors
from maze.model import FLOOR, neighbors

DORMANT = "dormant"
PATROL = "patrol"
CHASE = "chase"
SEARCH = "search"

MEMORY_DURATION = 5.0       # 초. 마지막 관측 위치를 이만큼 기억한다.
# 상태별 이동 간격(초). 값이 클수록 한 칸 옮기는 데 오래 걸린다 = 느리다.
# 순찰은 느긋하게, 추격은 조금 빠르게.
MOVE_INTERVAL = 0.58
MOVE_INTERVALS = {"patrol": 0.70, "search": 0.64, "chase": 0.58}
SEARCH_STEPS = 4            # 마지막 관측 위치 주변을 몇 군데 확인할지
SEARCH_RADIUS = 3
PATROL_MIN_DISTANCE = 5

STEP_FACING = {(-1, 0): "w", (0, -1): "a", (1, 0): "s", (0, 1): "d"}


@dataclass
class Creature:
    position: tuple[int, int]
    facing: str = "s"
    state: str = DORMANT
    active: bool = False
    last_seen_position: tuple[int, int] | None = None
    memory_remaining: float = 0.0
    target: tuple[int, int] | None = None
    path: list[tuple[int, int]] = field(default_factory=list)
    searches_left: int = 0
    move_timer: float = 0.0
    rng: random.Random = field(default_factory=random.Random)

    def activate(self) -> None:
        """Player 가 Key 를 획득했을 때 Game 이 불러 준다."""
        if not self.active:
            self.active = True
            self.state = PATROL

    # ---- 매 프레임 --------------------------------------------------------

    def update(self, observation, maze, opened_doors=(), seconds: float = 0.0,
               opened_walls=()) -> None:
        if not self.active:
            return
        self._remember(observation, seconds)
        self._transition(observation)

        self.move_timer -= seconds
        if self.move_timer > 0:
            return
        self.move_timer = MOVE_INTERVALS.get(self.state, MOVE_INTERVAL)
        self._advance(maze, opened_doors, opened_walls)

    def _remember(self, observation, seconds: float) -> None:
        if observation.visible:
            self.last_seen_position = observation.position
            self.memory_remaining = MEMORY_DURATION
        elif self.memory_remaining > 0:
            self.memory_remaining = max(0.0, self.memory_remaining - seconds)

    def _transition(self, observation) -> None:
        if observation.visible:
            if self.state != CHASE or self.target != observation.position:
                self.path = []
            self.state = CHASE
            self.target = observation.position
            self.searches_left = SEARCH_STEPS
            return

        if self.state == CHASE:                     # 방금 놓쳤다
            self.state = SEARCH
            self.target = self.last_seen_position
            self.path = []
            return

        if self.state == SEARCH and self.memory_remaining <= 0:
            self._forget()

    def _forget(self) -> None:
        self.state = PATROL
        self.last_seen_position = None
        self.target = None
        self.path = []
        self.searches_left = 0

    # ---- 이동 -------------------------------------------------------------

    def _advance(self, maze, opened_doors, opened_walls=()) -> None:
        # CHASE 중에는 목표를 바꾸지 않는다. 관측 위치에 이미 서 있더라도 다음 관측이
        # 목표를 갱신해 주므로, 여기서 순찰 목적지를 고르면 추격을 놓친다.
        if self.state != CHASE and (self.target is None or self.position == self.target):
            self._choose_target(maze, opened_doors, opened_walls)
        if self.target is None:
            return
        if not self.path:
            result = grid_astar(maze, self.position, self.target, opened_doors,
                                opened_walls)
            if result.path is None:
                self.target = None
                return
            self.path = result.path[1:]             # 현재 칸은 빼고
        if self.path:
            self._step_to(self.path.pop(0))

    def _step_to(self, cell) -> None:
        drow = cell[0] - self.position[0]
        dcol = cell[1] - self.position[1]
        self.facing = STEP_FACING.get((drow, dcol), self.facing)
        self.position = cell

    def _choose_target(self, maze, opened_doors, opened_walls=()) -> None:
        """도착했거나 목표가 없을 때 다음 목적지를 정한다."""
        if self.state == SEARCH:
            self.target = self._search_target(maze, opened_doors, opened_walls)
            if self.target is None:
                self._forget()
                self.target = self._patrol_target(maze, opened_doors, opened_walls)
        else:
            self.target = self._patrol_target(maze, opened_doors, opened_walls)
        self.path = []

    def _search_target(self, maze, opened_doors, opened_walls=()):
        """마지막 관측 위치 주변을 정해진 횟수만큼 둘러본다."""
        if self.last_seen_position is None or self.searches_left <= 0:
            return None
        if self.position != self.last_seen_position and self.searches_left == SEARCH_STEPS:
            return self.last_seen_position          # 아직 그 자리에 가는 중
        self.searches_left -= 1
        reachable = grid_distances(maze, self.position, opened_doors, opened_walls)
        anchor = self.last_seen_position
        nearby = [cell for cell, steps in reachable.items()
                  if 0 < steps <= SEARCH_RADIUS
                  and abs(cell[0] - anchor[0]) + abs(cell[1] - anchor[1]) <= SEARCH_RADIUS]
        return self.rng.choice(sorted(nearby)) if nearby else None

    def _patrol_target(self, maze, opened_doors, opened_walls=()):
        """평범한 통로 칸 하나만 목적지로 삼는다.

        Exit / Key / Trap / Door / Start / Spawn 은 순찰 목적지가 아니다.
        (추격 중에는 제한이 없으므로 Player 를 따라 Exit 까지 갈 수 있다.)
        """
        reachable = grid_distances(maze, self.position, opened_doors, opened_walls)
        plain = [cell for cell in reachable
                 if maze.tile(cell) == FLOOR or cell in opened_walls]
        far = [cell for cell in plain if reachable[cell] >= PATROL_MIN_DISTANCE]
        if not far:
            far = [cell for cell in plain if reachable[cell] > 0]
        return self.rng.choice(sorted(far)) if far else None


def spawn_for(maze, rng=None) -> Creature | None:
    """맵에 G 가 있으면 Creature 를 하나 만든다. 없으면 None (Creature 없는 맵)."""
    spawns = maze.creature_spawns
    if not spawns:
        return None
    position = spawns[0]
    facing = "s"
    for cell in neighbors(position):
        if cell in walkable_neighbors(maze, position):
            facing = STEP_FACING[(cell[0] - position[0], cell[1] - position[1])]
            break
    return Creature(position=position, facing=facing,
                    rng=rng if rng is not None else random.Random())
