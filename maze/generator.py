"""Randomized DFS (recursive backtracking) 미로 생성.

loop_ratio > 0 이면 내부 벽 일부를 허물어 루프가 있는 braided maze 가 된다.
specials=True 면 K / D / T / G 까지 배치하고 validator 로 확인한다.
"""

import random

from ai import route_guard
from ai.pathfinding import bfs, distances, grid_distances
from maze.model import (
    CREATURE,
    DOOR,
    EXIT,
    FLOOR,
    KEY,
    MIN_SIZE,
    START,
    TRAP,
    WALL,
    Maze,
)
from maze.validator import validate

# Creature 가 시작 지점 바로 옆에서 튀어나오지 않도록 하는 최소 거리.
MIN_SPAWN_DISTANCE = 5
# Creature spawn 이 다른 특수 타일에 붙어 있지 않도록 하는 graph distance 하한.
MIN_SPAWN_TO_KEY = 4
MIN_SPAWN_TO_EXIT = 4
MIN_SPAWN_TO_TRAP = 2
# Door 를 S->E 경로의 어느 지점에 두고 싶은지 (가까운 후보부터 시도).
DOOR_PATH_RATIO = 0.70
PLACEMENT_ATTEMPTS = 20
TRAP_SAMPLE = 25        # Trap 후보를 전수 검사하지 않고 이만큼만 본다


def generate(width: int = 21, height: int = 21, seed=None,
             loop_ratio: float = 0.0, specials: bool = False) -> Maze:
    """미로를 만들어 돌려준다.

    loop_ratio: 0.0 이면 perfect maze, 클수록 우회로가 많아진다 (0.0 ~ 1.0).
    specials:   True 면 Key / Door / Trap / Creature spawn 도 배치한다.
    같은 인자 + 같은 seed 면 항상 같은 미로가 나온다.
    특수 타일 배치에 실패하면 이유를 담은 ValueError 를 낸다.
    """
    width = _odd_at_least(width)
    height = _odd_at_least(height)
    rng = random.Random(seed)

    grid = [[WALL] * width for _ in range(height)]
    _carve(grid, (1, 1), rng)
    if loop_ratio > 0:
        _braid(grid, rng, loop_ratio)

    start = _farthest(grid, (1, 1))
    goal = _farthest(grid, start)
    grid[start[0]][start[1]] = START
    grid[goal[0]][goal[1]] = EXIT

    if specials:
        failure = _place_specials(grid, rng) or _repair_trap_route(grid)
        if failure:
            raise ValueError(failure)
    return _as_maze(grid)


def _repair_trap_route(grid) -> str | None:
    """Trap 을 전부 피해서 클리어할 수 있게 내부 벽을 최소 개수만 통로로 바꾼다.

    runtime 개방이 아니라 생성 중인 Maze 자체를 고치는 것이므로 결과 TXT 는
    그냥 통로가 하나 더 있는 정상 미로다.
    """
    walls = route_guard.trap_safe_walls(_as_maze(grid))
    if walls is None:
        return ("모든 Trap 을 피해 Exit 에 도달할 우회로를 만들지 못했습니다. "
                "loop_ratio 를 올리거나 다른 seed 를 쓰세요.")
    for row, col in walls:
        grid[row][col] = FLOOR
    return None


def _odd_at_least(size: int) -> int:
    size = max(size, MIN_SIZE + 1)
    return size if size % 2 else size + 1


def _as_maze(grid) -> Maze:
    return Maze(tuple("".join(row) for row in grid))


def _farthest(grid, origin) -> tuple[int, int]:
    found = distances(_as_maze(grid), origin)
    return max(found, key=found.get)


def _carve(grid, start, rng) -> None:
    """벽으로 가득 찬 격자에서 두 칸씩 전진하며 사이 벽을 허문다."""
    grid[start[0]][start[1]] = FLOOR
    stack = [start]
    while stack:
        row, col = stack[-1]
        options = []
        for drow, dcol in ((-2, 0), (0, -2), (2, 0), (0, 2)):
            nrow, ncol = row + drow, col + dcol
            if 0 < nrow < len(grid) - 1 and 0 < ncol < len(grid[0]) - 1:
                if grid[nrow][ncol] == WALL:
                    options.append((nrow, ncol, drow, dcol))
        if not options:
            stack.pop()
            continue
        nrow, ncol, drow, dcol = rng.choice(options)
        grid[row + drow // 2][col + dcol // 2] = FLOOR
        grid[nrow][ncol] = FLOOR
        stack.append((nrow, ncol))


def _braid(grid, rng, loop_ratio: float) -> None:
    """두 통로 사이의 벽만 골라서 허물어 루프를 만든다.

    허무는 대상은 행/열 중 정확히 하나만 홀수인 내부 벽, 즉 cell 과 cell 사이의
    칸뿐이다. (짝수, 짝수) 기둥은 남으므로 2x2 이상의 넓은 방이 생기지 않고,
    벽을 지우기만 하므로 연결성도 깨지지 않는다.
    """
    candidates = [
        (row, col)
        for row in range(1, len(grid) - 1)
        for col in range(1, len(grid[0]) - 1)
        if grid[row][col] == WALL and (row % 2) != (col % 2)
    ]
    candidates.sort()  # rng.sample 결과를 재현 가능하게 한다.
    for row, col in rng.sample(candidates, int(len(candidates) * min(loop_ratio, 1.0))):
        grid[row][col] = FLOOR


def _place_specials(grid, rng) -> str | None:
    """K / D / T / G 를 배치한다. 성공하면 None, 실패하면 이유 문자열."""
    maze = _as_maze(grid)
    start, goal = maze.start, maze.exit
    path = bfs(maze).path
    if path is None:
        return "S 에서 E 로 가는 경로가 없어 특수 타일을 배치할 수 없습니다."

    candidates = _blocking_cells(grid, start, goal, path)
    if not candidates:
        return ("S 에서 E 로 가는 길을 막을 수 있는 Door 자리가 없습니다. "
                "loop_ratio 를 낮추세요.")

    reason = "제한된 시도 안에서 유효한 특수 타일 배치를 찾지 못했습니다."
    for door in candidates[:PLACEMENT_ATTEMPTS]:
        grid[door[0]][door[1]] = DOOR
        # Door 를 먼저 써 두면 여기가 그대로 "문을 통과하지 않고 갈 수 있는 영역".
        before = distances(_as_maze(grid), start)
        chosen = {start, goal, door}

        key = _pick_key(grid, before)
        if key is None:
            reason = "Door 이전 영역에 Key 를 놓을 자리가 없습니다."
            _undo(grid, chosen - {start, goal})
            continue
        grid[key[0]][key[1]] = KEY
        chosen.add(key)

        route = bfs(_as_maze(grid)).path  # Key 를 먹고 Door 를 지나는 실제 동선
        if route is not None:
            trap = _pick_trap(grid, route, chosen, rng)
            if trap is not None:
                grid[trap[0]][trap[1]] = TRAP
                chosen.add(trap)

        spawn = _pick_spawn(grid, before, chosen, key, goal, trap, rng)
        if spawn is None:
            reason = ("Creature spawn 을 다른 특수 타일에서 충분히 떨어뜨릴 자리가 "
                      "없습니다.")
            _undo(grid, chosen - {start, goal})
            continue
        grid[spawn[0]][spawn[1]] = CREATURE
        chosen.add(spawn)

        errors = validate(_as_maze(grid))
        if not errors:
            return None
        reason = "배치 후 검증 실패: " + errors[0]
        _undo(grid, chosen - {start, goal})
    return reason


def _blocking_cells(grid, start, goal, path) -> list[tuple[int, int]]:
    """벽으로 막으면 E 가 실제로 끊기는 경로 칸들. 원하는 진행률에 가까운 순서."""
    found = []
    for index, cell in enumerate(path[1:-1], start=1):
        if grid[cell[0]][cell[1]] != FLOOR:
            continue
        grid[cell[0]][cell[1]] = WALL
        if goal not in distances(_as_maze(grid), start):
            found.append((index, cell))
        grid[cell[0]][cell[1]] = FLOOR
    target = len(path) * DOOR_PATH_RATIO
    found.sort(key=lambda item: (abs(item[0] - target), item[1]))
    return [cell for _, cell in found]


def _undo(grid, cells) -> None:
    for row, col in cells:
        grid[row][col] = FLOOR


def _pick_key(grid, before):
    """Door 이전 영역에서 S 로부터 가장 먼 칸. 되돌아오는 동선이 생긴다."""
    candidates = [c for c in before if grid[c[0]][c[1]] == FLOOR]
    if not candidates:
        return None
    return max(candidates, key=lambda c: (before[c], c))


def _pick_trap(grid, route, chosen, rng):
    """실제 동선 위의 칸. 단 막아도 우회로가 남는 칸을 우선한다.

    외길 한가운데에 놓으면 함정이 '선택'이 아니라 강제 통행료가 된다. 루프가 없는
    미로에서는 그런 칸이 없으므로, 그때만 아무 동선 칸이나 쓰고 뒤에서 벽을 뚫어 고친다.
    """
    maze = _as_maze(grid)
    on_route = [c for c in route if c not in chosen and grid[c[0]][c[1]] == FLOOR]
    sample = sorted(on_route)
    rng.shuffle(sample)
    for cell in sample[:TRAP_SAMPLE]:          # 전수 검사는 경로가 길어지면 너무 비싸다
        if bfs(maze, extra_blocked={cell}).path is not None:
            return cell
    return _pick(rng, on_route)


def _pick_spawn(grid, before, chosen, key, goal, trap, rng):
    """Start 뿐 아니라 Key / Exit / Trap 에서도 graph distance 로 떨어뜨린다."""
    maze = _as_maze(grid)
    through_doors = set(maze.doors)          # 문 상태와 무관한 순수 격자 거리
    far_from = {}
    for label, cell, least in ((KEY, key, MIN_SPAWN_TO_KEY),
                               (EXIT, goal, MIN_SPAWN_TO_EXIT),
                               (TRAP, trap, MIN_SPAWN_TO_TRAP)):
        if cell is not None:
            far_from[label] = (grid_distances(maze, cell, through_doors), least)
    candidates = [
        c for c, dist in before.items()
        if dist >= MIN_SPAWN_DISTANCE and c not in chosen and grid[c[0]][c[1]] == FLOOR
        and all(steps.get(c, 0) >= least for steps, least in far_from.values())
    ]
    return _pick(rng, candidates)


def _pick(rng, candidates):
    return rng.choice(sorted(candidates)) if candidates else None
