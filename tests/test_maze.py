import unittest

import fixtures
from ai.pathfinding import bfs, distances
from maze.generator import MIN_SPAWN_DISTANCE, generate
from maze.model import CREATURE, DOOR, KEY, TRAP, WALKABLE_TILES, WALL, Maze
from maze.loader import load_maze, parse_maze, save_maze
from maze.validator import is_valid, unreachable_cells, validate, walkable_positions


class TestLoader(unittest.TestCase):
    def test_parses_grid_and_tiles(self):
        m = fixtures.maze(fixtures.VALID)
        self.assertEqual((m.width, m.height), (10, 10))
        self.assertEqual(m.start, (1, 1))
        self.assertEqual(m.exit, (8, 1))
        self.assertEqual(m.keys, [(1, 4)])
        self.assertEqual(m.doors, [(5, 8)])
        self.assertEqual(m.traps, [(3, 4)])
        self.assertEqual(m.creature_spawns, [(7, 4)])

    def test_round_trip(self):
        m = fixtures.maze(fixtures.VALID)
        self.assertEqual(parse_maze(m.as_text()), m)

    def test_empty_file_rejected(self):
        with self.assertRaises(ValueError):
            parse_maze("\n\n  \n")

    def test_missing_file_rejected(self):
        with self.assertRaises(FileNotFoundError):
            load_maze("maps/does_not_exist.txt")

    def test_bundled_maps_are_valid(self):
        for name in ("maze01", "maze02", "maze03"):
            with self.subTest(name=name):
                self.assertEqual(validate(load_maze(f"maps/{name}.txt")), [])


class TestValidator(unittest.TestCase):
    def assert_fails(self, text, keyword):
        errors = validate(fixtures.maze(text))
        self.assertTrue(errors, "오류가 검출되지 않았습니다.")
        self.assertTrue(any(keyword in e for e in errors), errors)

    def test_valid_maze(self):
        self.assertTrue(is_valid(fixtures.maze(fixtures.VALID)))

    def test_too_small(self):
        self.assert_fails(fixtures.TOO_SMALL, "10x10")

    def test_ragged_rows(self):
        self.assert_fails(fixtures.RAGGED, "행의 길이")

    def test_illegal_character(self):
        self.assert_fails(fixtures.BAD_CHAR, "허용되지 않은 문자")

    def test_missing_start(self):
        self.assert_fails(fixtures.NO_START, "Start(S)가 존재하지 않습니다")

    def test_two_starts(self):
        self.assert_fails(fixtures.TWO_STARTS, "Start(S)가 2개")

    def test_missing_exit(self):
        self.assert_fails(fixtures.NO_EXIT, "Exit(E)가 존재하지 않습니다")

    def test_two_exits(self):
        self.assert_fails(fixtures.TWO_EXITS, "Exit(E)가 2개")

    def test_broken_outer_wall(self):
        self.assert_fails(fixtures.NO_OUTER_WALL, "외곽")

    def test_unreachable_exit(self):
        self.assert_fails(fixtures.UNREACHABLE_EXIT, "Exit에 도달할 수 없습니다")

    def test_key_behind_door(self):
        self.assert_fails(fixtures.KEY_BEHIND_DOOR, "Key에 도달할 수 없어")

    def test_key_then_door_is_solvable(self):
        self.assertTrue(is_valid(fixtures.maze(fixtures.KEY_THEN_DOOR)))

    def test_door_without_any_key(self):
        text = fixtures.KEY_THEN_DOOR.replace("K", ".")
        self.assert_fails(text, "Key(K)가 없어")


class TestConnectivity(unittest.TestCase):
    """Wall 이 아닌 모든 칸이 게임 규칙상 Start 에서 닿을 수 있어야 한다."""

    def orphans(self, text):
        return unreachable_cells(fixtures.maze(text))

    def test_fully_connected_maze_is_valid(self):
        self.assertEqual(self.orphans(fixtures.VALID), [])
        self.assertTrue(is_valid(fixtures.maze(fixtures.VALID)))

    def test_isolated_floor_region_is_invalid(self):
        errors = validate(fixtures.maze(fixtures.ISOLATED_FLOOR))
        self.assertTrue(any("접근할 수 없는" in error for error in errors), errors)
        self.assertEqual(len(self.orphans(fixtures.ISOLATED_FLOOR)), 8)

    def test_error_message_reports_count_and_sample(self):
        errors = validate(fixtures.maze(fixtures.ISOLATED_FLOOR))
        self.assertIn("8칸", errors[0])
        self.assertIn("(3, 1)", errors[1])

    def test_region_behind_a_door_is_connected_once_the_key_is_taken(self):
        self.assertEqual(validate(fixtures.maze(fixtures.DOOR_REGION)), [])

    def test_island_beyond_the_door_puzzle_is_still_invalid(self):
        errors = validate(fixtures.maze(fixtures.DOOR_REGION_PLUS_ISLAND))
        self.assertTrue(any("접근할 수 없는" in error for error in errors), errors)

    def test_each_isolated_special_tile_is_invalid(self):
        for tile in (".", "K", "T", "G"):
            with self.subTest(tile=tile):
                text = fixtures.isolated_tile(tile)
                self.assertEqual(self.orphans(text), [(3, 4)])
                self.assertFalse(is_valid(fixtures.maze(text)))

    def test_walkable_positions_counts_every_non_wall_tile(self):
        maze = fixtures.maze(fixtures.VALID)
        self.assertEqual(len(walkable_positions(maze)),
                         sum(len(line) - line.count("#") for line in maze.grid))

    def test_door_counts_as_walkable_space(self):
        maze = fixtures.maze(fixtures.DOOR_REGION)
        self.assertIn(maze.doors[0], walkable_positions(maze))

    def test_bundled_maps_are_fully_connected(self):
        for name in ("maze01", "maze02", "maze03"):
            with self.subTest(name=name):
                self.assertEqual(unreachable_cells(load_maze(f"maps/{name}.txt")), [])


class TestGenerator(unittest.TestCase):
    def test_generated_mazes_are_valid(self):
        for size in (11, 15, 21):
            for seed in range(5):
                with self.subTest(size=size, seed=seed):
                    self.assertEqual(validate(generate(size, size, seed=seed)), [])

    def test_even_size_is_rounded_up_to_odd(self):
        m = generate(16, 12, seed=1)
        self.assertEqual((m.width, m.height), (17, 13))

    def test_size_below_minimum_is_raised(self):
        m = generate(4, 4, seed=1)
        self.assertGreaterEqual(min(m.width, m.height), 11)

    def test_same_seed_gives_same_maze(self):
        self.assertEqual(generate(15, 15, seed=42), generate(15, 15, seed=42))

    def test_start_and_exit_are_far_apart(self):
        m = generate(21, 21, seed=3)
        self.assertGreater(len(bfs(m).path), 20)

    def test_saved_maze_reloads_identically(self):
        import tempfile

        m = generate(13, 13, seed=9)
        with tempfile.TemporaryDirectory() as tmp:
            path = save_maze(m, f"{tmp}/out.txt")
            self.assertEqual(load_maze(path), m)


def outer_wall_intact(maze) -> bool:
    return (set(maze.grid[0]) == {WALL} and set(maze.grid[-1]) == {WALL}
            and all(line[0] == WALL and line[-1] == WALL for line in maze.grid))


def open_cells(maze) -> int:
    return sum(line.count(".") for line in maze.grid)


class TestBraiding(unittest.TestCase):
    def test_zero_ratio_matches_plain_generate(self):
        self.assertEqual(generate(21, 15, seed=5), generate(21, 15, seed=5, loop_ratio=0.0))

    def test_zero_ratio_is_reproducible(self):
        self.assertEqual(generate(21, 15, seed=5, loop_ratio=0.0),
                         generate(21, 15, seed=5, loop_ratio=0.0))

    def test_same_seed_and_options_give_same_maze(self):
        for ratio in (0.05, 0.1, 0.25):
            with self.subTest(loop_ratio=ratio):
                self.assertEqual(generate(21, 15, seed=11, loop_ratio=ratio),
                                 generate(21, 15, seed=11, loop_ratio=ratio))

    def test_braided_maze_is_still_valid(self):
        for ratio in (0.05, 0.1, 0.2, 0.4):
            for seed in range(4):
                with self.subTest(loop_ratio=ratio, seed=seed):
                    self.assertEqual(validate(generate(21, 15, seed=seed,
                                                       loop_ratio=ratio)), [])

    def test_outer_wall_is_never_removed(self):
        for ratio in (0.1, 0.5, 1.0):
            for seed in range(4):
                with self.subTest(loop_ratio=ratio, seed=seed):
                    self.assertTrue(outer_wall_intact(
                        generate(21, 15, seed=seed, loop_ratio=ratio)))

    def test_loops_actually_open_more_cells(self):
        perfect = generate(21, 15, seed=8, loop_ratio=0.0)
        braided = generate(21, 15, seed=8, loop_ratio=0.2)
        self.assertGreater(open_cells(braided), open_cells(perfect))

    def test_no_two_by_two_open_room(self):
        """넓은 방이 생기지 않는지. (짝수, 짝수) 기둥이 남아 있어야 한다."""
        for ratio in (0.2, 0.5, 1.0):
            maze = generate(21, 15, seed=2, loop_ratio=ratio)
            for row in range(maze.height - 1):
                for col in range(maze.width - 1):
                    block = [maze.tile((r, c)) for r in (row, row + 1)
                             for c in (col, col + 1)]
                    with self.subTest(loop_ratio=ratio, at=(row, col)):
                        self.assertIn(WALL, block)


class TestSpecialTiles(unittest.TestCase):
    SEEDS = range(6)

    def mazes(self, loop_ratio=0.1):
        for seed in self.SEEDS:
            yield seed, generate(21, 15, seed=seed, loop_ratio=loop_ratio, specials=True)

    def test_all_special_tiles_are_placed(self):
        for seed, maze in self.mazes():
            with self.subTest(seed=seed):
                self.assertEqual(len(maze.keys), 1)
                self.assertEqual(len(maze.doors), 1)
                self.assertEqual(len(maze.traps), 1)
                self.assertEqual(len(maze.creature_spawns), 1)

    def test_every_non_wall_cell_is_reachable(self):
        for loop_ratio in (0.0, 0.05, 0.1):
            for seed in self.SEEDS:
                maze = generate(21, 15, seed=seed, loop_ratio=loop_ratio, specials=True)
                with self.subTest(loop_ratio=loop_ratio, seed=seed):
                    self.assertEqual(unreachable_cells(maze), [])

    def test_generated_maze_with_specials_is_valid(self):
        for seed, maze in self.mazes():
            with self.subTest(seed=seed):
                self.assertEqual(validate(maze), [])

    def test_door_and_key_are_actually_required(self):
        for seed, maze in self.mazes():
            with self.subTest(seed=seed):
                keyless = Maze(tuple(line.replace(KEY, ".") for line in maze.grid))
                self.assertIsNone(bfs(keyless).path,
                                  "Key 없이도 Exit 에 갈 수 있으면 장식 Door 다.")

    def test_door_is_on_the_solution_path(self):
        for seed, maze in self.mazes():
            with self.subTest(seed=seed):
                self.assertIn(maze.doors[0], bfs(maze).path)

    def test_key_is_reachable_without_passing_the_door(self):
        for seed, maze in self.mazes():
            with self.subTest(seed=seed):
                # K 를 지워서 열쇠 획득 없이 갈 수 있는 영역만 구한다.
                keyless = Maze(tuple(line.replace(KEY, ".") for line in maze.grid))
                before = distances(keyless, maze.start)
                self.assertIn(maze.keys[0], before)

    def test_special_tiles_never_overlap(self):
        for seed, maze in self.mazes():
            with self.subTest(seed=seed):
                spots = [maze.start, maze.exit, maze.keys[0], maze.doors[0],
                         maze.traps[0], maze.creature_spawns[0]]
                self.assertEqual(len(set(spots)), len(spots))

    def test_creature_spawn_is_walkable_and_away_from_start(self):
        for seed, maze in self.mazes():
            with self.subTest(seed=seed):
                spawn = maze.creature_spawns[0]
                self.assertEqual(maze.tile(spawn), CREATURE)
                self.assertIn(maze.tile(spawn), WALKABLE_TILES)
                self.assertGreaterEqual(distances(maze, maze.start)[spawn],
                                        MIN_SPAWN_DISTANCE)

    def test_trap_is_on_a_walkable_tile(self):
        for seed, maze in self.mazes():
            with self.subTest(seed=seed):
                self.assertEqual(maze.tile(maze.traps[0]), TRAP)
                self.assertIn(maze.traps[0], distances(maze, maze.start))

    def test_specials_are_reproducible(self):
        self.assertEqual(generate(21, 15, seed=4, loop_ratio=0.1, specials=True),
                         generate(21, 15, seed=4, loop_ratio=0.1, specials=True))

    def test_failure_reports_a_reason_instead_of_looping(self):
        with self.assertRaises(ValueError) as caught:
            generate(21, 15, seed=1, loop_ratio=0.6, specials=True)
        self.assertIn("Door", str(caught.exception))

    def test_door_tile_is_written_as_D(self):
        _, maze = next(iter(self.mazes()))
        self.assertEqual(maze.tile(maze.doors[0]), DOOR)


if __name__ == "__main__":
    unittest.main()
