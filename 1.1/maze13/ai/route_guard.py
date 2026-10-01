"""Adaptive Escape Route.

Trap 과 Creature 를 "지나가고 싶지 않은 칸"으로 보고 현재 목표까지 안전한 길이 남아
있는지 검사한다. 막혀 있으면 내부 벽을 최소 개수만 열어 우회로를 만든다.

원본 Maze 와 TXT 는 절대 바뀌지 않는다. runtime 개방은 opened_walls 집합에만 남고,
maze.model.blocks() 가 그 집합을 보기 때문에 이동 / Ray / LOS 가 자동으로 같이 열린다.

위치: 이 모듈은 maze.generator(생성 단계 보정)와 game.engine(runtime) 양쪽이 쓴다.
두 곳 모두 이미 ai 를 import 하고 있으므로 ai/ 에 두면 새 의존 방향이 생기지 않는다.
Game 객체는 import 하지 않고 Maze / 좌표만 받는 순수 함수로 유지한다.
"""

from typing import NamedTuple

from ai.pathfinding import bfs, distances
from maze.model import FLOOR, KEY, WALL, Maze, blocks

MAX_DYNAMIC_OPENS = 2         # 게임 한 판에서 runtime 으로 열 수 있는 벽 수
MAX_TRAP_REPAIR_OPENS = 2     # 생성 단계에서 Trap 우회로를 만들려고 열 수 있는 벽 수

ALREADY_SAFE = "already_safe"
OPENED_WALL = "opened_wall"
NO_CANDIDATE = "no_candidate"


class Guard(NamedTuple):
    status: str
    opened: tuple = ()


# ---- 목표와 위험 지역 -------------------------------------------------------

def current_goal(maze: Maze, opened_doors=()):
    """아직 열지 않은 Door 가 있으면 그 Door, 없으면 Exit 가 현재 목표다."""
    closed = [door for door in maze.doors if door not in opened_doors]
    return closed[0] if closed else maze.exit


def danger_cells(maze: Maze, creature=None) -> set:
    """Safe Route 에서만 막는 칸. 실제 게임에서 Trap 은 그대로 지나갈 수 있다."""
    blocked = set(maze.traps)
    if creature is not None and getattr(creature, "active", False):
        blocked.add(tuple(creature.position))
    return blocked


def safe_path(maze: Maze, start, goal, has_key=False, opened_doors=(),
              opened_walls=(), blocked=()):
    """Player 규칙(Key/Door)을 그대로 쓰되 blocked 칸을 피해 가는 경로."""
    if goal is None:
        return None
    blocked = set(blocked) - {tuple(start)}   # 지금 서 있는 칸은 막지 않는다
    return bfs(maze, start=start, goal=goal, has_key=has_key,
               opened_walls=opened_walls, extra_blocked=blocked).path


# ---- 벽 후보 ---------------------------------------------------------------

def _is_passage(maze: Maze, pos, opened_walls=()) -> bool:
    return maze.in_bounds(pos) and (maze.tile(pos) != WALL or pos in opened_walls)


def candidate_walls(maze: Maze, opened_walls=()) -> list:
    """두 통로 사이에 낀 내부 벽만 후보로 삼는다.

    두꺼운 벽 한가운데를 뚫으면 방처럼 되고 통로가 이어지지도 않으므로 제외한다.
    외곽 벽은 range 에서 이미 빠진다 (영구 불변).
    """
    found = []
    for row in range(1, maze.height - 1):
        for col in range(1, maze.width - 1):
            pos = (row, col)
            if maze.tile(pos) != WALL or pos in opened_walls:
                continue
            vertical = (_is_passage(maze, (row - 1, col), opened_walls)
                        and _is_passage(maze, (row + 1, col), opened_walls))
            horizontal = (_is_passage(maze, (row, col - 1), opened_walls)
                          and _is_passage(maze, (row, col + 1), opened_walls))
            if vertical or horizontal:
                found.append(pos)
    return found


def keeps_door_required(maze: Maze, opened_walls=(), opened_doors=()) -> bool:
    """벽을 열어도 Door 가 여전히 필수 관문인가.

    이미 연 문이라면 우회 논점이 없다. 아직 닫혀 있다면 Key 를 지운 미로에서
    S->E 가 여전히 불가능해야 한다 (기존 생성기 검증과 같은 기준).
    """
    if not maze.doors or all(door in opened_doors for door in maze.doors):
        return True
    keyless = Maze(tuple(line.replace(KEY, FLOOR) for line in maze.grid))
    return bfs(keyless, opened_walls=opened_walls).path is None


def choose_wall_to_open(maze: Maze, start, goal, has_key=False, opened_doors=(),
                        opened_walls=(), blocked=()):
    """길을 실제로 복구하면서 Door 를 무력화하지 않는 벽 중 가장 나은 하나."""
    ranked = []
    avoid = set(maze.doors) | ({maze.exit} if maze.exit else set())
    for wall in candidate_walls(maze, opened_walls):
        trial = set(opened_walls) | {wall}
        path = safe_path(maze, start, goal, has_key, opened_doors, trial, blocked)
        if path is None:
            continue
        if not keeps_door_required(maze, trial, opened_doors):
            continue
        penalty = 0
        if any(abs(wall[0] - c[0]) + abs(wall[1] - c[1]) <= 1 for c in avoid):
            penalty += 2                      # Door / Exit 바로 옆은 피한다
        if abs(wall[0] - start[0]) + abs(wall[1] - start[1]) <= 1:
            penalty += 1                      # Player 발밑도 피한다
        # 같은 점수면 우회로가 긴 쪽(= 지름길이 아닌 쪽)을 먼저, 그다음 좌표 순.
        ranked.append((penalty, -len(path), wall))
    if not ranked:
        return None
    return min(ranked)[2]


def _widening_wall(maze: Maze, start, has_key=False, opened_doors=(),
                   opened_walls=(), blocked=()):
    """한 장으로는 길이 안 열릴 때, 갈 수 있는 범위를 가장 많이 넓히는 벽.

    두 장째를 고르기 위한 한 단계짜리 greedy 다. 완전 탐색은 하지 않는다.
    """
    best = None
    for wall in candidate_walls(maze, opened_walls):
        trial = set(opened_walls) | {wall}
        if not keeps_door_required(maze, trial, opened_doors):
            continue
        reach = len(distances(maze, start=start, has_key=has_key,
                              opened_walls=trial, extra_blocked=set(blocked) - {tuple(start)}))
        score = (-reach, wall)
        if best is None or score < best[0]:
            best = (score, wall)
    return best[1] if best else None


def _next_wall(maze, start, goal, has_key, opened_doors, opened_walls, blocked):
    """길을 바로 복구하는 벽을 먼저 찾고, 없으면 범위를 넓히는 벽을 고른다."""
    return (choose_wall_to_open(maze, start, goal, has_key, opened_doors,
                                opened_walls, blocked)
            or _widening_wall(maze, start, has_key, opened_doors, opened_walls, blocked))


# ---- runtime 진입점 --------------------------------------------------------

def ensure_safe_route(maze: Maze, start, has_key=False, opened_doors=(),
                      opened_walls=None, creature=None, goal=None,
                      max_opens=MAX_DYNAMIC_OPENS) -> Guard:
    """현재 목표까지 안전한 길이 없으면 벽을 최소 개수만 연다.

    opened_walls 집합을 직접 갱신하고 결과를 돌려준다. 이미 안전하면 아무것도 하지 않는다.
    """
    opened_walls = set() if opened_walls is None else opened_walls
    goal = current_goal(maze, opened_doors) if goal is None else goal
    blocked = danger_cells(maze, creature)
    newly = []

    for _ in range(max_opens + 1):            # 무한 루프가 되지 않도록 횟수를 못 박는다
        if safe_path(maze, start, goal, has_key, opened_doors,
                     opened_walls, blocked) is not None:
            return Guard(OPENED_WALL if newly else ALREADY_SAFE, tuple(newly))
        if len(opened_walls) >= max_opens:
            break
        wall = _next_wall(maze, start, goal, has_key, opened_doors,
                          opened_walls, blocked)
        if wall is None:
            break
        opened_walls.add(wall)
        newly.append(wall)
    return Guard(NO_CANDIDATE, tuple(newly))


# ---- 생성 단계 Trap 보정 ----------------------------------------------------

def trap_safe_walls(maze: Maze, max_opens=MAX_TRAP_REPAIR_OPENS):
    """모든 Trap 을 피해 클리어하려면 뚫어야 할 내부 벽 목록.

    이미 가능하면 빈 목록, 제한 안에서 고치지 못하면 None.
    runtime 과 달리 이 결과는 생성되는 Maze 자체를 Floor 로 바꾸는 데 쓰인다.
    """
    if maze.start is None or maze.exit is None:
        return None
    blocked = set(maze.traps)
    opened: set = set()
    picked = []
    for _ in range(max_opens + 1):
        if safe_path(maze, maze.start, maze.exit, False, (), opened, blocked) is not None:
            return picked
        if len(opened) >= max_opens:
            break
        wall = _next_wall(maze, maze.start, maze.exit, False, (), opened, blocked)
        if wall is None:
            break
        opened.add(wall)
        picked.append(wall)
    return None
