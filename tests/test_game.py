import unittest

import fixtures
from fixtures import FakeClock
from game.engine import NORMAL, TIME_ATTACK, TRAP_PENALTY, Game


class TestMovement(unittest.TestCase):
    def setUp(self):
        self.game = Game(fixtures.maze(fixtures.VALID))

    def test_starts_on_start_tile(self):
        self.assertEqual(self.game.player.position, (1, 1))
        self.assertEqual(self.game.player.move_count, 0)

    def test_valid_move(self):
        self.assertTrue(self.game.move("d"))
        self.assertEqual(self.game.player.position, (1, 2))
        self.assertEqual(self.game.player.move_count, 1)

    def test_wall_blocks_move(self):
        self.assertFalse(self.game.move("w"))
        self.assertEqual(self.game.player.position, (1, 1))
        self.assertEqual(self.game.player.move_count, 0)

    def test_out_of_bounds_is_not_passable(self):
        self.assertFalse(self.game.is_passable((-1, 1)))
        self.assertFalse(self.game.is_passable((99, 99)))

    def test_only_successful_moves_are_counted(self):
        for key in "wwwdww":  # w 는 모두 벽, d 만 성공
            self.game.move(key)
        self.assertEqual(self.game.player.move_count, 1)

    def test_unknown_key_ignored(self):
        self.assertFalse(self.game.move("x"))
        self.assertEqual(self.game.player.move_count, 0)

    def test_visited_path_records_every_step(self):
        self.game.move("d")
        self.game.move("d")
        self.assertEqual(self.game.visited_path, [(1, 1), (1, 2), (1, 3)])


class TestKeyAndDoor(unittest.TestCase):
    def test_key_pickup(self):
        game = Game(fixtures.maze(fixtures.VALID))
        self.assertFalse(game.player.has_key)
        for _ in range(3):
            game.move("d")
        self.assertEqual(game.player.position, (1, 4))
        self.assertTrue(game.player.has_key)

    def test_door_blocks_without_key(self):
        game = Game(fixtures.maze(fixtures.KEY_BEHIND_DOOR))
        self.assertTrue(game.move("d"))
        self.assertFalse(game.move("d"))  # (1, 3) 은 Door
        self.assertEqual(game.player.position, (1, 2))
        self.assertEqual(game.player.move_count, 1)

    def test_door_opens_with_key(self):
        game = Game(fixtures.maze(fixtures.KEY_THEN_DOOR))
        for _ in range(2):
            game.move("d")  # (1, 2) 에서 Key 획득
        self.assertTrue(game.player.has_key)
        self.assertTrue(game.move("d"))  # (1, 4) 은 Door
        self.assertEqual(game.player.position, (1, 4))
        self.assertEqual(game.opened_doors, {(1, 4)})

    def test_original_maze_is_never_mutated(self):
        maze = fixtures.maze(fixtures.KEY_THEN_DOOR)
        game = Game(maze)
        for _ in range(4):
            game.move("d")
        self.assertEqual(maze.tile((1, 4)), "D")


class TestTrapAndExit(unittest.TestCase):
    def test_trap_adds_penalty_every_time(self):
        game = Game(fixtures.maze(fixtures.TRAP_LINE))
        game.move("d")
        game.move("d")  # (1, 3) 은 Trap
        self.assertEqual(game.player.move_count, 2 + TRAP_PENALTY)
        game.move("a")
        game.move("d")  # 다시 밟으면 또 패널티
        self.assertEqual(game.player.move_count, 4 + 2 * TRAP_PENALTY)

    def test_reaching_exit_clears(self):
        game = Game(fixtures.maze(fixtures.TRAP_LINE))
        for _ in range(7):
            game.move("d")
        self.assertEqual(game.player.position, (1, 8))
        self.assertTrue(game.cleared)

    def test_no_movement_after_clear(self):
        game = Game(fixtures.maze(fixtures.TRAP_LINE))
        for _ in range(7):
            game.move("d")
        self.assertFalse(game.move("a"))

    def test_full_valid_maze_can_be_cleared(self):
        game = Game(fixtures.maze(fixtures.VALID))
        for key in "ddddddd" "s" "s" "aaaaaaa" "s" "s" "ddddddd" "s" "s" "aaaaaaa" "s":
            game.move(key)
        self.assertTrue(game.cleared)
        self.assertEqual(game.player.move_count, 35 + TRAP_PENALTY)  # 함정 1회 통과

    def test_maze_without_start_rejected(self):
        with self.assertRaises(ValueError):
            Game(fixtures.maze(fixtures.NO_START))


class TestTimer(unittest.TestCase):
    def game(self, time_limit=None, elapsed=0.0):
        self.clock = FakeClock()
        return Game(fixtures.maze(fixtures.TRAP_LINE), time_limit=time_limit,
                    elapsed=elapsed, clock=self.clock)

    def test_normal_mode_has_no_limit(self):
        game = self.game()
        self.assertEqual(game.mode, NORMAL)
        self.assertIsNone(game.remaining)
        self.clock.advance(999.0)
        self.assertFalse(game.timed_out)
        self.assertFalse(game.over)

    def test_elapsed_follows_the_clock(self):
        game = self.game()
        self.assertEqual(game.elapsed, 0.0)
        self.clock.advance(12.5)
        self.assertEqual(game.elapsed, 12.5)

    def test_time_attack_mode_reports_remaining(self):
        game = self.game(time_limit=30.0)
        self.assertEqual(game.mode, TIME_ATTACK)
        self.clock.advance(10.0)
        self.assertEqual(game.remaining, 20.0)

    def test_timeout_ends_the_game(self):
        game = self.game(time_limit=5.0)
        self.clock.advance(5.0)
        self.assertTrue(game.timed_out)
        self.assertTrue(game.over)
        self.assertFalse(game.move("d"))
        self.assertEqual(game.player.move_count, 0)
        self.assertEqual(game.remaining, 0.0)

    def test_elapsed_freezes_after_timeout(self):
        game = self.game(time_limit=5.0)
        self.clock.advance(6.0)
        self.assertTrue(game.timed_out)
        frozen = game.elapsed
        self.clock.advance(100.0)
        self.assertEqual(game.elapsed, frozen)

    def test_elapsed_freezes_on_clear(self):
        game = self.game()
        self.clock.advance(3.0)
        for _ in range(7):
            game.move("d")
        self.assertTrue(game.cleared)
        self.clock.advance(50.0)
        self.assertEqual(game.elapsed, 3.0)

    def test_resumed_game_continues_from_saved_elapsed(self):
        game = self.game(elapsed=42.0)
        self.assertEqual(game.elapsed, 42.0)
        self.clock.advance(8.0)
        self.assertEqual(game.elapsed, 50.0)


if __name__ == "__main__":
    unittest.main()
