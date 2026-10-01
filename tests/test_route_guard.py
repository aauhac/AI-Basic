"""Adaptive Escape Route - 생성 단계 Trap 보정과 runtime 벽 개방."""

import random
import unittest

import fixtures
from ai import route_guard
from ai.pathfinding import bfs, grid_astar
from ai.perception import has_line_of_sight
from game.engine import HORROR, Game
from maze.loader import load_maze, parse_maze
from maze.model import Maze, blocks

# 아래 통로가 유일한 길이고 그 한가운데에 Trap 이 있다. 위쪽에 우회 통로가 될
# 벽 한 줄이 있어서 한 칸만 뚫으면 Trap 을 피할 수 있다.
TRAP_CHOKE = """\
############
#S.........#
##########.#
#..........#
#.########.#
#.#......#.#
#.#.T.....#E
############
"""

# 우회로가 이미 있어서 Trap 을 피할 수 있는 미로.
TRAP_FREE = """\
############
#S...T.....#
#.########.#
#..........#
##########.#
#.........E#
#..........#
############
"""


def maze_of(text):
    return parse_maze(text)


class TestSafeRouteBasics(unittest.TestCase):
    def setUp(self):
        self.maze = load_maze("maps/maze01.txt")

    def test_trap_is_walkable_in_game_but_blocked_in_the_search(self):
        """게임에서는 밟고 지나갈 수 있고, Safe Route 에서만 벽처럼 본다."""
        game = Game(self.maze, map_name="m")
        trap = self.maze.traps[0]
        self.assertTrue(game.is_passable(trap))
        self.assertIn(trap, route_guard.danger_cells(self.maze))
        self.assertIsNone(route_guard.safe_path(self.maze, self.maze.start, trap,
                                                blocked={trap}))

    def test_danger_cells_include_traps_and_an_active_creature(self):
        game = Game(self.maze, map_name="m", play_mode=HORROR)
        game.attach_creature(random.Random(1))
        self.assertEqual(route_guard.danger_cells(self.maze, game.creature),
                         set(self.maze.traps))               # DORMANT 는 제외
        game.creature.activate()
        self.assertIn(game.creature.position,
                      route_guard.danger_cells(self.maze, game.creature))

    def test_start_cell_is_never_treated_as_blocked(self):
        start = self.maze.traps[0]
        path = route_guard.safe_path(self.maze, start, self.maze.keys[0],
                                     blocked={start})
        self.assertIsNotNone(path)

    def test_candidate_walls_are_interior_and_between_two_passages(self):
        for wall in route_guard.candidate_walls(self.maze):
            with self.subTest(wall=wall):
                self.assertEqual(self.maze.tile(wall), "#")
                self.assertNotIn(wall[0], (0, self.maze.height - 1))
                self.assertNotIn(wall[1], (0, self.maze.width - 1))

    def test_outer_walls_are_never_candidates(self):
        border = {(r, c) for r in range(self.maze.height)
                  for c in range(self.maze.width)
                  if r in (0, self.maze.height - 1) or c in (0, self.maze.width - 1)}
        self.assertFalse(set(route_guard.candidate_walls(self.maze)) & border)


class TestCurrentGoal(unittest.TestCase):
    def setUp(self):
        self.maze = load_maze("maps/maze01.txt")

    def test_goal_is_the_closed_door(self):
        self.assertEqual(route_guard.current_goal(self.maze), self.maze.doors[0])

    def test_goal_becomes_the_exit_once_the_door_is_open(self):
        self.assertEqual(route_guard.current_goal(self.maze, set(self.maze.doors)),
                         self.maze.exit)

    def test_map_without_a_door_aims_at_the_exit(self):
        maze = fixtures.maze(fixtures.VALID.replace("D", "."))
        self.assertEqual(route_guard.current_goal(maze), maze.exit)

    def test_game_exposes_the_same_goal(self):
        game = Game(self.maze, map_name="m")
        self.assertEqual(game.current_goal, self.maze.doors[0])
        game.opened_doors.add(self.maze.doors[0])
        self.assertEqual(game.current_goal, self.maze.exit)


class TestTrapSafeGeneration(unittest.TestCase):
    def test_already_safe_maze_needs_no_repair(self):
        self.assertEqual(route_guard.trap_safe_walls(maze_of(TRAP_FREE)), [])

    def test_trap_on_the_only_corridor_is_repaired(self):
        maze = maze_of(TRAP_CHOKE)
        self.assertIsNone(bfs(maze, extra_blocked=set(maze.traps)).path)
        walls = route_guard.trap_safe_walls(maze)
        self.assertTrue(walls)
        self.assertLessEqual(len(walls), route_guard.MAX_TRAP_REPAIR_OPENS)
        self.assertIsNotNone(bfs(maze, opened_walls=set(walls),
                                 extra_blocked=set(maze.traps)).path)

    def test_repair_never_opens_an_outer_wall(self):
        maze = maze_of(TRAP_CHOKE)
        for wall in route_guard.trap_safe_walls(maze) or []:
            self.assertNotIn(wall[0], (0, maze.height - 1))
            self.assertNotIn(wall[1], (0, maze.width - 1))

    def test_every_trap_is_blocked_at_once(self):
        """T1 을 피하면 T2 를 밟는 구조도 실패로 잡아야 한다."""
        maze = load_maze("maps/maze03.txt")
        blocked = set(maze.traps)
        self.assertEqual(len(blocked), len(maze.traps))
        path = bfs(maze, extra_blocked=blocked).path
        if path is not None:
            self.assertFalse(set(path) & blocked)

    def test_generated_mazes_have_a_trap_free_route(self):
        from maze.generator import generate

        for seed in range(6):
            with self.subTest(seed=seed):
                maze = generate(21, 15, seed=seed, loop_ratio=0.05, specials=True)
                self.assertIsNotNone(bfs(maze, extra_blocked=set(maze.traps)).path)


class TestRuntimeRouteGuard(unittest.TestCase):
    def game(self, seed=1):
        game = Game(load_maze("maps/maze01.txt"), map_name="maze01.txt",
                    play_mode=HORROR)
        game.attach_creature(random.Random(seed))
        game.creature.activate()
        return game

    def test_nothing_happens_when_the_route_is_already_safe(self):
        game = self.game()
        game.creature.position = (3, 9)
        guard = route_guard.ensure_safe_route(
            game.maze, game.player.position, game.player.has_key,
            game.opened_doors, game.opened_walls, game.creature)
        self.assertEqual(guard.status, route_guard.ALREADY_SAFE)
        self.assertEqual(game.opened_walls, set())

    def test_a_creature_blocking_the_only_corridor_opens_a_wall(self):
        game = self.game()
        game.player.position = (1, 1)
        goal = game.current_goal
        # 좁은 목을 차례로 막아 보며 실제로 길이 끊기는 지점을 찾는다.
        blocked_case = None
        for cell in bfs(game.maze, goal=goal).path[1:]:
            if route_guard.safe_path(game.maze, game.player.position, goal,
                                     blocked=set(game.maze.traps) | {cell}) is None:
                blocked_case = cell
                break
        self.assertIsNotNone(blocked_case, "차단 지점을 찾지 못했다")
        game.creature.position = blocked_case
        guard = route_guard.ensure_safe_route(
            game.maze, game.player.position, game.player.has_key,
            game.opened_doors, game.opened_walls, game.creature)
        self.assertIn(guard.status, (route_guard.OPENED_WALL, route_guard.NO_CANDIDATE))
        if guard.status == route_guard.OPENED_WALL:
            self.assertTrue(game.opened_walls)
            self.assertIsNotNone(route_guard.safe_path(
                game.maze, game.player.position, goal,
                opened_walls=game.opened_walls,
                blocked=route_guard.danger_cells(game.maze, game.creature)))

    def test_open_count_never_exceeds_the_limit(self):
        game = self.game()
        for cell in bfs(game.maze).path:
            game.creature.position = cell
            route_guard.ensure_safe_route(
                game.maze, game.player.position, game.player.has_key,
                game.opened_doors, game.opened_walls, game.creature)
        self.assertLessEqual(len(game.opened_walls), route_guard.MAX_DYNAMIC_OPENS)

    def test_the_same_wall_is_not_counted_twice(self):
        game = self.game()
        game.opened_walls.add((2, 2))
        game.opened_walls.add((2, 2))
        self.assertEqual(len(game.opened_walls), 1)

    def test_no_candidate_does_not_crash_or_open_anything(self):
        maze = fixtures.maze(fixtures.TRAP_LINE)   # 벽뿐이라 후보가 없다
        opened = set()
        guard = route_guard.ensure_safe_route(maze, maze.start, False, (), opened,
                                              goal=(5, 5))
        self.assertEqual(guard.status, route_guard.NO_CANDIDATE)
        self.assertEqual(opened, set())

    def test_guard_is_skipped_while_the_creature_sleeps(self):
        game = Game(load_maze("maps/maze01.txt"), map_name="m", play_mode=HORROR)
        game.attach_creature(random.Random(1))
        game.guard_route()
        self.assertEqual(game.opened_walls, set())

    def test_classic_game_never_opens_walls(self):
        game = Game(load_maze("maps/maze01.txt"), map_name="m")
        for key in "dddd":
            game.move(key)
        self.assertEqual(game.opened_walls, set())


class TestDoorBypass(unittest.TestCase):
    def setUp(self):
        self.maze = load_maze("maps/maze01.txt")

    def test_door_stays_required_with_no_walls_open(self):
        self.assertTrue(route_guard.keeps_door_required(self.maze))

    def test_a_wall_that_bypasses_the_door_is_rejected(self):
        """Door 옆 벽을 열어 Key 없이 Exit 에 갈 수 있게 되는 후보는 거부된다."""
        bypass = [wall for wall in route_guard.candidate_walls(self.maze)
                  if not route_guard.keeps_door_required(self.maze, {wall})]
        chosen = route_guard.choose_wall_to_open(
            self.maze, self.maze.start, self.maze.exit, True, (), set(),
            set(self.maze.traps))
        if bypass:
            self.assertNotIn(chosen, bypass)

    def test_opened_walls_keep_the_key_mandatory(self):
        game = Game(self.maze, map_name="m", play_mode=HORROR)
        game.attach_creature(random.Random(2))
        game.creature.activate()
        for cell in bfs(self.maze).path:
            game.creature.position = cell
            game.guard_route()
        keyless = Maze(tuple(line.replace("K", ".") for line in self.maze.grid))
        self.assertIsNone(bfs(keyless, opened_walls=game.opened_walls).path)


class TestOpenedWallConsistency(unittest.TestCase):
    """같은 opened wall 을 이동 / 탐색 / Ray / LOS 가 모두 똑같이 본다."""

    def setUp(self):
        self.maze = load_maze("maps/maze01.txt")
        self.wall = route_guard.candidate_walls(self.maze)[0]
        self.game = Game(self.maze, map_name="m")
        self.game.opened_walls.add(self.wall)

    def test_original_maze_tile_is_still_a_wall(self):
        self.assertEqual(self.maze.tile(self.wall), "#")

    def test_model_blocks_agrees(self):
        self.assertTrue(blocks(self.maze, self.wall))
        self.assertFalse(blocks(self.maze, self.wall, (), {self.wall}))

    def test_player_can_step_on_it(self):
        self.assertTrue(self.game.is_passable(self.wall))

    def test_creature_path_can_use_it(self):
        neighbours = [n for n in
                      [(self.wall[0] - 1, self.wall[1]), (self.wall[0] + 1, self.wall[1]),
                       (self.wall[0], self.wall[1] - 1), (self.wall[0], self.wall[1] + 1)]
                      if self.maze.in_bounds(n) and self.maze.tile(n) != "#"]
        self.assertTrue(neighbours)
        path = grid_astar(self.maze, neighbours[0], self.wall,
                          opened_walls={self.wall}).path
        self.assertIsNotNone(path)
        self.assertIsNone(grid_astar(self.maze, neighbours[0], self.wall).path)

    def test_ray_and_line_of_sight_pass_through(self):
        from renderer.raycaster import blocks_ray

        self.assertTrue(blocks_ray(self.maze, self.wall))
        self.assertFalse(blocks_ray(self.maze, self.wall, (), {self.wall}))
        above = (self.wall[0] - 1, self.wall[1])
        below = (self.wall[0] + 1, self.wall[1])
        if self.maze.in_bounds(above) and self.maze.in_bounds(below) \
                and self.maze.tile(above) != "#" and self.maze.tile(below) != "#":
            self.assertFalse(has_line_of_sight(above, below, self.maze))
            self.assertTrue(has_line_of_sight(above, below, self.maze, (), {self.wall}))

    def test_player_state_space_search_uses_it(self):
        self.assertIsNone(bfs(self.maze, goal=self.wall).path)
        self.assertIsNotNone(bfs(self.maze, goal=self.wall,
                                 opened_walls={self.wall}).path)


if __name__ == "__main__":
    unittest.main()
