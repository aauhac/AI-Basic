import unittest

import fixtures
from ai.pathfinding import astar, bfs, dfs, distances, farthest, manhattan
from maze.loader import load_maze


class TestPathfinding(unittest.TestCase):
    def setUp(self):
        self.maze = fixtures.maze(fixtures.VALID)

    def assert_walkable_path(self, result):
        self.assertIsNotNone(result.path)
        self.assertEqual(result.path[0], self.maze.start)
        self.assertEqual(result.path[-1], self.maze.exit)
        for a, b in zip(result.path, result.path[1:]):
            self.assertEqual(manhattan(a, b), 1, f"{a} -> {b} 는 인접하지 않습니다.")
        self.assertGreater(result.visited, 0)

    def test_bfs_finds_path(self):
        self.assert_walkable_path(bfs(self.maze))

    def test_dfs_finds_path(self):
        self.assert_walkable_path(dfs(self.maze))

    def test_astar_finds_path(self):
        self.assert_walkable_path(astar(self.maze))

    def test_bfs_and_astar_agree_on_shortest_length(self):
        for name in ("maze01", "maze02", "maze03"):
            with self.subTest(name=name):
                maze = load_maze(f"maps/{name}.txt")
                self.assertEqual(len(bfs(maze).path), len(astar(maze).path))

    def test_dfs_is_never_shorter_than_bfs(self):
        self.assertGreaterEqual(len(dfs(self.maze).path), len(bfs(self.maze).path))

    def test_path_respects_key_and_door(self):
        path = bfs(self.maze).path
        self.assertLess(path.index(self.maze.keys[0]), path.index(self.maze.doors[0]))

    def test_unreachable_returns_none(self):
        maze = fixtures.maze(fixtures.UNREACHABLE_EXIT)
        for algorithm in (bfs, dfs, astar):
            with self.subTest(algorithm=algorithm.__name__):
                self.assertIsNone(algorithm(maze).path)

    def test_locked_door_blocks_without_key(self):
        maze = fixtures.maze(fixtures.KEY_BEHIND_DOOR)
        self.assertIsNone(bfs(maze).path)
        self.assertIsNotNone(bfs(maze, has_key=True).path)


class TestDistances(unittest.TestCase):
    """generator 가 쓰는 거리 맵. bfs 와 결과가 어긋나면 안 된다."""

    def test_distance_to_exit_matches_bfs(self):
        for name in ("maze01", "maze02", "maze03"):
            with self.subTest(name=name):
                maze = load_maze(f"maps/{name}.txt")
                self.assertEqual(distances(maze, maze.start)[maze.exit],
                                 len(bfs(maze).path) - 1)

    def test_key_bearing_state_is_not_lost_on_revisited_cells(self):
        """좌표만으로 방문 처리하면 Door 뒤가 도달 불가로 잘못 나왔던 회귀 테스트."""
        maze = fixtures.maze(fixtures.KEY_THEN_DOOR)
        found = distances(maze, maze.start)
        self.assertIn(maze.exit, found)
        self.assertEqual(found[maze.exit], len(bfs(maze).path) - 1)

    def test_locked_door_bounds_the_region_when_no_key_exists(self):
        maze = fixtures.maze(fixtures.KEY_BEHIND_DOOR)
        self.assertNotIn(maze.exit, distances(maze, maze.start))

    def test_unreachable_cells_are_absent(self):
        maze = fixtures.maze(fixtures.UNREACHABLE_EXIT)
        self.assertNotIn(maze.exit, distances(maze, maze.start))

    def test_farthest_cell_is_at_maximum_distance(self):
        maze = fixtures.maze(fixtures.VALID)
        found = distances(maze, maze.start)
        self.assertEqual(found[farthest(maze, maze.start)], max(found.values()))


if __name__ == "__main__":
    unittest.main()
