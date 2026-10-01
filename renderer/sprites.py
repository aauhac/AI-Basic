"""코드로 그리는 투명 배경 pixel-art sprite.

외부 이미지 asset 없이 pygame draw primitive 만 쓴다. 저해상도로 만들어 두고
billboard 가 거리에 맞춰 확대하므로 확대하면 자연스럽게 각진 retro 질감이 된다.
"""

import random

import pygame

KEY = "key"
TRAP = "trap"
EXIT = "exit"
CREATURE = "creature"
CREATURE_UNSEEN = "creature_unseen"   # 플레이어를 못 보고 있을 때: 눈이 꺼진 빈 얼굴

CLEAR = (0, 0, 0, 0)

BRASS = (198, 160, 62)
BRASS_LIT = (248, 222, 132)
BRASS_DARK = (92, 70, 22)

SPIKE = (170, 176, 178)
SPIKE_LIT = (226, 230, 232)
RUST = (122, 40, 32)
GRATE = (46, 40, 38)

EXIT_FRAME = (86, 214, 108)
EXIT_LIT = (186, 255, 196)

# 어두운 실루엣은 유지하되 벽(거리 8에서 약 (32,34,31))과 구분되도록 올렸다.
# 뒤엉킨 붉은 형체. 몸은 거의 검게 두고 붉은 후광과 핏줄로 식별한다.
ROT = (96, 22, 24)
GORE = (158, 38, 34)
GORE_LIT = (226, 64, 48)
FLESH_DARK = (18, 12, 14)
EYE = (255, 96, 74)             # 붉은 눈
EYE_CORE = (255, 214, 196)
HALO = (255, 48, 40)

CREATURE_SIZE = (48, 60)        # 후광까지 포함한 박스
CREATURE_CENTER = (24, 28)

_cache: dict[str, pygame.Surface] = {}


def sprite(name: str) -> pygame.Surface:
    """이름으로 sprite 를 얻는다. 한 번 만들면 캐시한다."""
    if name not in _cache:
        _cache[name] = _BUILDERS[name]()
    return _cache[name]


def _surface(width: int, height: int) -> pygame.Surface:
    return pygame.Surface((width, height), pygame.SRCALPHA)


def _key() -> pygame.Surface:
    """고리 + 손잡이 + 아래쪽 이빨 두 개의 열쇠 실루엣."""
    surface = _surface(14, 20)
    pygame.draw.circle(surface, BRASS_DARK, (5, 5), 5)
    pygame.draw.circle(surface, BRASS, (5, 5), 4)
    pygame.draw.circle(surface, CLEAR, (5, 5), 2)          # 고리 구멍
    pygame.draw.rect(surface, BRASS_DARK, (3, 9, 4, 11))   # 자루 외곽
    pygame.draw.rect(surface, BRASS, (4, 9, 2, 10))
    pygame.draw.rect(surface, BRASS_DARK, (7, 13, 4, 3))   # 이빨 위
    pygame.draw.rect(surface, BRASS, (7, 13, 3, 2))
    pygame.draw.rect(surface, BRASS_DARK, (7, 17, 5, 3))   # 이빨 아래
    pygame.draw.rect(surface, BRASS, (7, 17, 4, 2))
    pygame.draw.rect(surface, BRASS_LIT, (4, 2, 2, 1))     # 하이라이트
    pygame.draw.rect(surface, BRASS_LIT, (4, 10, 1, 7))
    return surface


def _trap() -> pygame.Surface:
    """바닥 쇠살대에서 솟은 가시들. 바닥에 붙어 보이도록 세로로 납작하다."""
    surface = _surface(24, 11)
    pygame.draw.rect(surface, GRATE, (0, 8, 24, 3))        # 바닥 틀
    pygame.draw.rect(surface, RUST, (0, 8, 24, 1))
    for index in range(4):
        left = 1 + index * 6
        pygame.draw.polygon(surface, SPIKE,
                            [(left, 9), (left + 2, 1), (left + 4, 9)])
        pygame.draw.line(surface, SPIKE_LIT, (left + 2, 2), (left + 1, 8))
    return surface


def _exit() -> pygame.Surface:
    """빛나는 출구 문틀. 가운데는 비워서 지나갈 수 있는 통로로 보이게 한다."""
    surface = _surface(22, 30)
    pygame.draw.rect(surface, EXIT_FRAME, (1, 1, 20, 3))     # 상단 인방
    pygame.draw.rect(surface, EXIT_FRAME, (1, 1, 3, 28))     # 왼쪽 기둥
    pygame.draw.rect(surface, EXIT_FRAME, (18, 1, 3, 28))    # 오른쪽 기둥
    pygame.draw.rect(surface, EXIT_FRAME, (1, 26, 20, 3))    # 바닥 문턱
    pygame.draw.rect(surface, EXIT_LIT, (1, 1, 20, 1))
    pygame.draw.rect(surface, EXIT_LIT, (1, 1, 1, 28))
    for step in range(4):                                    # 개구부 안쪽 잔광
        pygame.draw.rect(surface, (*EXIT_FRAME, 70 - step * 18),
                         (4 + step, 4 + step, 14 - step * 2, 22 - step * 2), 1)
    return surface


def _halo(surface, radius=24, peak=235, steps=14) -> None:
    """바깥에서 안쪽으로 알파를 올리며 겹쳐 그린다 (pygame.draw 는 덮어쓰기)."""
    for index in range(steps):
        alpha = int(peak * (index / steps) ** 1.1)
        pygame.draw.circle(surface, (*HALO, alpha), CREATURE_CENTER,
                           int(radius * (1 - index / steps)))


def _creature_body(seen: bool) -> pygame.Surface:
    """붉은 후광에 감싸인, 픽셀이 뒤엉킨 검붉은 형체.

    몸을 거의 검게 두고 후광과 핏줄로 보여 주기 때문에 어두운 복도에서도 멀리서
    바로 눈에 띈다. rng 는 seed 를 고정해서 매번 같은 그림이 나온다.
    seen=False 면 눈이 꺼져 형체만 남는다.
    """
    surface = _surface(*CREATURE_SIZE)
    _halo(surface)
    rng = random.Random(23)
    ox, oy = CREATURE_CENTER[0] - 8, 10

    pygame.draw.ellipse(surface, FLESH_DARK, (ox + 3, oy, 10, 13))      # 머리
    for _ in range(26):                                                 # 엉킨 가닥
        x, y = rng.randint(2, 13), rng.randint(0, 12)
        if ((x - 8) / 5.5) ** 2 + ((y - 6) / 6.5) ** 2 < 1.15:
            surface.set_at((ox + x, oy + y),
                           rng.choice((ROT, GORE, FLESH_DARK, FLESH_DARK)))
    if seen:
        for (ex, ey), size in (((5, 5), 3), ((10, 6), 2)):              # 좌우 크기가 다른 눈
            pygame.draw.rect(surface, EYE, (ox + ex, oy + ey, size, size))
            pygame.draw.rect(surface, EYE_CORE, (ox + ex, oy + ey, 1, 1))

    pygame.draw.polygon(surface, FLESH_DARK, [(ox + 2, oy + 13), (ox + 14, oy + 13),
                                              (ox + 12, oy + 33), (ox + 4, oy + 33)])
    for _ in range(9):                                                  # 몸통을 타고 흐르는 핏줄
        x, y = rng.randint(3, 12), rng.randint(14, 30)
        for _ in range(rng.randint(3, 8)):
            if 0 <= ox + x < CREATURE_SIZE[0] and 0 <= oy + y < CREATURE_SIZE[1]:
                surface.set_at((ox + x, oy + y), rng.choice((GORE, GORE_LIT, ROT)))
            x += rng.choice((-1, 0, 0, 1))
            y += 1
    for _ in range(55):                                                 # 뜯겨 흩어진 조각
        x, y = ox + rng.randint(-4, 20), oy + rng.randint(-2, 38)
        if 0 <= x < CREATURE_SIZE[0] and 0 <= y < CREATURE_SIZE[1]:
            surface.set_at((x, y), rng.choice((ROT, GORE, FLESH_DARK, FLESH_DARK)))
    for left, top in ((0, 15), (15, 17)):                               # 늘어진 팔
        y = top
        for _ in range(rng.randint(12, 16)):
            surface.set_at((ox + left + rng.choice((0, 1)), oy + y),
                           rng.choice((FLESH_DARK, ROT)))
            y += 1
    return surface


_BUILDERS = {KEY: _key, TRAP: _trap, EXIT: _exit,
             CREATURE: lambda: _creature_body(True),
             CREATURE_UNSEEN: lambda: _creature_body(False)}
