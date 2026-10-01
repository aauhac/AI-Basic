"""1인칭 조작 변환과 Billboard sprite.

조작 변환은 순수 함수라 pygame 없이 돌고, sprite 쪽은 창을 만들지 않고
off-screen Surface 로만 확인한다.
"""

import unittest

import fixtures
from game.engine import DIRECTIONS, Game
from renderer.raycaster import (
    FACING,
    Camera,
    cast_columns,
    project_sprite,
    relative_move,
    turn,
)


class TestRelativeInput(unittest.TestCase):
    """1인칭 입력 -> 절대 격자 방향. Game.move() 에는 절대 방향만 들어간다."""

    TABLE = {
        "w": {"w": "w", "s": "s", "a": "a", "d": "d"},   # 북을 볼 때
        "d": {"w": "d", "s": "a", "a": "w", "d": "s"},   # 동을 볼 때
        "s": {"w": "s", "s": "w", "a": "d", "d": "a"},   # 남을 볼 때
        "a": {"w": "a", "s": "d", "a": "s", "d": "w"},   # 서를 볼 때
    }

    def test_every_facing_and_key(self):
        for facing, expected in self.TABLE.items():
            for key, absolute in expected.items():
                with self.subTest(facing=facing, key=key):
                    self.assertEqual(relative_move(facing, key), absolute)

    def test_forward_is_always_the_facing_itself(self):
        for facing in "wasd":
            self.assertEqual(relative_move(facing, "w"), facing)

    def test_back_is_always_the_opposite(self):
        opposite = {"w": "s", "s": "w", "a": "d", "d": "a"}
        for facing in "wasd":
            self.assertEqual(relative_move(facing, "s"), opposite[facing])

    def test_turn_right_cycles_north_east_south_west(self):
        self.assertEqual([turn("w", 1), turn("d", 1), turn("s", 1), turn("a", 1)],
                         ["d", "s", "a", "w"])

    def test_turn_left_cycles_the_other_way(self):
        self.assertEqual([turn("w", -1), turn("a", -1), turn("s", -1), turn("d", -1)],
                         ["a", "s", "d", "w"])

    def test_four_right_turns_return_to_start(self):
        for facing in "wasd":
            spun = facing
            for _ in range(4):
                spun = turn(spun, 1)
            self.assertEqual(spun, facing)

    def test_turning_then_walking_forward_equals_strafing(self):
        for facing in "wasd":
            with self.subTest(facing=facing):
                self.assertEqual(relative_move(turn(facing, 1), "w"),
                                 relative_move(facing, "d"))

    def test_only_four_facings_exist(self):
        for facing in "wasd":
            for steps in range(-8, 9):
                self.assertIn(turn(facing, steps), DIRECTIONS)

    def test_engine_direction_table_is_untouched(self):
        self.assertEqual(DIRECTIONS,
                         {"w": (-1, 0), "a": (0, -1), "s": (1, 0), "d": (0, 1)})

    def test_engine_move_does_not_own_facing(self):
        """시선은 렌더러 입력 계층의 상태다. Game.move() 는 관여하지 않는다."""
        game = Game(fixtures.maze(fixtures.RAY_ROOM), map_name="ray.txt")
        row, col = game.player.position
        self.assertTrue(game.move(relative_move("d", "a")))   # 동쪽을 볼 때 왼쪽 = 북
        self.assertEqual(game.player.position, (row - 1, col))
        self.assertFalse(hasattr(game, "facing"))


@unittest.skipUnless(__import__("importlib").util.find_spec("pygame"),
                     "pygame 을 불러올 수 없는 환경")
class TestControlScheme(unittest.TestCase):
    """3D 는 이동(W/S)과 시점(A/D)을 분리한다."""

    def setUp(self):
        import pygame

        from renderer import game_view

        self.pygame = pygame
        self.view = game_view

    def test_only_forward_and_back_move(self):
        self.assertEqual(set(self.view.MOVE_KEYS.values()), {"w", "s"})

    def test_left_and_right_turn_in_place(self):
        keys = self.view.TURN_KEYS
        self.assertEqual(keys[self.pygame.K_a], -1)
        self.assertEqual(keys[self.pygame.K_d], 1)
        self.assertEqual(keys[self.pygame.K_LEFT], -1)
        self.assertEqual(keys[self.pygame.K_RIGHT], 1)

    def test_turn_and_move_keys_do_not_overlap(self):
        self.assertFalse(set(self.view.MOVE_KEYS) & set(self.view.TURN_KEYS))

    def test_forward_follows_the_facing_and_back_is_its_opposite(self):
        opposite = {"w": "s", "s": "w", "a": "d", "d": "a"}
        for facing in "wasd":
            with self.subTest(facing=facing):
                self.assertEqual(relative_move(facing, "w"), facing)
                self.assertEqual(relative_move(facing, "s"), opposite[facing])

    def test_turning_works_even_when_every_side_is_a_wall(self):
        """회전은 지형과 무관하다. 막다른 길에서도 항상 돈다."""
        maze = fixtures.maze(fixtures.TRAP_LINE)      # 1칸 복도, 위아래가 벽
        game = Game(maze, map_name="corridor.txt")
        facing = "d"
        self.assertFalse(game.move(relative_move(facing, "a")))   # 북은 벽
        for expected in ("w", "a", "s", "d"):                     # 그래도 계속 돈다
            facing = turn(facing, -1)
            self.assertEqual(facing, expected)

    def test_turning_never_touches_the_game(self):
        game = Game(fixtures.maze(fixtures.TRAP_LINE), map_name="corridor.txt")
        before = (game.player.position, game.player.move_count)
        facing = "d"
        for _ in range(8):
            facing = turn(facing, 1)
        self.assertEqual((game.player.position, game.player.move_count), before)

    def test_walking_a_path_costs_one_move_per_cell(self):
        """회전을 몇 번 하든 이동 횟수는 지나온 칸 수와 같다."""
        from ai.pathfinding import bfs, moves_for
        from maze.loader import load_maze

        maze = load_maze("maps/maze01.txt")
        game = Game(maze, map_name="maze01.txt")
        facing = "d"
        turns = 0
        for absolute in moves_for(bfs(maze).path):
            while relative_move(facing, "w") != absolute \
                    and relative_move(facing, "s") != absolute:
                facing = turn(facing, 1)          # 화면만 돌린다
                turns += 1
            game.move(absolute)
        self.assertTrue(game.cleared)
        self.assertGreater(turns, 0)
        traps = sum(1 for cell in game.visited_path if maze.tile(cell) == "T")
        self.assertEqual(game.player.move_count,
                         len(game.visited_path) - 1 + traps * 5)


class TestSpriteProjection(unittest.TestCase):
    def setUp(self):
        self.camera = Camera(5.5, 5.5, FACING["d"])    # 동쪽을 본다

    def test_sprite_straight_ahead_lands_in_the_middle(self):
        projection = project_sprite(self.camera, (5.5, 8.5), 320, 180)
        self.assertEqual(projection.screen_x, 160)
        self.assertAlmostEqual(projection.depth, 3.0)

    def test_sprite_behind_the_camera_is_dropped(self):
        self.assertIsNone(project_sprite(self.camera, (5.5, 2.5), 320, 180))
        self.assertIsNone(project_sprite(self.camera, (5.5, 5.5), 320, 180))

    def test_closer_sprite_is_bigger(self):
        near = project_sprite(self.camera, (5.5, 6.5), 320, 180)
        far = project_sprite(self.camera, (5.5, 9.5), 320, 180)
        self.assertGreater(near.size, far.size)
        self.assertLess(near.depth, far.depth)

    def test_left_and_right_land_on_the_matching_side(self):
        left = project_sprite(self.camera, (4.5, 8.5), 320, 180)
        right = project_sprite(self.camera, (6.5, 8.5), 320, 180)
        self.assertLess(left.screen_x, 160)
        self.assertGreater(right.screen_x, 160)

    def test_depth_shares_the_z_buffer_unit(self):
        hits = cast_columns(fixtures.maze(fixtures.RAY_ROOM), self.camera, 64)
        projection = project_sprite(self.camera, (5.5, 8.5), 64, 36)
        self.assertLess(projection.depth, hits[32].distance)

    def test_projection_does_not_touch_the_maze(self):
        maze = fixtures.maze(fixtures.RAY_ROOM)
        before = maze.as_text()
        project_sprite(self.camera, (5.5, 8.5), 320, 180)
        self.assertEqual(maze.as_text(), before)


try:
    import pygame

    from renderer import sprites
    from renderer.game_view import billboards_for, draw_billboard, wall_base_color
except ImportError:  # pygame 이 없는 환경
    HAS_PYGAME = False
else:
    HAS_PYGAME = True


@unittest.skipUnless(HAS_PYGAME, "pygame 을 불러올 수 없는 환경")
class TestSprites(unittest.TestCase):
    def test_every_sprite_has_transparent_background(self):
        for name in (sprites.KEY, sprites.TRAP, sprites.EXIT):
            with self.subTest(name=name):
                art = sprites.sprite(name)
                width, height = art.get_size()
                alphas = [art.get_at((x, y)).a
                          for x in range(width) for y in range(height)]
                self.assertIn(0, alphas, "투명 픽셀이 없으면 네모 박스다.")
                self.assertTrue(any(alpha == 255 for alpha in alphas))

    def test_key_sprite_has_a_hole_in_its_bow(self):
        art = sprites.sprite(sprites.KEY)
        self.assertEqual(art.get_at((5, 5)).a, 0)      # 고리 가운데가 뚫려 있다

    def test_trap_sprite_sits_low_and_wide(self):
        width, height = sprites.sprite(sprites.TRAP).get_size()
        self.assertGreater(width, height)              # 바닥에 붙는 납작한 모양

    def test_exit_sprite_is_a_tall_frame(self):
        width, height = sprites.sprite(sprites.EXIT).get_size()
        self.assertGreater(height, width)

    def test_sprites_are_cached(self):
        self.assertIs(sprites.sprite(sprites.KEY), sprites.sprite(sprites.KEY))

    def test_creature_sprite_is_transparent_with_bright_eyes(self):
        art = sprites.sprite(sprites.CREATURE)
        width, height = art.get_size()
        pixels = [art.get_at((x, y)) for x in range(width) for y in range(height)]
        self.assertIn(0, [pixel.a for pixel in pixels])
        self.assertTrue(any(pixel.a == 255 and sum(pixel[:3]) > 500 for pixel in pixels),
                        "밝은 눈 픽셀이 있어야 멀리서도 Creature 로 보인다.")

    def test_creature_silhouette_is_taller_than_wide(self):
        width, height = sprites.sprite(sprites.CREATURE).get_size()
        self.assertGreater(height, width)


@unittest.skipUnless(HAS_PYGAME, "pygame 을 불러올 수 없는 환경")
class TestBillboardOcclusion(unittest.TestCase):
    def setUp(self):
        self.surface = pygame.Surface((64, 36))
        self.art = sprites.sprite(sprites.KEY)

    def test_wall_in_front_hides_the_sprite(self):
        projection = project_sprite(Camera(5.5, 5.5, FACING["d"]), (5.5, 8.5), 64, 36)
        self.assertEqual(draw_billboard(self.surface, self.art, projection, [1.0] * 64), 0)

    def test_sprite_in_front_of_the_wall_is_drawn(self):
        projection = project_sprite(Camera(5.5, 5.5, FACING["d"]), (5.5, 8.5), 64, 36)
        self.assertGreater(draw_billboard(self.surface, self.art, projection, [99.0] * 64), 0)

    def test_closed_door_hides_it_and_opening_reveals_it(self):
        maze = fixtures.maze(fixtures.RAY_ROOM)
        camera = Camera(1.5, 4.5, FACING["s"])          # Door (3, 4) 를 정면으로 본다
        projection = project_sprite(camera, (5.5, 4.5), 64, 36)   # 문 뒤의 sprite
        closed = [hit.distance for hit in cast_columns(maze, camera, 64)]
        opened = [hit.distance
                  for hit in cast_columns(maze, camera, 64, opened_doors={(3, 4)})]
        self.assertEqual(draw_billboard(self.surface, self.art, projection, closed), 0)
        self.assertGreater(draw_billboard(self.surface, self.art, projection, opened), 0)


@unittest.skipUnless(HAS_PYGAME, "pygame 을 불러올 수 없는 환경")
class TestBillboardList(unittest.TestCase):
    def game(self):
        return Game(fixtures.maze(fixtures.VALID), map_name="valid.txt")

    def test_key_trap_and_exit_are_listed(self):
        self.assertEqual(len(billboards_for(self.game())), 3)

    def test_key_disappears_once_taken(self):
        game = self.game()
        for _ in range(3):
            game.move("d")                              # (1, 4) 의 Key 획득
        self.assertTrue(game.player.has_key)
        self.assertEqual(len(billboards_for(game)), 2)

    def test_positions_are_tile_centres(self):
        game = self.game()
        positions = {item[0] for item in billboards_for(game)}
        row, col = game.maze.exit
        self.assertIn((row + 0.5, col + 0.5), positions)

    def test_dormant_creature_is_not_drawn(self):
        import random

        from game.engine import HORROR
        from maze.loader import load_maze

        game = Game(load_maze("maps/maze01.txt"), map_name="maze01.txt",
                    play_mode=HORROR)
        game.attach_creature(random.Random(1))
        before = len(billboards_for(game))
        game.creature.activate()
        self.assertEqual(len(billboards_for(game)), before + 1)

    def test_active_creature_is_occluded_by_a_wall(self):
        maze = fixtures.maze(fixtures.RAY_ROOM)
        camera = Camera(1.5, 4.5, FACING["s"])
        art = sprites.sprite(sprites.CREATURE)
        projection = project_sprite(camera, (5.5, 4.5), 64, 36)
        surface = pygame.Surface((64, 36))
        closed = [hit.distance for hit in cast_columns(maze, camera, 64)]
        opened = [hit.distance
                  for hit in cast_columns(maze, camera, 64, opened_doors={(3, 4)})]
        self.assertEqual(draw_billboard(surface, art, projection, closed), 0)
        self.assertGreater(draw_billboard(surface, art, projection, opened), 0)

    def test_creature_behind_the_camera_is_not_projected(self):
        camera = Camera(5.5, 5.5, FACING["d"])
        self.assertIsNone(project_sprite(camera, (5.5, 2.5), 64, 36))

    def test_listing_does_not_change_the_game(self):
        game = self.game()
        before = (game.player.position, game.player.move_count, game.maze.as_text())
        billboards_for(game)
        self.assertEqual((game.player.position, game.player.move_count,
                          game.maze.as_text()), before)


@unittest.skipUnless(HAS_PYGAME, "pygame 을 불러올 수 없는 환경")
class TestCreatureVisibility(unittest.TestCase):
    """3~7칸 거리에서 Creature 가 실제로 화면에 나타나는지."""

    def setUp(self):
        from maze.loader import load_maze
        from renderer.game_view import render_frame

        self.maze = load_maze("maps/maze03.txt")     # row 15 가 긴 직선 복도
        self.render_frame = render_frame

    def scene(self, distance):
        from game.engine import HORROR, Game

        game = Game(self.maze, map_name="m", play_mode=HORROR)
        game.attach_creature()
        game.creature.activate()
        game.player.position = (15, 7)
        game.creature.position = (15, 7 + distance)
        camera = Camera(15.5, 7.5, FACING["d"])
        return game, camera

    def test_creature_is_drawn_at_three_five_and_seven_cells(self):
        for distance in (3, 5, 7):
            game, camera = self.scene(distance)
            projection = project_sprite(camera, (15.5, 7.5 + distance), 320, 180)
            with self.subTest(distance=distance):
                self.assertIsNotNone(projection)
                plain = pygame.Surface((320, 180))
                self.render_frame(plain, self.maze, camera, game.opened_doors)
                withc = pygame.Surface((320, 180))
                self.render_frame(withc, self.maze, camera, game.opened_doors, None,
                                  billboards_for(game))
                changed = sum(1 for x in range(320) for y in range(180)
                              if plain.get_at((x, y))[:3] != withc.get_at((x, y))[:3])
                self.assertGreater(changed, 0, "화면에 아무 변화가 없다")

    def test_outline_stands_out_against_the_wall(self):
        """몸통은 어둡게 두고 창백한 외곽선으로 식별한다. 그 외곽이 벽보다 밝아야 한다."""
        from renderer import sprites
        from renderer.game_view import WALL_COLOR, shade

        art = sprites.sprite(sprites.CREATURE)
        opaque = [art.get_at((x, y)) for x in range(art.get_width())
                  for y in range(art.get_height()) if art.get_at((x, y)).a > 0]
        brightest = max(sum(p[:3]) / 3 for p in opaque)
        for distance in (3, 5, 7):
            wall = shade(WALL_COLOR, distance, 0)
            with self.subTest(distance=distance):
                self.assertGreater(brightest, sum(wall) / 3 + 40)

    def test_eyes_only_light_up_when_the_creature_sees_the_player(self):
        from renderer import sprites

        lit = sprites.sprite(sprites.CREATURE)
        dark = sprites.sprite(sprites.CREATURE_UNSEEN)
        self.assertEqual(lit.get_size(), dark.get_size())
        count = lambda art: sum(1 for x in range(art.get_width())
                                for y in range(art.get_height())
                                if art.get_at((x, y))[:3] == sprites.EYE)
        self.assertGreater(count(lit), 0)
        self.assertEqual(count(dark), 0)

    def test_proximity_warning_works_without_line_of_sight(self):
        """사각지대 식별: 시야와 무관하게 보행 거리만으로 경고가 뜬다."""
        from renderer.game_view import WARN_DISTANCE, warning_level

        game, _camera = self.scene(3)
        game.creature.position = (15, 5)        # 플레이어 뒤쪽 = 화면 밖
        game.creature_sees_player = False
        game.refresh_creature_distance()
        self.assertEqual(game.creature_distance, 2)
        self.assertGreater(warning_level(game.creature_distance), 0)

    def test_warning_fades_with_distance_and_stops_at_the_limit(self):
        from renderer.game_view import WARN_DISTANCE, warning_level

        self.assertGreater(warning_level(1), warning_level(4))
        self.assertEqual(warning_level(WARN_DISTANCE), 0.0)
        self.assertEqual(warning_level(WARN_DISTANCE + 5), 0.0)
        self.assertEqual(warning_level(None), 0.0)

    def test_distance_is_walking_distance_not_straight_line(self):
        """얇은 벽 하나 너머라도 돌아가야 하면 멀다고 센다."""
        game, _camera = self.scene(3)
        game.creature.position = (13, 7)        # 직선으로는 2칸이지만 벽 너머
        game.refresh_creature_distance()
        self.assertGreater(game.creature_distance, 2)

    def test_dormant_creature_raises_no_warning(self):
        game, _camera = self.scene(3)
        game.creature.active = False
        game.refresh_creature_distance()
        self.assertIsNone(game.creature_distance)

    def test_billboard_picks_the_variant_from_the_last_observation(self):
        from renderer import sprites
        from renderer.game_view import billboards_for

        game, _camera = self.scene(3)
        game.creature_sees_player = True
        self.assertIn(sprites.sprite(sprites.CREATURE),
                      {item[1] for item in billboards_for(game)})
        game.creature_sees_player = False
        self.assertIn(sprites.sprite(sprites.CREATURE_UNSEEN),
                      {item[1] for item in billboards_for(game)})

    def test_sway_only_shifts_the_drawn_offset(self):
        from renderer.game_view import billboards_for

        from renderer import sprites

        creature_arts = {sprites.sprite(sprites.CREATURE),
                         sprites.sprite(sprites.CREATURE_UNSEEN)}
        game, _camera = self.scene(3)
        still = [i for i in billboards_for(game, creature_bias=0.0) if i[1] in creature_arts]
        swayed = [i for i in billboards_for(game, creature_bias=0.03) if i[1] in creature_arts]
        self.assertEqual(still[0][0], swayed[0][0])          # 월드 위치는 그대로
        self.assertNotEqual(still[0][2], swayed[0][2])       # 화면 오프셋만 바뀐다
        self.assertEqual(game.creature.position, (15, 10))   # 논리 위치 불변


@unittest.skipUnless(HAS_PYGAME, "pygame 을 불러올 수 없는 환경")
class TestCreatureInterpolation(unittest.TestCase):
    def test_render_position_lags_behind_the_logical_cell(self):
        from ai.creature import Creature
        from game.engine import HORROR, Game
        from maze.loader import load_maze
        from renderer.game_view import billboards_for

        game = Game(load_maze("maps/maze01.txt"), map_name="m", play_mode=HORROR)
        game.creature = Creature(position=(5, 5))
        game.creature.activate()
        render = (5.5, 5.5)
        game.creature.position = (5, 6)           # 논리 위치는 즉시 옮겨간다
        self.assertEqual(game.creature.position, (5, 6))

        weight = 0.2
        target = (6.0 - 0.5, 6.5)
        for _ in range(3):
            render = (render[0] + (5.5 - render[0]) * weight,
                      render[1] + (6.5 - render[1]) * weight)
        self.assertLess(render[1], 6.5)           # 아직 도착하지 않았고
        self.assertGreater(render[1], 5.5)        # 중간값을 지나는 중
        drawn = {item[0] for item in billboards_for(game, render)}
        self.assertIn(render, drawn)              # 화면은 보간 위치를 쓴다

    def test_billboard_falls_back_to_the_logical_cell(self):
        from ai.creature import Creature
        from game.engine import HORROR, Game
        from maze.loader import load_maze
        from renderer.game_view import billboards_for

        game = Game(load_maze("maps/maze01.txt"), map_name="m", play_mode=HORROR)
        game.creature = Creature(position=(5, 5))
        game.creature.activate()
        self.assertIn((5.5, 5.5), {item[0] for item in billboards_for(game)})


@unittest.skipUnless(HAS_PYGAME, "pygame 을 불러올 수 없는 환경")
class TestEndingIntegration(unittest.TestCase):
    """실제 GameView 순서(입력 -> 충돌 -> tick -> check_over)로 종료를 확인한다."""

    def run_to_exit(self, creature_on_exit):
        import os

        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        from ai.pathfinding import bfs, moves_for
        from game.engine import HORROR, Game
        from maze.loader import load_maze
        from renderer.game_view import GameView

        pygame.init()
        game = Game(load_maze("maps/maze01.txt"), map_name="maze01.txt",
                    play_mode=HORROR)
        game.attach_creature()
        game.creature.activate()
        game.creature.position = game.maze.exit if creature_on_exit else (3, 9)
        view = GameView(game, (320, 180), (160, 90))
        for key in moves_for(bfs(game.maze).path):
            game.move(key)                      # handle_events -> step 과 같은 경로
            if creature_on_exit:
                game.creature.position = game.maze.exit
            game.tick_creature(1 / 60)
            view.check_over()
        return game, view

    def test_creature_on_exit_ends_with_entity_contact(self):
        game, view = self.run_to_exit(True)
        self.assertTrue(game.caught)
        self.assertFalse(game.cleared)
        self.assertEqual(view.result.splitlines()[0], "ENTITY CONTACT")

    def test_clear_exit_ends_with_maze_cleared(self):
        game, view = self.run_to_exit(False)
        self.assertTrue(game.cleared)
        self.assertFalse(game.caught)
        self.assertEqual(view.result.splitlines()[0], "MAZE CLEARED")

    def test_each_ending_has_its_own_accent_colour(self):
        from renderer.game_view import RESULT_COLORS

        self.assertEqual(len(set(RESULT_COLORS.values())), 3)
        self.assertEqual(set(RESULT_COLORS),
                         {"MAZE CLEARED", "ENTITY CONTACT", "TIME OVER"})


@unittest.skipUnless(HAS_PYGAME, "pygame 을 불러올 수 없는 환경")
class TestDoorAppearance(unittest.TestCase):
    class FakeHit:
        def __init__(self, tile, wall_x):
            self.tile, self.wall_x = tile, wall_x

    def colour(self, tile, wall_x):
        return wall_base_color(self.FakeHit(tile, wall_x))

    def test_door_has_frame_seam_and_body(self):
        parts = {self.colour("D", 0.02), self.colour("D", 0.50), self.colour("D", 0.30)}
        self.assertEqual(len(parts), 3)

    def test_door_never_looks_like_a_plain_wall(self):
        wall = self.colour("#", 0.30)
        for wall_x in (0.02, 0.30, 0.50, 0.98):
            with self.subTest(wall_x=wall_x):
                self.assertNotEqual(self.colour("D", wall_x), wall)

    def test_plain_wall_ignores_wall_x(self):
        self.assertEqual(self.colour("#", 0.01), self.colour("#", 0.99))


if __name__ == "__main__":
    unittest.main()
