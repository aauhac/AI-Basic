"""BFS / DFS / A* over the maze.

세 알고리즘 모두 (row, col, has_key) 를 하나의 상태로 쓰는 state-space 탐색이다.
좌표만 쓰면 Key/Door 규칙을 무시한 경로가 나오므로, 실제 게임 규칙과 같은 경로를
돌려주려면 열쇠 보유 여부가 상태에 들어가야 한다.

visited 는 탐색 중 방문 처리한 서로 다른 상태의 개수다.
실행시간은 여기서 재지 않는다 (benchmark 에서 외부 측정).
"""

import heapq
from collections import deque
from typing import NamedTuple

from maze.model import DOOR, KEY, WALKABLE_TILES, blocks, neighbors


class Result(NamedTuple):
    path: list[tuple[int, int]] | None  # 도달 불가면 None
    visited: int


State = tuple[int, int, bool]  # (row, col, has_key)


def _start_state(maze, start, has_key) -> State:
    row, col = maze.start if start is None else start
    return (row, col, has_key)


def _next_states(maze, state: State, opened_walls=(), extra_blocked=()):
    """Player 규칙. Door 는 열쇠를 들고 들어가며 열 수 있다.

    extra_blocked 는 "지금은 지나가고 싶지 않은 칸"(Trap, Creature)이며 Maze 를
    바꾸지 않고 탐색에서만 막는다.
    """
    row, col, has_key = state
    for pos in neighbors((row, col)):
        if pos in extra_blocked:
            continue
        tile = maze.tile(pos) if maze.in_bounds(pos) else WALL
        if tile == DOOR:
            if not has_key:
                continue
        elif blocks(maze, pos, (), opened_walls):
            continue
        yield (pos[0], pos[1], has_key or tile == KEY)


def _rebuild(came_from, state) -> list[tuple[int, int]]:
    path = []
    while state is not None:
        path.append((state[0], state[1]))
        state = came_from[state]
    path.reverse()
    return path


def bfs(maze, start=None, goal=None, has_key=False,
        opened_walls=(), extra_blocked=()) -> Result:
    """최단 경로 (이동 횟수 기준)."""
    goal = maze.exit if goal is None else goal
    first = _start_state(maze, start, has_key)
    came_from: dict[State, State | None] = {first: None}
    queue = deque([first])
    while queue:
        state = queue.popleft()
        if (state[0], state[1]) == goal:
            return Result(_rebuild(came_from, state), len(came_from))
        for nxt in _next_states(maze, state, opened_walls, extra_blocked):
            if nxt not in came_from:
                came_from[nxt] = state
                queue.append(nxt)
    return Result(None, len(came_from))


def dfs(maze, start=None, goal=None, has_key=False,
        opened_walls=(), extra_blocked=()) -> Result:
    """도달 가능한 경로 하나. 최단은 보장하지 않는다."""
    goal = maze.exit if goal is None else goal
    first = _start_state(maze, start, has_key)
    came_from: dict[State, State | None] = {first: None}
    stack = [first]
    while stack:
        state = stack.pop()
        if (state[0], state[1]) == goal:
            return Result(_rebuild(came_from, state), len(came_from))
        for nxt in _next_states(maze, state, opened_walls, extra_blocked):
            if nxt not in came_from:
                came_from[nxt] = state
                stack.append(nxt)
    return Result(None, len(came_from))


def distances(maze, start=None, has_key=False,
              opened_walls=(), extra_blocked=()) -> dict[tuple[int, int], int]:
    """start 에서 각 칸까지의 최단 이동 수. 도달 못 하는 칸은 빠진다.

    generator 의 S/E 배치와 특수 타일 배치가 쓰는 공용 primitive.
    Door 는 has_key=False 일 때 그대로 벽처럼 막으므로, 격자에 D 를 먼저 써 두면
    "문을 통과하지 않고 갈 수 있는 영역" 이 그대로 나온다.
    """
    first = _start_state(maze, start, has_key)
    # 방문 처리는 반드시 state 단위로 한다. 좌표로만 하면 "열쇠를 든 상태" 가
    # 이미 지나온 칸에서 막혀 사라지고, Door 뒤가 도달 불가로 잘못 나온다.
    seen = {first}
    found = {(first[0], first[1]): 0}
    queue = deque([(first, 0)])
    while queue:
        state, step = queue.popleft()
        for nxt in _next_states(maze, state, opened_walls, extra_blocked):
            if nxt in seen:
                continue
            seen.add(nxt)
            found.setdefault((nxt[0], nxt[1]), step + 1)
            queue.append((nxt, step + 1))
    return found


def farthest(maze, start=None) -> tuple[int, int]:
    """start 에서 가장 먼 칸. 같은 거리면 BFS 순서상 마지막 칸."""
    found = distances(maze, start)
    return max(found, key=found.get)


def manhattan(a: tuple[int, int], b: tuple[int, int]) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def astar(maze, start=None, goal=None, has_key=False,
        opened_walls=(), extra_blocked=()) -> Result:
    """최단 경로. heuristic 은 목표까지의 Manhattan distance."""
    goal = maze.exit if goal is None else goal
    first = _start_state(maze, start, has_key)
    came_from: dict[State, State | None] = {first: None}
    best_g = {first: 0}
    counter = 0  # 같은 f 값일 때 tie-break (State 는 비교 대상이 아님)
    heap = [(manhattan((first[0], first[1]), goal), counter, first)]
    while heap:
        _, _, state = heapq.heappop(heap)
        if (state[0], state[1]) == goal:
            return Result(_rebuild(came_from, state), len(came_from))
        g = best_g[state]
        for nxt in _next_states(maze, state, opened_walls, extra_blocked):
            if nxt in best_g and best_g[nxt] <= g + 1:
                continue
            best_g[nxt] = g + 1
            came_from[nxt] = state
            counter += 1
            heapq.heappush(heap, (g + 1 + manhattan((nxt[0], nxt[1]), goal), counter, nxt))
    return Result(None, len(came_from))


ALGORITHMS = {"bfs": bfs, "dfs": dfs, "astar": astar}

# --- 열쇠 개념이 없는 격자 탐색 (Creature 전용) --------------------------------
#
# Creature 는 열쇠를 줍지 못하므로 has_key 상태공간이 아니라 "지금 열려 있는 문" 만
# 반영하는 평범한 격자 탐색을 쓴다. Player 용 A* 에 has_key=True 를 억지로 넘겨
# 닫힌 문을 지나가게 하는 편법을 쓰지 않는다.


def walkable_neighbors(maze, pos, opened_doors=(), opened_walls=()):
    return [n for n in neighbors(pos) if not blocks(maze, n, opened_doors, opened_walls)]


def grid_distances(maze, start, opened_doors=(), opened_walls=()) -> dict[tuple[int, int], int]:
    """start 에서 각 칸까지의 이동 수. PATROL 목적지 고르기와 도달 판정에 쓴다."""
    found = {start: 0}
    queue = deque([start])
    while queue:
        current = queue.popleft()
        for nxt in walkable_neighbors(maze, current, opened_doors, opened_walls):
            if nxt not in found:
                found[nxt] = found[current] + 1
                queue.append(nxt)
    return found


def grid_astar(maze, start, goal, opened_doors=(), opened_walls=()) -> Result:
    """Manhattan heuristic A*. 닫힌 Door 는 벽과 같다."""
    if blocks(maze, goal, opened_doors, opened_walls):
        return Result(None, 0)
    came_from = {start: None}
    best_g = {start: 0}
    counter = 0
    heap = [(manhattan(start, goal), counter, start)]
    while heap:
        _, _, current = heapq.heappop(heap)
        if current == goal:
            path = []
            while current is not None:
                path.append(current)
                current = came_from[current]
            return Result(path[::-1], len(came_from))
        g = best_g[current]
        for nxt in walkable_neighbors(maze, current, opened_doors, opened_walls):
            if nxt in best_g and best_g[nxt] <= g + 1:
                continue
            best_g[nxt] = g + 1
            came_from[nxt] = current
            counter += 1
            heapq.heappush(heap, (g + 1 + manhattan(nxt, goal), counter, nxt))
    return Result(None, len(came_from))


STEP_KEYS = {(-1, 0): "w", (0, -1): "a", (1, 0): "s", (0, 1): "d"}


def moves_for(path) -> list[str]:
    """좌표 경로를 W/A/S/D 절대 방향 입력으로 바꾼다. AUTO SOLVE 가 쓴다."""
    return [STEP_KEYS[(b[0] - a[0], b[1] - a[1])] for a, b in zip(path, path[1:])]
