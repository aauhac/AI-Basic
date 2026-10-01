"""Pygame 1인칭 3D 플레이 화면.

게임 규칙은 하나도 여기에 없다. 이동/Key/Door/Trap/Exit/시간은 전부 기존 Game 이
판정하고, 이 모듈은 그 결과를 화면에 비추고 입력을 Game.move() 로 넘기기만 한다.

조작은 1인칭에 맞게 camera-relative 이지만, 변환은 renderer.raycaster.relative_move()
한 곳에서만 일어나고 Game.move() 에는 언제나 절대 방향 'w'/'a'/'s'/'d' 가 들어간다.

낮은 내부 해상도로 렌더링하고 창 크기로 확대해서 retro horror 질감을 낸다.
"""

import math
import os

import pygame

from game import records, save_manager
from game.engine import DIRECTIONS, EVENT_TEXT, WARN_EVENTS
from maze.model import DOOR, WALL
from ai.route_guard import MAX_DYNAMIC_OPENS
from renderer import sprites
from renderer.raycaster import (
    FACING,
    Camera,
    cast_columns,
    column_span,
    project_sprite,
    relative_move,
    turn,
)

INTERNAL_SIZE = (320, 180)
WINDOW_SIZE = (960, 540)
VIEW_DISTANCE = 12.0            # 이 거리에서 벽이 거의 검게 보인다
SNAP_SPEED = 12.0               # 논리 cell / 방향으로 카메라가 따라붙는 속도
SWAY_SPEED = 2.2                # Creature 가 가만히 있어도 미세하게 흔들린다
SWAY_AMOUNT = 0.022
WARN_DISTANCE = 6               # 이 칸 수 안으로 들어오면 화면 가장자리가 붉어진다
WARN_BANDS = 96
WARN_RED = (210, 24, 20)
MESSAGE_SECONDS = 1.6

CEILING_TOP = (26, 30, 27)
CEILING_BOTTOM = (10, 12, 10)
FLOOR_FAR = (12, 14, 12)
FLOOR_NEAR = (34, 32, 26)

WALL_COLOR = (96, 104, 94)
DOOR_BODY = (140, 82, 40)
DOOR_FRAME = (86, 50, 24)
DOOR_SEAM = (54, 30, 14)
DOOR_HANDLE = (222, 190, 96)

HUD_FG = (140, 255, 140)
HUD_DIM = (70, 120, 70)
HUD_WARN = (255, 120, 96)
RESULT_COLORS = {"MAZE CLEARED": (140, 255, 140),      # 녹색
                 "ENTITY CONTACT": (255, 110, 96),     # 붉은색
                 "TIME OVER": (255, 196, 90)}          # 황색
HUD_BG = (8, 12, 8)
MAP_BG = (6, 10, 6)
MAP_FLOOR = (44, 82, 48)
MAP_DOOR = (140, 82, 40)
MAP_PLAYER = (242, 255, 92)

# 이동과 시점을 분리한다. W/S 는 앞뒤로만 움직이고 A/D 는 제자리에서 90도 돈다.
# 통로가 1칸 폭이라 옆으로 가는 입력은 대부분 벽에 막혀 아무 일도 일어나지 않았다.
# 회전으로 두면 벽 앞에서도 항상 반응하고, 키 하나가 언제나 한 가지 일만 한다.
MOVE_KEYS = {pygame.K_w: "w", pygame.K_s: "s"}
TURN_KEYS = {pygame.K_a: -1, pygame.K_LEFT: -1, pygame.K_d: 1, pygame.K_RIGHT: 1}

# (sprite 이름, 화면 세로 오프셋, 크기 배율). 오프셋이 클수록 화면 아래쪽에 놓인다.
SPRITE_STYLE = {
    sprites.KEY: (0.16, 0.50),
    sprites.TRAP: (0.38, 0.45),
    sprites.EXIT: (0.02, 0.92),
    # 후광이 포함된 큰 박스라, 몸이 예전과 같은 크기로 보이도록 배율을 올렸다.
    sprites.CREATURE: (0.02, 1.55),
    sprites.CREATURE_UNSEEN: (0.02, 1.55),
}


def shade(color, distance: float, side: int) -> tuple[int, int, int]:
    """멀수록 어둡게, 가로벽은 조금 더 어둡게 해서 공간감을 준다."""
    factor = max(0.10, 1.0 - distance / VIEW_DISTANCE)
    if side == 1:
        factor *= 0.68
    return (int(color[0] * factor), int(color[1] * factor), int(color[2] * factor))


def wall_base_color(hit) -> tuple[int, int, int]:
    """Door 는 wall_x 로 좌우 문틀과 가운데 이음새를 그려 벽과 구분한다."""
    if hit.tile != DOOR:
        return WALL_COLOR
    if hit.wall_x < 0.10 or hit.wall_x > 0.90:
        return DOOR_FRAME
    if abs(hit.wall_x - 0.5) < 0.035:
        return DOOR_SEAM
    return DOOR_BODY


def warning_vignette(size) -> pygame.Surface:
    """화면 가장자리에서 안쪽으로 옅어지는 붉은 테두리. 한 번 만들어 두고 재사용한다."""
    surface = pygame.Surface(size, pygame.SRCALPHA)
    width, height = size
    for band in range(WARN_BANDS):
        alpha = int(165 * (1 - band / WARN_BANDS) ** 1.7)
        pygame.draw.rect(surface, (*WARN_RED, alpha),
                         (band, band, width - band * 2, height - band * 2), 1)
    return surface


def warning_level(distance) -> float:
    """보행 거리 -> 경고 세기 0.0 ~ 1.0. 시야와 무관하므로 사각지대에서도 동작한다."""
    if distance is None or distance > WARN_DISTANCE:
        return 0.0
    return 1.0 - distance / WARN_DISTANCE


def background(size) -> pygame.Surface:
    """천장/바닥 그라디언트. 변하지 않으므로 한 번만 만들어 두고 매 프레임 blit 한다."""
    width, height = size
    surface = pygame.Surface(size)
    middle = height // 2
    for y in range(middle):
        blend = y / max(1, middle - 1)
        surface.fill(_mix(CEILING_TOP, CEILING_BOTTOM, blend), (0, y, width, 1))
    for y in range(middle, height):
        blend = (y - middle) / max(1, height - middle - 1)
        surface.fill(_mix(FLOOR_FAR, FLOOR_NEAR, blend), (0, y, width, 1))
    return surface


def _mix(start, end, blend):
    return tuple(int(a + (b - a) * blend) for a, b in zip(start, end))


def draw_billboard(surface, sprite: pygame.Surface, projection, z_buffer,
                   vertical_offset=0.0, scale=1.0) -> int:
    """벽보다 앞선 column 만 골라 sprite 를 세로줄 단위로 그린다.

    Key / Trap / Exit 가 공유하고, 다음 Phase 의 Creature 도 이 함수를 그대로 쓴다.
    그린 column 수를 돌려주므로 창 없이도 가림 여부를 확인할 수 있다.
    """
    art_width, art_height = sprite.get_size()
    height = max(1, int(projection.size * scale))
    width = max(1, round(height * art_width / art_height))
    scaled = pygame.transform.scale(sprite, (width, height))

    screen_width, screen_height = surface.get_size()
    top = (screen_height - height) // 2 + int(projection.size * vertical_offset)
    left = projection.screen_x - width // 2

    drawn = 0
    for x in range(max(0, left), min(screen_width, left + width)):
        if projection.depth >= z_buffer[x]:
            continue
        surface.blit(scaled, (x, top), (x - left, 0, 1, height))
        drawn += 1
    return drawn


def render_frame(surface: pygame.Surface, maze, camera: Camera, opened_doors=(),
                 sky: pygame.Surface | None = None, billboards=(),
                 opened_walls=()) -> list[float]:
    """한 프레임을 그리고 column 별 벽 거리(z-buffer)를 돌려준다.

    billboards 는 (world_pos, sprite surface, vertical_offset, scale) 목록이다.
    무엇을 넘길지는 호출자가 정하므로 렌더러는 게임 규칙을 알 필요가 없다.
    """
    width, height = surface.get_size()
    surface.blit(sky if sky is not None else background((width, height)), (0, 0))

    z_buffer = []
    for x, hit in enumerate(cast_columns(maze, camera, width, opened_doors,
                                         opened_walls=opened_walls)):
        z_buffer.append(hit.distance)
        if not hit.hit:
            continue
        top, span = column_span(hit.distance, height)
        visible_top = max(0, top)
        surface.fill(shade(wall_base_color(hit), hit.distance, hit.side),
                     (x, visible_top, 1, min(span, height - visible_top)))
        if hit.tile == DOOR and 0.70 <= hit.wall_x <= 0.79:   # 손잡이
            thickness = max(1, span // 14)
            surface.fill(shade(DOOR_HANDLE, hit.distance, hit.side),
                         (x, top + span // 2, 1, thickness))

    # 먼 것부터 그려야 가까운 sprite 가 위에 온다.
    projected = []
    for world_pos, art, offset, scale in billboards:
        projection = project_sprite(camera, world_pos, width, height)
        if projection is not None:
            projected.append((projection, art, offset, scale))
    for projection, art, offset, scale in sorted(projected, key=lambda item: -item[0].depth):
        draw_billboard(surface, art, projection, z_buffer, offset, scale)
    return z_buffer


def billboards_for(game, creature_position=None, creature_seen=None,
                   creature_bias=0.0) -> list[tuple]:
    """지금 화면에 나와야 할 sprite 목록. 규칙 판정이 아니라 표시 여부만 본다."""
    items = []
    if not game.player.has_key:            # 이미 주웠으면 원본 K 가 남아도 숨긴다
        items += [(pos, sprites.KEY) for pos in game.maze.keys]
    items += [(pos, sprites.TRAP) for pos in game.maze.traps]
    if game.maze.exit is not None:
        items.append((game.maze.exit, sprites.EXIT))
    drawn = [((row + 0.5, col + 0.5), sprites.sprite(name), *SPRITE_STYLE[name])
             for (row, col), name in items]
    creature = getattr(game, "creature", None)
    if creature is not None and creature.active:   # 깨어나기 전에는 보이지 않는다
        row, col = creature.position
        world = creature_position or (row + 0.5, col + 0.5)   # 렌더 전용 보간 위치
        if creature_seen is None:
            creature_seen = getattr(game, "creature_sees_player", False)
        # 나를 보고 있을 때만 눈이 켜진다. 평소에는 얼굴이 빈 공동이다.
        name = sprites.CREATURE if creature_seen else sprites.CREATURE_UNSEEN
        offset, scale = SPRITE_STYLE[name]
        drawn.append((world, sprites.sprite(name), offset + creature_bias, scale))
    return drawn


def result_text(game, entry=None) -> str:
    """게임 종료 화면 문구. 창 없이 테스트할 수 있게 순수 함수로 둔다."""
    tail = "ENTER / ESC  TO RETURN"
    stats = f"MOVES {game.player.move_count}    TIME {game.elapsed:.2f}"
    if game.cleared:
        best = ""
        if entry:
            best = (f"\nBEST MOVES {entry['best_moves']}    "
                    f"BEST TIME {entry['best_time']:.2f}")
        return f"MAZE CLEARED\n{stats}{best}\n{tail}"
    if game.caught:
        return f"ENTITY CONTACT\nYOU WERE CAUGHT\n{stats}\n{tail}"
    return f"TIME OVER\n제한 시간을 초과했습니다.\n{tail}"


def facing_at_start(game) -> str:
    """시작할 때 벽을 정면으로 보고 있지 않도록 열린 방향을 고른다."""
    row, col = game.player.position
    for key, (drow, dcol) in DIRECTIONS.items():
        if game.is_passable((row + drow, col + dcol)):
            return key
    return "d"


class GameView:
    def __init__(self, game, window_size=WINDOW_SIZE, internal_size=INTERNAL_SIZE):
        self.game = game
        self.screen = pygame.display.set_mode(window_size)
        pygame.display.set_caption(f"MAZE-13  //  {game.map_name}")
        self.frame = pygame.Surface(internal_size)
        self.sky = background(internal_size)
        self.font = pygame.font.SysFont("consolas", 15)
        # Consolas 에는 한글 글립이 없어 네모로 깨진다. 한글 줄만 다른 폰트로 그린다.
        # (숫자 정렬이 필요한 상태줄 / 디버그는 그대로 Consolas 를 쓴다.)
        self.kr_font = pygame.font.SysFont("gulim,malgungothic,dotum,consolas", 16)
        self.big_font = pygame.font.SysFont("consolas", 30, bold=True)
        self.clock = pygame.time.Clock()

        row, col = game.player.position
        self.facing = facing_at_start(game)        # 'w'/'a'/'s'/'d' 4방향만 가진다
        self.camera = Camera(row + 0.5, col + 0.5, FACING[self.facing])
        self.target = (row + 0.5, col + 0.5)
        self.message = ""
        self.message_warn = False
        self.message_until = 0.0
        self.show_map = False
        self.show_debug = False
        self.result = ""
        # Creature 는 논리적으로 칸 단위지만 화면에서는 부드럽게 따라온다.
        self.creature_render = self._creature_center()
        self.sway = 0.0
        self.vignette = warning_vignette(window_size)
        game.on_wall_opened = self._wall_opened
        self.z_buffer: list[float] = []

    def _creature_center(self):
        creature = getattr(self.game, "creature", None)
        if creature is None:
            return None
        return (creature.position[0] + 0.5, creature.position[1] + 0.5)

    def _wall_opened(self, walls) -> None:
        self.say("EMERGENCY ROUTE OPENED")

    # ---- 입력 -------------------------------------------------------------

    def step(self, key: str) -> None:
        """W/S 한 번 = 한 cell. 절대 방향으로 바꿔 Game.move() 에 넘긴다.

        시선은 여기서 바뀌지 않는다. 회전은 snap_turn() 이 전담한다.
        """
        game = self.game
        moved = game.move(relative_move(self.facing, key))
        if game.last_event:                  # 무슨 일이 있었는지는 Game 이 알려 준다
            self.say(EVENT_TEXT[game.last_event],
                     warn=game.last_event in WARN_EVENTS)
        if moved:
            self.target = (game.player.position[0] + 0.5,
                           game.player.position[1] + 0.5)

    def snap_turn(self, steps: int) -> None:
        """논리 방향은 즉시 90도 돌고 화면만 짧게 보간된다."""
        self.facing = turn(self.facing, steps)

    def handle_events(self) -> bool:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return False
            if event.type != pygame.KEYDOWN:
                continue
            if event.key == pygame.K_ESCAPE:
                return False
            if event.key == pygame.K_TAB:
                self.show_map = not self.show_map
                continue
            if event.key == pygame.K_F3:
                self.show_debug = not self.show_debug
                continue
            if self.game.over:
                if event.key in (pygame.K_RETURN, pygame.K_SPACE):
                    return False
                continue
            if event.key == pygame.K_F5:
                path = save_manager.save_game(self.game, save_manager.next_save_path())
                self.say(f"SAVED  {path.name}")
            elif event.key in TURN_KEYS:        # A / D / 좌우 화살표 - 제자리 90도
                self.snap_turn(TURN_KEYS[event.key])
            elif event.key in MOVE_KEYS:        # W / S - 앞뒤로 한 칸
                self.step(MOVE_KEYS[event.key])
        return True

    def follow(self, seconds: float) -> None:
        """논리 위치/방향으로 카메라를 부드럽게 끌어당긴다. 순간이동하면 방향 감각이 깨진다."""
        weight = min(1.0, seconds * SNAP_SPEED)
        self.camera.row += (self.target[0] - self.camera.row) * weight
        self.camera.col += (self.target[1] - self.camera.col) * weight
        delta = (FACING[self.facing] - self.camera.angle + math.pi) % (2 * math.pi) - math.pi
        self.camera.angle += delta * weight

        self.sway += seconds
        target = self._creature_center()      # AI / 충돌은 논리 칸만 쓴다
        if target is not None:
            if self.creature_render is None:
                self.creature_render = target
            else:
                row, col = self.creature_render
                self.creature_render = (row + (target[0] - row) * weight,
                                        col + (target[1] - col) * weight)

    # ---- 화면 -------------------------------------------------------------

    def say(self, text: str, warn=False) -> None:
        self.message = text
        self.message_warn = warn
        self.message_until = pygame.time.get_ticks() / 1000 + MESSAGE_SECONDS

    def draw(self) -> None:
        self.z_buffer = render_frame(self.frame, self.game.maze, self.camera,
                                     self.game.opened_doors, self.sky,
                                     billboards_for(
                                         self.game, self.creature_render, None,
                                         math.sin(self.sway * SWAY_SPEED) * SWAY_AMOUNT),
                                     self.game.opened_walls)
        pygame.transform.scale(self.frame, self.screen.get_size(), self.screen)
        self.draw_warning()
        self.draw_hud()
        if self.show_map:
            self.draw_map()
        if self.show_debug:
            self.draw_debug()
        if self.result:
            self.draw_result()
        pygame.display.flip()

    def draw_warning(self) -> None:
        """Creature 가 가까우면 가장자리가 붉게 맥동한다. 위치는 알려 주지 않는다."""
        level = warning_level(getattr(self.game, "creature_distance", None))
        if level <= 0:
            return
        pulse = 0.68 + 0.32 * math.sin(self.sway * 5.0)
        self.vignette.set_alpha(int(255 * level * pulse))
        self.screen.blit(self.vignette, (0, 0))

    def draw_hud(self) -> None:
        game = self.game
        remaining = game.remaining
        clock = (f"TIME {game.elapsed:6.2f}" if remaining is None
                 else f"LEFT {remaining:6.2f}/{game.time_limit:.0f}")
        status = (f"{game.map_name}   {clock}   MOVES {game.player.move_count:4d}   "
                  f"KEY {'1' if game.player.has_key else '0'}   MODE {game.mode}")
        width, height = self.screen.get_size()
        self.screen.fill(HUD_BG, (0, 0, width, 22))
        self.screen.blit(self.font.render(status, True, HUD_FG), (8, 3))

        hint = ("W/S FWD-BACK   A/D TURN   TAB MAP   "
                "F3 DEBUG   F5 SAVE   ESC MENU")
        self.screen.fill(HUD_BG, (0, height - 22, width, 22))
        self.screen.blit(self.font.render(hint, True, HUD_DIM), (8, height - 19))

        if self.message and pygame.time.get_ticks() / 1000 < self.message_until:
            color = HUD_WARN if self.message_warn else HUD_FG
            label = self.kr_font.render(self.message, True, color)
            self.screen.blit(label, ((width - label.get_width()) // 2, 34))

    def draw_map(self) -> None:
        """TAB 탐색 지도. 이미 지나온 칸만 보여 준다 (정답 지도가 아니다)."""
        visited = set(self.game.visited_path)
        rows = [row for row, _ in visited]
        cols = [col for _, col in visited]
        cell = 7
        pad = 6
        panel_width = (max(cols) - min(cols) + 1) * cell + pad * 2
        panel_height = (max(rows) - min(rows) + 1) * cell + pad * 2
        origin_x = self.screen.get_width() - panel_width - 10
        origin_y = 48   # HUD 바 아래

        panel = pygame.Surface((panel_width, panel_height), pygame.SRCALPHA)
        panel.fill((*MAP_BG, 215))
        for row, col in visited:
            x = pad + (col - min(cols)) * cell
            y = pad + (row - min(rows)) * cell
            opened = (row, col) in self.game.opened_doors
            panel.fill(MAP_DOOR if opened else MAP_FLOOR, (x, y, cell - 1, cell - 1))
        row, col = self.game.player.position
        panel.fill(MAP_PLAYER, (pad + (col - min(cols)) * cell + 1,
                                pad + (row - min(rows)) * cell + 1, cell - 3, cell - 3))
        self.screen.blit(panel, (origin_x, origin_y))
        self.screen.blit(self.font.render("VISITED", True, HUD_DIM),
                         (origin_x, origin_y - 17))

    def draw_debug(self) -> None:
        """F3. Creature 가 '시각 + 기억' 으로 움직인다는 걸 보여주기 위한 텍스트 표시."""
        creature = getattr(self.game, "creature", None)
        if creature is None:
            lines = ["CREATURE  none (맵에 G 없음)"]
        else:
            seeing = self.game.creature_sees_player
            lines = [
                f"STATE     {creature.state}",
                f"ACTIVE    {creature.active}",
                f"POSITION  {creature.position}   FACING {creature.facing}",
                f"VISION    {'VISIBLE (눈 켜짐)' if seeing else 'lost (눈 꺼짐)'}",
                f"LAST SEEN {creature.last_seen_position}"
                f"   memory {creature.memory_remaining:.1f}s",
                f"TARGET    {creature.target}   path {len(creature.path)}",
            ]
        game = self.game
        safe = "BLOCKED" if game.route_status == "no_candidate" else "OK"
        goal = game.current_goal
        lines += [
            f"SAFE ROUTE    {safe}   ({game.route_status})",
            f"OPENED WALLS  {len(game.opened_walls)} / {MAX_DYNAMIC_OPENS}",
            f"PROXIMITY     {game.creature_distance}  "
            f"warn {warning_level(game.creature_distance):.2f}",
            f"CURRENT GOAL  {goal}"
            f"{'  (DOOR)' if goal in game.maze.doors else '  (EXIT)'}",
        ]
        panel = pygame.Surface((430, 18 * len(lines) + 12), pygame.SRCALPHA)
        panel.fill((*MAP_BG, 215))
        for index, line in enumerate(lines):
            panel.blit(self.font.render(line, True, HUD_FG), (8, 6 + index * 18))
        self.screen.blit(panel, (10, 48))

    def draw_result(self) -> None:
        lines = self.result.splitlines()
        width, height = self.screen.get_size()
        panel_height = 46 + 26 * len(lines)
        panel = pygame.Surface((width, panel_height))
        panel.set_alpha(225)
        panel.fill(HUD_BG)
        self.screen.blit(panel, (0, (height - panel_height) // 2))
        top = (height - panel_height) // 2 + 14
        accent = RESULT_COLORS.get(lines[0], HUD_FG)
        self.screen.fill(accent, (0, (height - panel_height) // 2, width, 2))
        self.screen.fill(accent, (0, (height + panel_height) // 2 - 2, width, 2))
        title = self.big_font.render(lines[0], True, accent)
        self.screen.blit(title, ((width - title.get_width()) // 2, top))
        for index, line in enumerate(lines[1:], start=1):
            label = self.kr_font.render(line, True, HUD_DIM)
            self.screen.blit(label, ((width - label.get_width()) // 2, top + 18 + 26 * index))

    # ---- 루프 -------------------------------------------------------------

    def check_over(self) -> None:
        if self.result or not self.game.over:
            return
        game = self.game
        entry = None
        if game.cleared:
            entry = records.update(game.map_name, game.player.move_count,
                                   game.elapsed, mode=game.play_mode)
        self.result = result_text(game, entry)

    def run(self, max_frames: int | None = None) -> None:
        running = True
        frames = 0
        while running:
            seconds = self.clock.tick(60) / 1000
            running = self.handle_events()
            self.follow(seconds)
            self.game.tick_creature(seconds)   # 관측/AI/잡힘 판정은 Game 이 한다
            self.check_over()
            self.draw()
            frames += 1
            if max_frames is not None and frames >= max_frames:
                break


def run(game, window_size=WINDOW_SIZE, internal_size=INTERNAL_SIZE,
        max_frames: int | None = None, headless=False) -> None:
    """3D 플레이를 실행하고 끝나면 pygame 을 정리한다 (Tkinter 로 복귀)."""
    if headless:
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    pygame.init()
    try:
        GameView(game, window_size, internal_size).run(max_frames)
    finally:
        pygame.quit()
