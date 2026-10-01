"""미로 형식 + 실제 클리어 가능성 검사.

validate() 는 사람이 읽을 수 있는 오류 메시지 목록을 돌려준다.
빈 목록이면 유효한 미로다. custom exception 계층은 만들지 않는다.
"""

from ai.pathfinding import bfs, distances
from maze.model import (
    CREATURE,
    DOOR,
    EXIT,
    KEY,
    LEGAL_TILES,
    MIN_SIZE,
    START,
    WALL,
    Maze,
)


def validate(maze: Maze) -> list[str]:
    errors = []

    widths = {len(line) for line in maze.grid}
    if len(widths) > 1:
        errors.append(f"모든 행의 길이가 같아야 합니다. (발견된 길이: {sorted(widths)})")

    if maze.height < MIN_SIZE or min(widths) < MIN_SIZE:
        errors.append(f"미로는 최소 {MIN_SIZE}x{MIN_SIZE} 이상이어야 합니다. "
                      f"(현재 {min(widths)}x{maze.height})")

    illegal = sorted({ch for line in maze.grid for ch in line} - LEGAL_TILES)
    if illegal:
        errors.append(f"허용되지 않은 문자가 있습니다: {illegal}")

    for tile, name in ((START, "Start"), (EXIT, "Exit")):
        count = len(maze.positions_of(tile))
        if count == 0:
            errors.append(f"{name}({tile})가 존재하지 않습니다.")
        elif count > 1:
            errors.append(f"{name}({tile})가 {count}개 존재합니다. 정확히 1개여야 합니다.")

    spawns = len(maze.positions_of(CREATURE))
    if spawns > 1:
        errors.append(f"Creature Spawn(G)은 0개 또는 1개여야 합니다. (현재 {spawns}개)")

    if len(widths) == 1 and not _outer_wall_ok(maze):
        errors.append("미로의 외곽은 모두 Wall(#)이어야 합니다.")

    # 아래 검사는 격자 모양과 S/E 가 정상일 때만 의미가 있다.
    if not errors:
        errors.extend(_solvability_errors(maze))
    if not errors:
        errors.extend(_connectivity_errors(maze))

    return errors


def walkable_positions(maze: Maze) -> set[tuple[int, int]]:
    """Wall 이 아닌 모든 칸. Door 도 이동 가능한 공간으로 센다."""
    return {(row, col)
            for row, line in enumerate(maze.grid)
            for col, tile in enumerate(line)
            if tile != WALL}


def unreachable_cells(maze: Maze) -> list[tuple[int, int]]:
    """Start 에서 실제 게임 규칙상 끝내 닿을 수 없는 이동 가능 칸.

    Door 를 벽으로 보는 단순 flood fill 이 아니라 (row, col, has_key) 상태공간
    탐색 결과를 쓴다. 그래서 'Key 를 먹은 뒤에 열리는 영역' 은 고립으로 치지 않는다.
    """
    if maze.start is None:
        return []
    return sorted(walkable_positions(maze) - set(distances(maze, maze.start)))


def _connectivity_errors(maze: Maze) -> list[str]:
    orphans = unreachable_cells(maze)
    if not orphans:
        return []
    sample = ", ".join(str(pos) for pos in orphans[:5])
    more = " ..." if len(orphans) > 5 else ""
    return [f"Start에서 접근할 수 없는 이동 가능 공간이 {len(orphans)}칸 존재합니다.",
            f"예시 위치: {sample}{more}"]


def _outer_wall_ok(maze: Maze) -> bool:
    top, bottom = maze.grid[0], maze.grid[-1]
    if set(top) != {WALL} or set(bottom) != {WALL}:
        return False
    return all(line[0] == WALL and line[-1] == WALL for line in maze.grid)


def _solvability_errors(maze: Maze) -> list[str]:
    """(row, col, has_key) state-space BFS 로 실제 게임 규칙상 클리어 가능한지 본다."""
    if bfs(maze).path is not None:
        return []

    # 열쇠를 처음부터 가진 상태로도 못 가면 경로 자체가 막힌 것이다.
    if bfs(maze, has_key=True).path is None:
        return ["Exit에 도달할 수 없습니다."]

    if not maze.keys:
        return ["Key(K)가 없어 Door(D)를 열 수 없습니다."]

    reachable_key = any(bfs(maze, goal=key).path is not None for key in maze.keys)
    if not reachable_key:
        return ["Key에 도달할 수 없어 Door를 열 수 없습니다."]
    return ["Key를 획득한 뒤에도 Exit에 도달할 수 없습니다."]


def is_valid(maze: Maze) -> bool:
    return not validate(maze)
