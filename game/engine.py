"""2D 논리 게임. 렌더링과 Creature 는 여기에 들어가지 않는다.

원본 Maze 는 frozen 이라 수정할 수 없고, Door 개방 같은 변화는 모두 runtime state 다.
시간은 thread 없이 clock() 호출 시점 계산으로만 관리한다.
"""

import time

from ai import creature as creature_ai, route_guard
from ai.pathfinding import grid_astar
from ai.perception import observe
from maze.model import DOOR, EXIT, KEY, TRAP, Maze, blocks
from game.player import Player

DIRECTIONS = {
    "w": (-1, 0),  # North
    "a": (0, -1),  # West
    "s": (1, 0),   # South
    "d": (0, 1),   # East
}

TRAP_PENALTY = 5

NORMAL = "normal"
TIME_ATTACK = "time_attack"

# 시간 제한 모드(normal / time_attack)와 플레이 모드(classic / horror)는 서로 다르다.
CLASSIC = "classic"
HORROR = "horror"

# 마지막 이동에서 무슨 일이 있었는지. 2D 와 3D 가 같은 문구를 쓰도록 여기 한 곳에 둔다.
EVENT_KEY = "key"
EVENT_DOOR = "door"
EVENT_TRAP = "trap"
EVENT_LOCKED = "locked"
EVENT_TEXT = {
    EVENT_KEY: "열쇠를 획득했습니다!",
    EVENT_DOOR: "문을 열었습니다.",
    EVENT_TRAP: f"함정을 밟았습니다!  이동 횟수 +{TRAP_PENALTY}",
    EVENT_LOCKED: "잠겨 있습니다.  열쇠가 필요합니다.",
}
WARN_EVENTS = (EVENT_TRAP, EVENT_LOCKED)


class Game:
    def __init__(self, maze: Maze, time_limit: float | None = None,
                 elapsed: float = 0.0, map_name: str = "", play_mode: str = CLASSIC,
                 clock=time.monotonic):
        if maze.start is None or maze.exit is None:
            raise ValueError("Start(S)와 Exit(E)가 있는 미로가 필요합니다.")
        self.maze = maze
        self.map_name = map_name  # 기록/저장을 위한 원본 TXT 파일명
        self.play_mode = play_mode
        self.time_limit = time_limit
        self.player = Player(maze.start)
        self.opened_doors: set[tuple[int, int]] = set()
        self.visited_path: list[tuple[int, int]] = [maze.start]
        self.cleared = False
        self.caught = False
        self.creature = None      # Horror 모드에서 attach_creature() 로 붙인다
        # runtime 으로 개방된 내부 벽. 원본 Maze 의 '#' 는 그대로 두고 여기에만 담는다.
        self.opened_walls: set[tuple[int, int]] = set()
        self.route_status = route_guard.ALREADY_SAFE
        self.creature_sees_player = False   # 렌더러/디버그가 읽는 마지막 관측
        self.creature_distance = None       # 근접 경고용 보행 거리. 못 가면 None
        self.last_event = None              # 마지막 이동의 결과 (EVENT_* 또는 None)
        self._clock = clock
        self._offset = elapsed          # 이어하기로 물려받은 시간
        self._started = clock()
        self._stopped_at: float | None = None  # clear / timeout 시점

    # ---- 시간 -------------------------------------------------------------

    @property
    def mode(self) -> str:
        """시간 제한 모드. 플레이 모드는 play_mode 를 따로 본다."""
        return NORMAL if self.time_limit is None else TIME_ATTACK

    @property
    def elapsed(self) -> float:
        end = self._clock() if self._stopped_at is None else self._stopped_at
        return self._offset + (end - self._started)

    @property
    def timed_out(self) -> bool:
        if self.time_limit is None:
            return False
        if self.elapsed >= self.time_limit:
            self._freeze()
            return True
        return False

    @property
    def remaining(self) -> float | None:
        return None if self.time_limit is None else max(0.0, self.time_limit - self.elapsed)

    @property
    def over(self) -> bool:
        return self.cleared or self.timed_out or self.caught

    def _freeze(self) -> None:
        if self._stopped_at is None:
            self._stopped_at = self._clock()

    # ---- 이동 -------------------------------------------------------------

    def is_passable(self, pos: tuple[int, int]) -> bool:
        """지금 이 칸으로 들어갈 수 있는가."""
        if not self.maze.in_bounds(pos):
            return False
        if self.maze.tile(pos) == DOOR:
            # Player 만의 규칙: 열쇠를 들고 문에 들어가면서 연다.
            return pos in self.opened_doors or self.player.has_key
        # 벽 / 개방된 벽 판정은 Ray·Creature 와 같은 규칙 하나를 쓴다.
        return not blocks(self.maze, pos, (), self.opened_walls)

    def move(self, key: str) -> bool:
        """W/A/S/D 로 한 칸 이동. 이동에 성공하면 True."""
        if self.over:
            return False
        step = DIRECTIONS.get(key.lower())
        if step is None:
            return False

        row, col = self.player.position
        target = (row + step[0], col + step[1])
        self.last_event = None
        if not self.is_passable(target):
            if self.maze.in_bounds(target) and self.maze.tile(target) == DOOR:
                self.last_event = EVENT_LOCKED      # 열쇠가 없어 막힌 경우
            return False

        self.player.position = target
        self.player.move_count += 1
        self.visited_path.append(target)
        # Creature 접촉이 Exit 보다 먼저다. 순서가 아니라 규칙으로 못 박는다.
        if self._touching_creature():
            self._catch()
            return True
        self._enter(target)
        self.guard_route()
        self.refresh_creature_distance()
        return True

    # ---- Creature ---------------------------------------------------------

    def attach_creature(self, rng=None):
        """맵에 G 가 있으면 Creature 를 붙인다. Horror 모드에서만 호출한다."""
        self.creature = creature_ai.spawn_for(self.maze, rng)
        return self.creature

    def tick_creature(self, seconds: float) -> None:
        """관측 -> AI -> 잡힘 판정 -> (움직였으면) 안전 경로 점검."""
        if self.creature is None or self.over:
            return
        before = self.creature.position
        observation = observe(self.creature.position, self.creature.facing,
                              self.player.position, self.maze, self.opened_doors,
                              self.opened_walls)
        self.creature_sees_player = observation.visible
        self.creature.update(observation, self.maze, self.opened_doors, seconds,
                             self.opened_walls)
        if self.check_caught(self.creature.position):
            return
        if self.creature.position != before:   # 실제로 칸을 옮겼을 때만 검사한다
            self.guard_route()
            self.refresh_creature_distance()

    def refresh_creature_distance(self) -> None:
        """Creature 까지 실제로 몇 칸을 걸어야 하는지. 매 프레임이 아니라 이동 때만 센다."""
        if self.creature is None or not self.creature.active:
            self.creature_distance = None
            return
        result = grid_astar(self.maze, self.creature.position, self.player.position,
                            self.opened_doors, self.opened_walls)
        self.creature_distance = None if result.path is None else len(result.path) - 1

    def _touching_creature(self, position=None) -> bool:
        """깨어 있는 Creature 가 Player 와 같은 칸인가. 잡힘 판정은 이 하나뿐이다."""
        creature = self.creature
        if creature is None or not creature.active:
            return False          # DORMANT 는 장애물도 위협도 아니다
        if position is None:
            position = creature.position
        return tuple(position) == self.player.position

    def _catch(self) -> None:
        self.caught = True
        self._freeze()

    def check_caught(self, position=None) -> bool:
        """잡힘 판정은 게임 규칙이므로 렌더러가 아니라 여기에 둔다.

        이미 클리어했거나 시간이 끝난 판은 뒤집지 않는다. 반대로 Exit 칸이라는
        이유로 접촉이 무시되지도 않는다 (그 판정은 move() 에서 먼저 끝난다).
        """
        if self.cleared or self.timed_out:
            return self.caught
        if self._touching_creature(position):
            self._catch()
        return self.caught

    def guard_route(self) -> None:
        """Trap 과 Creature 를 막힌 칸으로 보고 현재 목표까지 길이 남았는지 본다."""
        if self.creature is None or not self.creature.active or self.over:
            return
        guard = route_guard.ensure_safe_route(
            self.maze, self.player.position, self.player.has_key,
            self.opened_doors, self.opened_walls, self.creature)
        self.route_status = guard.status
        if guard.opened:
            self.on_wall_opened(guard.opened)

    def on_wall_opened(self, walls) -> None:
        """렌더러가 알림을 띄우려고 덮어쓰는 훅. 기본은 아무것도 하지 않는다."""

    @property
    def current_goal(self):
        return route_guard.current_goal(self.maze, self.opened_doors)

    # ---- 칸 진입 ----------------------------------------------------------

    def _enter(self, pos: tuple[int, int]) -> None:
        tile = self.maze.tile(pos)
        if tile == KEY:
            self.player.has_key = True
            self.last_event = EVENT_KEY
            if self.creature is not None:
                self.creature.activate()   # 열쇠를 집는 순간 깨어난다
                self.refresh_creature_distance()
        elif tile == DOOR:
            self.opened_doors.add(pos)
            self.last_event = EVENT_DOOR
        elif tile == TRAP:
            self.player.move_count += TRAP_PENALTY
            self.last_event = EVENT_TRAP
        elif tile == EXIT:
            self.cleared = True
            self._freeze()
