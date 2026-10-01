"""Creature 의 시각. Player 위치를 볼 수 있는 유일한 곳이다.

Creature AI 는 여기서 나온 Observation 만 받는다. observe() 가 돌려주는 것은
좌표 tuple 하나뿐이라 AI 쪽에서 Player 객체를 몰래 참조할 방법이 없다.

    Player ──▶ Perception ──▶ Observation ──▶ Creature AI

Line of Sight 는 renderer.raycaster.cast 를 그대로 쓴다. 벽/닫힌 문 판정이
화면에 보이는 것과 정확히 같아야 하기 때문이다 (두 곳 모두 maze.model.blocks 규칙).
raycaster 는 pygame 을 import 하지 않는 순수 계산 모듈이라 의존해도 문제없다.
"""

import math
from dataclasses import dataclass

from renderer.raycaster import FACING, cast

VISION_DISTANCE = 7.0           # cells
FIELD_OF_VIEW = math.radians(90)
# 반각의 코사인. acos 없이 dot product 만으로 시야각을 판정한다.
# 정확히 경계각인 대각선이 부동소수점 오차로 빠지지 않도록 경계는 포함으로 둔다.
FOV_COS = math.cos(FIELD_OF_VIEW / 2) - 1e-9


@dataclass(frozen=True)
class Observation:
    visible: bool
    position: tuple[int, int] | None = None


BLIND = Observation(False, None)


def direction_vector(facing: str) -> tuple[float, float]:
    angle = FACING[facing]
    return (math.sin(angle), math.cos(angle))


def observe(creature_position, creature_facing, player_position, maze,
            opened_doors=(), opened_walls=()) -> Observation:
    """거리 -> 시야각 -> 시선 순서로 검사한다. 셋 다 통과해야 보인다."""
    if creature_position == player_position:
        return Observation(True, tuple(player_position))

    drow = player_position[0] - creature_position[0]
    dcol = player_position[1] - creature_position[1]
    distance = math.hypot(drow, dcol)
    if distance > VISION_DISTANCE:
        return BLIND

    face_row, face_col = direction_vector(creature_facing)
    if (drow * face_row + dcol * face_col) / distance < FOV_COS:
        return BLIND

    if not has_line_of_sight(creature_position, player_position, maze,
                             opened_doors, opened_walls):
        return BLIND
    return Observation(True, tuple(player_position))


def has_line_of_sight(source, target, maze, opened_doors=(), opened_walls=()) -> bool:
    """두 칸의 중심을 잇는 직선이 벽이나 닫힌 문에 막히지 않는가."""
    origin = (source[0] + 0.5, source[1] + 0.5)
    drow = (target[0] + 0.5) - origin[0]
    dcol = (target[1] + 0.5) - origin[1]
    distance = math.hypot(drow, dcol)
    if distance == 0:
        return True
    hit = cast(maze, origin, (drow / distance, dcol / distance), opened_doors,
               max_distance=distance, opened_walls=opened_walls)
    # 목표보다 앞에서 막히면 안 보인다. 목표 칸 자체에 닿는 경우는 허용한다.
    return not hit.hit or hit.distance >= distance - 1e-9 or hit.cell == tuple(target)
