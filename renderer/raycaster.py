"""DDA Raycasting. pygame 에 의존하지 않는 순수 계산이므로 그대로 테스트할 수 있다.

좌표는 프로젝트 규약대로 (row, col) 이다. row 가 화면의 세로축(y), col 이 가로축(x)에
해당하고, 카메라 각도 0 은 +col(동쪽)을 본다.

    angle      0 -> (drow, dcol) = ( 0,  1)  동
            pi/2 -> ( 1,  0)  남 (row 증가)
              pi -> ( 0, -1)  서
           -pi/2 -> (-1,  0)  북

ray 방향을 dir + plane * camera_x 로 만들기 때문에 DDA 가 내놓는 거리는 그 자체로
카메라 평면에 수직인 거리다. 따라서 fisheye 보정을 따로 하지 않는다.
"""

import math
from dataclasses import dataclass
from typing import NamedTuple

from maze.model import WALL, blocks

DEFAULT_FOV = math.radians(66)
MAX_DISTANCE = 64.0

# 각 이동 방향이 바라보는 각도. W/A/S/D 가 그대로 여기에 대응한다.
FACING = {
    "w": -math.pi / 2,  # 북
    "a": math.pi,       # 서
    "s": math.pi / 2,   # 남
    "d": 0.0,           # 동
}


# 시계 방향 4방향. Creature Vision 도 이 표를 그대로 쓸 수 있다.
CLOCKWISE = ("w", "d", "s", "a")  # 북 -> 동 -> 남 -> 서


def turn(facing: str, steps: int) -> str:
    """facing 을 90도 단위로 돌린다. steps=+1 우회전, -1 좌회전."""
    return CLOCKWISE[(CLOCKWISE.index(facing) + steps) % 4]


def relative_move(facing: str, key: str) -> str:
    """1인칭 입력(W 전진 / S 후진 / A 좌 / D 우)을 절대 격자 방향으로 바꾼다.

    CLOCKWISE 에서 키의 위치가 곧 facing 으로부터 돌려야 할 칸 수다.
    (w=0 전진, d=1 오른쪽, s=2 뒤, a=3 왼쪽)
    """
    return turn(facing, CLOCKWISE.index(key))


@dataclass
class Camera:
    """렌더링 전용 연속 좌표. 게임의 논리 위치(정수 cell)와 섞지 않는다."""

    row: float
    col: float
    angle: float = 0.0
    fov: float = DEFAULT_FOV

    @property
    def cell(self) -> tuple[int, int]:
        return (int(self.row), int(self.col))

    @property
    def direction(self) -> tuple[float, float]:
        return (math.sin(self.angle), math.cos(self.angle))

    @property
    def plane(self) -> tuple[float, float]:
        """direction 을 90도 돌리고 tan(fov/2) 만큼 늘린 카메라 평면."""
        drow, dcol = self.direction
        scale = math.tan(self.fov / 2)
        return (dcol * scale, -drow * scale)


class Hit(NamedTuple):
    hit: bool
    tile: str
    distance: float               # 카메라 평면에 수직인 거리
    side: int                     # 0 = 세로벽(열 경계), 1 = 가로벽(행 경계)
    cell: tuple[int, int]
    wall_x: float                 # 벽면 위 0.0 ~ 1.0 위치 (texture 용, 지금은 미사용)


def blocks_ray(maze, pos: tuple[int, int], opened_doors=(), opened_walls=()) -> bool:
    """ray 를 막는 칸인가. 이동 규칙과 같아야 하므로 maze.model.blocks 를 그대로 쓴다."""
    return blocks(maze, pos, opened_doors, opened_walls)


def camera_offsets(width: int) -> list[float]:
    """화면 column 별 카메라 평면 위치 (-1 왼쪽 ~ +1 오른쪽)."""
    return [2.0 * x / width - 1.0 for x in range(width)]


def ray_direction(camera: Camera, camera_x: float) -> tuple[float, float]:
    drow, dcol = camera.direction
    prow, pcol = camera.plane
    return (drow + prow * camera_x, dcol + pcol * camera_x)


def cast(maze, origin, ray_dir, opened_doors=(), max_distance=MAX_DISTANCE,
         opened_walls=()) -> Hit:
    """origin 에서 ray_dir 로 DDA 를 돌려 처음 막히는 칸을 찾는다."""
    row, col = origin
    drow, dcol = ray_dir
    cell_row, cell_col = int(row), int(col)

    delta_row = math.inf if drow == 0 else abs(1.0 / drow)
    delta_col = math.inf if dcol == 0 else abs(1.0 / dcol)
    step_row = 1 if drow > 0 else -1
    step_col = 1 if dcol > 0 else -1
    next_row = (cell_row + 1 - row if drow > 0 else row - cell_row) * delta_row
    next_col = (cell_col + 1 - col if dcol > 0 else col - cell_col) * delta_col

    side = 0
    while True:
        if next_col < next_row:
            distance = next_col
            next_col += delta_col
            cell_col += step_col
            side = 0
        else:
            distance = next_row
            next_row += delta_row
            cell_row += step_row
            side = 1

        if distance > max_distance:
            return Hit(False, "", max_distance, side, (cell_row, cell_col), 0.0)
        if blocks_ray(maze, (cell_row, cell_col), opened_doors, opened_walls):
            along = row + distance * drow if side == 0 else col + distance * dcol
            return Hit(True, maze.tile((cell_row, cell_col)) if maze.in_bounds(
                (cell_row, cell_col)) else WALL,
                distance, side, (cell_row, cell_col), along % 1.0)


def cast_columns(maze, camera: Camera, width: int, opened_doors=(),
                 max_distance=MAX_DISTANCE, opened_walls=()) -> list[Hit]:
    """화면 한 줄 분량의 ray 결과. 이 결과의 distance 목록이 곧 z-buffer 다."""
    origin = (camera.row, camera.col)
    return [cast(maze, origin, ray_direction(camera, camera_x), opened_doors,
                 max_distance, opened_walls)
            for camera_x in camera_offsets(width)]


class Projection(NamedTuple):
    screen_x: int      # 화면상 sprite 중심 x
    depth: float       # 카메라 평면 기준 깊이 (z-buffer 와 같은 단위)
    size: int          # 이 거리에서의 기준 크기 (화면 높이 / depth)


def project_sprite(camera: Camera, world_pos, width: int, height: int) -> Projection | None:
    """Billboard sprite 하나를 화면 좌표로 투영한다. 카메라 뒤면 None.

    Key / Trap / Exit 가 모두 이 함수를 쓰고, 다음 Phase 의 Creature 도 같은 것을 쓴다.
    카메라 행렬 [plane | direction] 의 역행렬을 sprite 상대 위치에 곱하는 표준 방식이다.
    """
    drow = world_pos[0] - camera.row
    dcol = world_pos[1] - camera.col
    dir_row, dir_col = camera.direction
    plane_row, plane_col = camera.plane

    determinant = plane_col * dir_row - dir_col * plane_row
    if determinant == 0:
        return None
    inverse = 1.0 / determinant
    offset = inverse * (dir_row * dcol - dir_col * drow)
    depth = inverse * (plane_col * drow - plane_row * dcol)
    if depth <= 0.02:                      # 카메라 뒤 또는 너무 가까움
        return None
    return Projection(int(width / 2 * (1 + offset / depth)), depth, int(height / depth))


def column_span(distance: float, screen_height: int) -> tuple[int, int]:
    """거리에 따른 벽 기둥의 (top, height). 화면 높이의 4배까지만 그린다."""
    height = int(min(screen_height * 4, screen_height / max(distance, 1e-6)))
    return ((screen_height - height) // 2, height)
