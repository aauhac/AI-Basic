"""Creature 의 시각 / 기억 / FSM / 이동 / 잡힘.

Creature AI 에는 Player 좌표가 들어가지 않는다. 그 점 자체도 테스트한다.
"""

import inspect
import random
import unittest

import fixtures
from ai import perception
from ai.creature import (
    CHASE,
    DORMANT,
    MOVE_INTERVAL,
    PATROL,
    SEARCH,
    Creature,
    spawn_for,
)
from ai.pathfinding import bfs, grid_astar, grid_distances
from ai.perception import Observation, observe
from game.engine import HORROR, Game
from maze.loader import load_maze

# Door (3, 4) 가 있는 10x10 방. 시야 테스트에 쓰기 좋다.
ROOM = fixtures.RAY_ROOM


def seen(position):
    return Observation(True, position)


BLIND = Observation(False, None)


class TestPerception(unittest.TestCase):
    def setUp(self):
        self.room = fixtures.maze(ROOM)
        self.snake = fixtures.maze(fixtures.VALID)

    def test_player_in_front_within_range_is_visible(self):
        self.assertTrue(observe((5, 2), "d", (5, 5), self.room).visible)

    def test_player_behind_is_not_visible(self):
        self.assertFalse(observe((5, 2), "d", (5, 1), self.room).visible)

    def test_player_beyond_vision_distance_is_not_visible(self):
        far = int(perception.VISION_DISTANCE) + 2
        self.assertFalse(observe((5, 1), "d", (5, 1 + far), self.room).visible)

    def test_wall_blocks_sight(self):
        # VALID 미로에서 (2, 1) 은 벽이라 (1, 1) 에서 (3, 1) 이 보이면 안 된다.
        self.assertEqual(self.snake.tile((2, 1)), "#")
        self.assertFalse(observe((1, 1), "s", (3, 1), self.snake).visible)

    def test_open_corridor_is_visible(self):
        self.assertTrue(observe((1, 1), "d", (1, 3), self.snake).visible)

    def test_closed_door_blocks_sight(self):
        self.assertFalse(observe((1, 4), "s", (5, 4), self.room).visible)

    def test_opened_door_lets_sight_through(self):
        self.assertTrue(observe((1, 4), "s", (5, 4), self.room,
                                opened_doors={(3, 4)}).visible)

    def test_fov_boundary_is_inclusive(self):
        self.assertTrue(observe((5, 2), "d", (4, 3), self.room).visible)   # 정확히 45도

    def test_just_outside_the_fov_is_not_visible(self):
        self.assertFalse(observe((5, 2), "d", (3, 3), self.room).visible)

    def test_same_cell_is_visible(self):
        self.assertTrue(observe((4, 4), "d", (4, 4), self.room).visible)

    def test_observation_carries_only_a_coordinate(self):
        observation = observe((5, 2), "d", (5, 5), self.room)
        self.assertEqual(set(vars(observation)), {"visible", "position"})
        self.assertIsInstance(observation.position, tuple)
        self.assertTrue(all(isinstance(value, int) for value in observation.position))

    def test_blind_observation_has_no_position(self):
        self.assertIsNone(observe((5, 2), "d", (5, 1), self.room).position)


class TestAiIsolation(unittest.TestCase):
    def test_update_never_receives_the_player(self):
        names = list(inspect.signature(Creature.update).parameters)
        self.assertEqual(names, ["self", "observation", "maze", "opened_doors",
                                 "seconds", "opened_walls"])
        for name in names:
            self.assertNotIn("player", name)

    def test_creature_has_no_reference_to_the_game(self):
        creature = Creature(position=(1, 1))
        for value in vars(creature).values():
            self.assertNotIsInstance(value, Game)


class TestFiniteStateMachine(unittest.TestCase):
    def setUp(self):
        self.maze = fixtures.maze(ROOM)
        self.creature = Creature(position=(8, 8), facing="w",
                                 rng=random.Random(7))

    def tick(self, observation, seconds=MOVE_INTERVAL):
        self.creature.update(observation, self.maze, (), seconds)

    def test_dormant_creature_does_not_move_or_react(self):
        before = self.creature.position
        self.tick(seen((1, 1)))
        self.assertEqual(self.creature.state, DORMANT)
        self.assertEqual(self.creature.position, before)
        self.assertIsNone(self.creature.last_seen_position)

    def test_activate_switches_to_patrol(self):
        self.creature.activate()
        self.assertTrue(self.creature.active)
        self.assertEqual(self.creature.state, PATROL)

    def test_patrol_moves_towards_a_target(self):
        self.creature.activate()
        before = self.creature.position
        self.tick(BLIND)
        self.assertIsNotNone(self.creature.target)
        self.assertNotEqual(self.creature.position, before)

    def test_seeing_the_player_starts_a_chase(self):
        self.creature.activate()
        self.tick(seen((8, 5)))
        self.assertEqual(self.creature.state, CHASE)
        self.assertEqual(self.creature.last_seen_position, (8, 5))
        self.assertEqual(self.creature.target, (8, 5))

    def test_losing_sight_starts_a_search_at_the_last_seen_cell(self):
        self.creature.activate()
        self.tick(seen((8, 5)))
        self.tick(BLIND)
        self.assertEqual(self.creature.state, SEARCH)
        self.assertEqual(self.creature.last_seen_position, (8, 5))

    def test_search_walks_to_the_remembered_cell(self):
        self.creature.activate()
        self.creature.position = (8, 8)
        self.tick(seen((8, 4)))
        for _ in range(12):
            self.tick(BLIND)
            if self.creature.position == (8, 4):
                break
        self.assertEqual(self.creature.position, (8, 4))

    def test_seeing_the_player_again_returns_to_chase(self):
        self.creature.activate()
        self.tick(seen((8, 5)))
        self.tick(BLIND)
        self.assertEqual(self.creature.state, SEARCH)
        self.tick(seen((8, 6)))
        self.assertEqual(self.creature.state, CHASE)
        self.assertEqual(self.creature.target, (8, 6))

    def test_memory_expires_back_to_patrol(self):
        self.creature.activate()
        self.tick(seen((8, 5)))
        self.tick(BLIND)
        self.assertEqual(self.creature.state, SEARCH)
        for _ in range(20):
            self.tick(BLIND, seconds=1.0)
        self.assertEqual(self.creature.state, PATROL)
        self.assertIsNone(self.creature.last_seen_position)

    def test_memory_countdown_only_runs_while_blind(self):
        self.creature.activate()
        self.tick(seen((8, 5)))
        full = self.creature.memory_remaining
        self.tick(seen((8, 5)), seconds=2.0)
        self.assertEqual(self.creature.memory_remaining, full)
        self.tick(BLIND, seconds=2.0)
        self.assertLess(self.creature.memory_remaining, full)


class TestNavigation(unittest.TestCase):
    def setUp(self):
        self.maze = fixtures.maze(ROOM)

    def test_grid_path_uses_adjacent_cells(self):
        path = grid_astar(self.maze, (1, 1), (8, 8)).path
        self.assertIsNotNone(path)
        for first, second in zip(path, path[1:]):
            self.assertEqual(abs(first[0] - second[0]) + abs(first[1] - second[1]), 1)

    def test_path_never_crosses_a_wall(self):
        path = grid_astar(self.maze, (1, 1), (8, 8)).path
        for cell in path:
            self.assertNotEqual(self.maze.tile(cell), "#")

    def test_closed_door_is_not_passable(self):
        maze = fixtures.maze(fixtures.KEY_BEHIND_DOOR)
        self.assertIsNone(grid_astar(maze, maze.start, maze.exit).path)

    def test_opened_door_is_passable(self):
        maze = fixtures.maze(fixtures.KEY_BEHIND_DOOR)
        path = grid_astar(maze, maze.start, maze.exit, opened_doors={(1, 3)}).path
        self.assertIsNotNone(path)

    def test_unreachable_target_returns_no_path(self):
        maze = fixtures.maze(fixtures.ISOLATED_FLOOR)
        self.assertIsNone(grid_astar(maze, maze.start, (3, 1)).path)

    def test_target_inside_a_wall_returns_no_path(self):
        self.assertIsNone(grid_astar(self.maze, (1, 1), (0, 0)).path)

    def test_facing_follows_the_actual_step(self):
        creature = Creature(position=(5, 5), facing="w", rng=random.Random(1))
        creature.activate()
        creature.target = (5, 8)
        creature.update(BLIND, self.maze, (), MOVE_INTERVAL)
        self.assertEqual(creature.position, (5, 6))
        self.assertEqual(creature.facing, "d")

    def test_no_move_before_the_interval_elapses(self):
        creature = Creature(position=(5, 5), rng=random.Random(1))
        creature.activate()
        creature.update(BLIND, self.maze, (), 0.0)      # 첫 tick 에서 한 칸
        moved = creature.position
        creature.update(BLIND, self.maze, (), MOVE_INTERVAL / 4)
        self.assertEqual(creature.position, moved)

    def test_one_cell_per_interval(self):
        from ai.creature import MOVE_INTERVALS

        creature = Creature(position=(5, 5), rng=random.Random(1))
        creature.activate()
        creature.update(BLIND, self.maze, (), 0.0)
        first = creature.position
        creature.update(BLIND, self.maze, (), MOVE_INTERVALS[creature.state])
        self.assertEqual(abs(creature.position[0] - first[0])
                         + abs(creature.position[1] - first[1]), 1)

    def test_patrol_target_is_not_next_door(self):
        creature = Creature(position=(1, 1), rng=random.Random(3))
        creature.activate()
        creature.update(BLIND, self.maze, (), 0.0)
        steps = grid_distances(self.maze, (1, 1))
        self.assertGreaterEqual(steps[creature.target], 5)

    def test_patrol_target_is_always_a_plain_floor_cell(self):
        """Exit / Key / Trap / Door / Start / Spawn 은 순찰 목적지가 아니다."""
        maze = load_maze("maps/maze01.txt")
        opened = set(maze.doors)
        for seed in range(200):
            creature = Creature(position=maze.creature_spawns[0],
                                rng=random.Random(seed))
            creature.activate()
            target = creature._patrol_target(maze, opened)
            with self.subTest(seed=seed):
                self.assertIsNotNone(target)
                self.assertEqual(maze.tile(target), ".")

    def test_chase_can_still_reach_the_exit(self):
        """순찰 제한 때문에 추격이 Exit 를 못 가면 안 된다."""
        maze = load_maze("maps/maze01.txt")
        opened = set(maze.doors)
        creature = Creature(position=maze.creature_spawns[0], rng=random.Random(1))
        creature.activate()
        creature.update(seen(maze.exit), maze, opened, 0.0)
        self.assertEqual(creature.state, CHASE)
        self.assertEqual(creature.target, maze.exit)
        self.assertIsNotNone(grid_astar(maze, creature.position, maze.exit, opened).path)

    def test_creature_can_walk_through_a_runtime_opened_wall(self):
        from ai import route_guard

        maze = load_maze("maps/maze01.txt")
        wall = route_guard.candidate_walls(maze)[0]
        self.assertIsNone(grid_astar(maze, maze.start, wall).path)
        self.assertIsNotNone(grid_astar(maze, maze.start, wall,
                                        opened_walls={wall}).path)

    def test_spawn_uses_the_G_tile(self):
        maze = load_maze("maps/maze01.txt")
        creature = spawn_for(maze, random.Random(1))
        self.assertEqual(creature.position, maze.creature_spawns[0])
        self.assertEqual(creature.state, DORMANT)
        self.assertFalse(creature.active)

    def test_map_without_G_has_no_creature(self):
        self.assertIsNone(spawn_for(fixtures.maze(fixtures.KEY_THEN_DOOR)))


class TestCaught(unittest.TestCase):
    def game(self):
        game = Game(load_maze("maps/maze01.txt"), map_name="maze01.txt",
                    play_mode=HORROR)
        game.attach_creature(random.Random(1))
        return game

    def test_different_cells_are_safe(self):
        game = self.game()
        self.assertFalse(game.check_caught((0, 0)))
        self.assertFalse(game.caught)
        self.assertFalse(game.over)

    def test_same_cell_is_caught(self):
        game = self.game()
        game.creature.activate()
        self.assertTrue(game.check_caught(game.player.position))
        self.assertTrue(game.caught)
        self.assertTrue(game.over)

    def test_movement_stops_after_being_caught(self):
        game = self.game()
        game.creature.activate()
        game.check_caught(game.player.position)
        self.assertFalse(game.move("d"))
        self.assertEqual(game.player.move_count, 0)

    def test_a_cleared_game_cannot_be_caught_afterwards(self):
        game = self.game()
        game.cleared = True
        self.assertFalse(game.check_caught(game.player.position))
        self.assertFalse(game.caught)

    def test_creature_wakes_up_when_the_key_is_taken(self):
        game = self.game()
        self.assertEqual(game.creature.state, DORMANT)
        for key in "ddddssssdddd":
            game.move(key)
        self.assertTrue(game.player.has_key)
        self.assertTrue(game.creature.active)
        self.assertEqual(game.creature.state, PATROL)

    def test_dormant_creature_stays_put_during_ticks(self):
        game = self.game()
        spawn = game.creature.position
        for _ in range(10):
            game.tick_creature(1.0)
        self.assertEqual(game.creature.position, spawn)

    def test_creature_on_the_exit_catches_the_player_walking_in(self):
        """조사에서 나온 버그. Exit 칸이라도 접촉이 먼저다."""
        from ai.pathfinding import moves_for

        game = self.game()
        game.creature.activate()
        game.creature.position = game.maze.exit
        keys = moves_for(bfs(game.maze).path)
        for key in keys[:-1]:
            game.move(key)
            game.creature.position = game.maze.exit    # Exit 에 계속 서 있게 둔다
        self.assertFalse(game.over)
        game.move(keys[-1])                            # Exit 칸으로 진입
        self.assertEqual(game.player.position, game.maze.exit)
        self.assertEqual(game.creature.position, game.maze.exit)
        self.assertTrue(game.caught)
        self.assertFalse(game.cleared)

    def test_exit_without_a_creature_still_clears(self):
        from ai.pathfinding import moves_for

        game = self.game()
        game.creature.position = (3, 9)
        for key in moves_for(bfs(game.maze).path):
            game.move(key)
        self.assertTrue(game.cleared)
        self.assertFalse(game.caught)

    def test_cleared_and_caught_are_never_both_true(self):
        from ai.pathfinding import moves_for

        for creature_cell in (None, (3, 9)):
            game = self.game()
            game.creature.activate()
            if creature_cell is None:
                game.creature.position = game.maze.exit
            else:
                game.creature.position = creature_cell
            for key in moves_for(bfs(game.maze).path):
                game.move(key)
                game.tick_creature(0.0)
                if creature_cell is None:
                    game.creature.position = game.maze.exit
            with self.subTest(creature=creature_cell):
                self.assertFalse(game.cleared and game.caught)
                self.assertTrue(game.over)

    def test_dormant_creature_does_not_catch(self):
        """열쇠를 먹기 전에는 같은 칸에 들어가도 잡히지 않는다.

        move() 뿐 아니라 실제 루프의 tick_creature() 경로까지 확인한다.
        예전에는 check_caught() 가 active 를 보지 않아 tick 에서 잡혔다.
        """
        game = self.game()
        spawn = game.maze.creature_spawns[0]
        game.player.position = (spawn[0], spawn[1] - 1)
        self.assertFalse(game.creature.active)
        self.assertTrue(game.move("d"))
        self.assertEqual(game.player.position, spawn)
        self.assertFalse(game.caught)
        for _ in range(10):                       # 게임 루프가 계속 돌아도
            game.tick_creature(1 / 60)
        self.assertFalse(game.caught)
        self.assertFalse(game.over)

    def test_waking_up_on_the_player_cell_catches(self):
        """같은 칸에 선 채로 열쇠를 먹어 깨어나면 그때는 잡힌다."""
        game = self.game()
        game.player.position = game.maze.creature_spawns[0]
        game.tick_creature(1 / 60)
        self.assertFalse(game.caught)
        game.creature.activate()
        game.tick_creature(1 / 60)
        self.assertTrue(game.caught)

    def test_result_screen_says_entity_contact(self):
        from renderer.game_view import result_text

        game = self.game()
        game.creature.activate()
        game.check_caught(game.player.position)
        text = result_text(game)
        self.assertIn("ENTITY CONTACT", text)
        self.assertIn("YOU WERE CAUGHT", text)

    def test_result_screen_distinguishes_the_three_endings(self):
        from renderer.game_view import result_text

        caught = self.game()
        caught.creature.activate()
        caught.check_caught(caught.player.position)
        cleared = self.game()
        cleared.cleared = True
        timeout = Game(load_maze("maps/maze01.txt"), time_limit=0.0,
                       map_name="maze01.txt")
        self.assertTrue(timeout.timed_out)
        endings = {result_text(caught).split("\n")[0],
                   result_text(cleared).split("\n")[0],
                   result_text(timeout).split("\n")[0]}
        self.assertEqual(endings, {"ENTITY CONTACT", "MAZE CLEARED", "TIME OVER"})

    def test_classic_game_has_no_creature(self):
        game = Game(load_maze("maps/maze01.txt"), map_name="maze01.txt")
        self.assertIsNone(game.creature)
        game.tick_creature(1.0)      # 아무 일도 없어야 한다
        self.assertFalse(game.caught)


if __name__ == "__main__":
    unittest.main()
