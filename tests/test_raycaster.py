"""DDA Raycasting. pygame 창 없이 계산만 검증한다.

거리 기대값은 RAY_ROOM 격자에서 직접 계산한 값이다 (fixtures.RAY_ROOM 참고).
"""

import math
import unittest

import fixtures
from ai.pathfinding import bfs
from game.engine import DIRECTIONS, Game
from renderer.raycaster import (
    FACING,
    Camera,
    blocks_ray,
    camera_offsets,
    cast,
    cast_columns,
    column_span,
    ray_direction,
)

MOVE_FOR_STEP = {step: key for key, step in DIRECTIONS.items()}


def path_keys(path):
    """좌표 경로를 W/A/S/D 입력으로 바꾼다."""
    return [MOVE_FOR_STEP[(b[0] - a[0], b[1] - a[1])] for a, b in zip(path, path[1:])]


class TestBlocksRay(unittest.TestCase):
    def setUp(self):
        self.maze = fixtures.maze(fixtures.RAY_ROOM)

    def test_wall_blocks(self):
        self.assertTrue(blocks_ray(self.maze, (0, 0)))

    def test_floor_does_not_block(self):
        self.assertFalse(blocks_ray(self.maze, (1, 1)))

    def test_outside_the_map_counts_as_wall(self):
        self.assertTrue(blocks_ray(self.maze, (-1, 4)))
        self.assertTrue(blocks_ray(self.maze, (99, 99)))

    def test_closed_door_blocks_but_opened_door_does_not(self):
        self.assertTrue(blocks_ray(self.maze, (3, 4)))
        self.assertFalse(blocks_ray(self.maze, (3, 4), opened_doors={(3, 4)}))


class TestCast(unittest.TestCase):
    def setUp(self):
        self.maze = fixtures.maze(fixtures.RAY_ROOM)

    def cast_from(self, origin, key, **kwargs):
        camera = Camera(origin[0], origin[1], FACING[key])
        return cast(self.maze, origin, camera.direction, **kwargs)

    def test_hits_the_wall_straight_ahead(self):
        hit = self.cast_from((8.5, 1.5), "w")
        self.assertTrue(hit.hit)
        self.assertEqual(hit.tile, "#")
        self.assertEqual(hit.cell, (0, 1))
        self.assertAlmostEqual(hit.distance, 7.5)
        self.assertEqual(hit.side, 1)  # 행 경계를 넘어 만난 가로벽

    def test_distance_is_always_positive(self):
        for key in "wasd":
            with self.subTest(key=key):
                self.assertGreater(self.cast_from((8.5, 1.5), key).distance, 0)

    def test_four_directions_are_consistent(self):
        expected = {"w": ((0, 1), 7.5), "s": ((9, 1), 0.5),
                    "a": ((8, 0), 0.5), "d": ((8, 9), 7.5)}
        for key, (cell, distance) in expected.items():
            with self.subTest(key=key):
                hit = self.cast_from((8.5, 1.5), key)
                self.assertEqual(hit.cell, cell)
                self.assertAlmostEqual(hit.distance, distance)

    def test_closed_door_stops_the_ray(self):
        hit = self.cast_from((1.5, 4.5), "s")
        self.assertEqual(hit.cell, (3, 4))
        self.assertEqual(hit.tile, "D")
        self.assertAlmostEqual(hit.distance, 1.5)

    def test_opened_door_lets_the_ray_through(self):
        hit = self.cast_from((1.5, 4.5), "s", opened_doors={(3, 4)})
        self.assertEqual(hit.cell, (9, 4))
        self.assertEqual(hit.tile, "#")
        self.assertAlmostEqual(hit.distance, 7.5)

    def test_ray_never_runs_forever(self):
        """외곽이 벽이므로 항상 멈추고, max_distance 로도 반드시 끊긴다."""
        for angle in range(0, 360, 7):
            with self.subTest(angle=angle):
                camera = Camera(4.5, 4.5, math.radians(angle))
                hit = cast(self.maze, (4.5, 4.5), camera.direction)
                self.assertTrue(hit.hit)
                self.assertLessEqual(hit.distance, 9.0)

    def test_max_distance_cuts_the_ray_off(self):
        hit = self.cast_from((8.5, 1.5), "w", max_distance=2.0)
        self.assertFalse(hit.hit)
        self.assertEqual(hit.distance, 2.0)

    def test_wall_x_stays_in_range(self):
        for angle in range(0, 360, 11):
            camera = Camera(4.5, 4.5, math.radians(angle))
            hit = cast(self.maze, (4.5, 4.5), camera.direction)
            with self.subTest(angle=angle):
                self.assertGreaterEqual(hit.wall_x, 0.0)
                self.assertLess(hit.wall_x, 1.0)

    def test_original_maze_is_never_modified(self):
        before = self.maze.as_text()
        cast_columns(self.maze, Camera(4.5, 4.5, 0.0), 64)
        self.assertEqual(self.maze.as_text(), before)


class TestCamera(unittest.TestCase):
    def test_cell_is_the_logical_cell(self):
        self.assertEqual(Camera(8.5, 1.9, 0.0).cell, (8, 1))

    def test_facing_angles_point_at_the_right_neighbour(self):
        expected = {"w": (-1, 0), "a": (0, -1), "s": (1, 0), "d": (0, 1)}
        for key, (drow, dcol) in expected.items():
            with self.subTest(key=key):
                row, col = Camera(0.0, 0.0, FACING[key]).direction
                self.assertAlmostEqual(row, drow)
                self.assertAlmostEqual(col, dcol)

    def test_facing_matches_the_engine_move_table(self):
        for key, step in DIRECTIONS.items():
            with self.subTest(key=key):
                row, col = Camera(0.0, 0.0, FACING[key]).direction
                self.assertEqual((round(row), round(col)), step)

    def test_screen_left_edge_is_left_of_the_facing_direction(self):
        """동쪽을 볼 때 화면 왼쪽 ray 는 북(row 감소)을 향해야 한다."""
        camera = Camera(4.5, 4.5, FACING["d"])
        self.assertLess(ray_direction(camera, -1.0)[0], 0)
        self.assertGreater(ray_direction(camera, 1.0)[0], 0)

    def test_camera_offsets_span_minus_one_to_one(self):
        offsets = camera_offsets(320)
        self.assertEqual(len(offsets), 320)
        self.assertAlmostEqual(offsets[0], -1.0)
        self.assertLess(offsets[-1], 1.0)
        self.assertAlmostEqual(offsets[160], 0.0)


class TestColumns(unittest.TestCase):
    def setUp(self):
        self.maze = fixtures.maze(fixtures.RAY_ROOM)

    def test_one_hit_per_screen_column(self):
        hits = cast_columns(self.maze, Camera(4.5, 4.5, FACING["d"]), 320)
        self.assertEqual(len(hits), 320)
        self.assertTrue(all(hit.hit for hit in hits))

    def test_no_fisheye_on_a_flat_wall(self):
        """평평한 벽을 정면으로 보면 수직거리가 column 전체에서 같아야 한다."""
        hits = cast_columns(self.maze, Camera(8.5, 4.5, FACING["s"]), 64)
        distances = [hit.distance for hit in hits]
        self.assertAlmostEqual(min(distances), max(distances), places=9)

    def test_centre_column_matches_a_direct_cast(self):
        camera = Camera(8.5, 1.5, FACING["w"])
        hits = cast_columns(self.maze, camera, 64)
        direct = cast(self.maze, (camera.row, camera.col), camera.direction)
        self.assertAlmostEqual(hits[32].distance, direct.distance, places=6)

    def test_opened_door_changes_the_column_distances(self):
        camera = Camera(1.5, 4.5, FACING["s"])
        closed = cast_columns(self.maze, camera, 64)
        opened = cast_columns(self.maze, camera, 64, opened_doors={(3, 4)})
        self.assertGreater(opened[32].distance, closed[32].distance)


class TestColumnSpan(unittest.TestCase):
    def test_closer_walls_are_taller(self):
        heights = [column_span(distance, 180)[1] for distance in (1, 2, 4, 8)]
        self.assertEqual(heights, sorted(heights, reverse=True))

    def test_span_is_centred(self):
        top, height = column_span(4.0, 180)
        self.assertEqual(top, (180 - height) // 2)

    def test_very_close_wall_is_clamped(self):
        _, height = column_span(1e-9, 180)
        self.assertEqual(height, 180 * 4)


class TestCameraFollowsGame(unittest.TestCase):
    """renderer camera 의 논리 cell 은 항상 Game 의 player 위치와 같아야 한다."""

    def test_camera_cell_tracks_every_move(self):
        maze = fixtures.maze(fixtures.VALID)
        game = Game(maze, map_name="valid.txt")
        camera = Camera(*[value + 0.5 for value in game.player.position])
        for key in path_keys(bfs(maze).path):
            game.move(key)
            camera.row, camera.col = (game.player.position[0] + 0.5,
                                      game.player.position[1] + 0.5)
            self.assertEqual(camera.cell, game.player.position)
        self.assertTrue(game.cleared)

    def test_renderer_does_not_change_game_state(self):
        maze = fixtures.maze(fixtures.VALID)
        game = Game(maze, map_name="valid.txt")
        before = (game.player.position, game.player.move_count, game.maze.as_text())
        cast_columns(game.maze, Camera(1.5, 1.5, 0.0), 128, game.opened_doors)
        self.assertEqual((game.player.position, game.player.move_count,
                          game.maze.as_text()), before)


try:
    import pygame
    from renderer.game_view import facing_at_start, render_frame, shade
except ImportError:  # pygame 이 없는 환경
    HAS_PYGAME = False
else:
    HAS_PYGAME = True


@unittest.skipUnless(HAS_PYGAME, "pygame 을 불러올 수 없는 환경")
class TestFrameRendering(unittest.TestCase):
    """창을 만들지 않고 off-screen Surface 로만 확인한다."""

    def setUp(self):
        self.maze = fixtures.maze(fixtures.RAY_ROOM)
        self.surface = pygame.Surface((64, 36))

    def test_z_buffer_has_one_entry_per_column(self):
        z_buffer = render_frame(self.surface, self.maze, Camera(4.5, 4.5, FACING["d"]))
        self.assertEqual(len(z_buffer), 64)
        self.assertTrue(all(distance > 0 for distance in z_buffer))

    def test_opened_door_changes_the_picture(self):
        camera = Camera(1.5, 4.5, FACING["s"])
        render_frame(self.surface, self.maze, camera)
        closed = pygame.image.tostring(self.surface, "RGB")
        render_frame(self.surface, self.maze, camera, opened_doors={(3, 4)})
        self.assertNotEqual(pygame.image.tostring(self.surface, "RGB"), closed)

    def test_shading_gets_darker_with_distance(self):
        near = shade((200, 200, 200), 1.0, 0)
        far = shade((200, 200, 200), 9.0, 0)
        self.assertGreater(sum(near), sum(far))

    def test_shading_never_goes_black_or_negative(self):
        for distance in (0.0, 5.0, 50.0, 1000.0):
            with self.subTest(distance=distance):
                for channel in shade((200, 200, 200), distance, 1):
                    self.assertGreaterEqual(channel, 0)
                    self.assertLessEqual(channel, 200)

    def test_horizontal_walls_are_dimmer(self):
        self.assertLess(sum(shade((200, 200, 200), 2.0, 1)),
                        sum(shade((200, 200, 200), 2.0, 0)))

    def test_start_facing_is_an_open_direction(self):
        game = Game(fixtures.maze(fixtures.VALID), map_name="valid.txt")
        key = facing_at_start(game)
        self.assertIn(key, DIRECTIONS)
        row, col = game.player.position
        drow, dcol = DIRECTIONS[key]
        self.assertTrue(game.is_passable((row + drow, col + dcol)))


if __name__ == "__main__":
    unittest.main()
