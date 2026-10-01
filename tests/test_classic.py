"""CLASSIC 2D (과제 기본 모드) - P 표시, 기록 history, 경로 시각화, AUTO SOLVE."""

import tempfile
import unittest
from pathlib import Path

import fixtures
from ai.pathfinding import ALGORITHMS, astar, bfs, dfs, moves_for
from game import records
from game.engine import (CLASSIC, DIRECTIONS, EVENT_DOOR, EVENT_KEY,
                         EVENT_LOCKED, EVENT_TEXT, EVENT_TRAP, HORROR,
                         TRAP_PENALTY, WARN_EVENTS, Game)
from maze.loader import load_maze, save_maze
from maze.model import LEGAL_TILES, PLAYER_TILE


class TestPlayerSymbol(unittest.TestCase):
    def test_P_is_not_a_map_tile(self):
        """P 는 runtime 표시용이라 TXT 규격 문자에 들어가면 안 된다."""
        self.assertNotIn(PLAYER_TILE, LEGAL_TILES)

    def test_bundled_maps_contain_no_P(self):
        for name in ("maze01", "maze02", "maze03"):
            with self.subTest(name=name):
                text = Path(f"maps/{name}.txt").read_text(encoding="utf-8")
                self.assertNotIn(PLAYER_TILE, text)

    def test_playing_never_writes_P_into_the_map(self):
        with tempfile.TemporaryDirectory() as tmp:
            maze = fixtures.maze(fixtures.VALID)
            path = save_maze(maze, Path(tmp) / "m.txt")
            game = Game(maze, map_name="m.txt")
            for key in "dddd":
                game.move(key)
            self.assertNotIn(PLAYER_TILE, path.read_text(encoding="utf-8"))
            self.assertNotIn(PLAYER_TILE, game.maze.as_text())

    def test_player_position_is_runtime_only(self):
        game = Game(fixtures.maze(fixtures.VALID), map_name="m.txt")
        self.assertEqual(game.maze.tile(game.player.position), "S")
        game.move("d")
        self.assertEqual(game.maze.tile(game.player.position), ".")


class TestClassicMovement(unittest.TestCase):
    """과제 규칙: W/A/S/D 는 화면 기준 상/좌/하/우 절대 방향."""

    def test_absolute_direction_table(self):
        self.assertEqual(DIRECTIONS["w"], (-1, 0))
        self.assertEqual(DIRECTIONS["a"], (0, -1))
        self.assertEqual(DIRECTIONS["s"], (1, 0))
        self.assertEqual(DIRECTIONS["d"], (0, 1))

    def test_classic_mode_has_no_creature(self):
        game = Game(load_maze("maps/maze01.txt"), map_name="maze01.txt",
                    play_mode=CLASSIC)
        self.assertIsNone(game.creature)


class TestMoveEvents(unittest.TestCase):
    """2D 와 3D 가 같은 문구를 쓰도록 사건은 Game 이 한 번만 판정한다."""

    def game(self):
        return Game(load_maze("maps/maze01.txt"), map_name="maze01.txt")

    def test_no_event_on_a_plain_step(self):
        game = self.game()
        self.assertIsNone(game.last_event)
        game.move("d")
        self.assertIsNone(game.last_event)

    def test_trap_reports_itself_and_the_penalty(self):
        game = self.game()
        before = None
        for key in moves_for(bfs(game.maze).path):
            game.move(key)
            if game.last_event == EVENT_TRAP:
                before = game.player.position
                break
        self.assertIsNotNone(before, "함정을 밟는 경로가 아니다")
        self.assertEqual(game.maze.tile(before), "T")
        self.assertIn(str(TRAP_PENALTY), EVENT_TEXT[EVENT_TRAP])

    def test_key_and_door_report_themselves(self):
        game = self.game()
        seen = []
        for key in moves_for(bfs(game.maze).path):
            game.move(key)
            if game.last_event:
                seen.append(game.last_event)
        self.assertIn(EVENT_KEY, seen)
        self.assertIn(EVENT_DOOR, seen)

    def test_locked_door_reports_itself_and_refuses_the_move(self):
        game = self.game()
        game.player.position = (9, 11)          # Door (9, 12) 바로 앞
        self.assertFalse(game.move("d"))
        self.assertEqual(game.last_event, EVENT_LOCKED)
        self.assertEqual(game.player.move_count, 0)

    def test_every_event_has_text_and_warnings_are_marked(self):
        for event in (EVENT_KEY, EVENT_DOOR, EVENT_TRAP, EVENT_LOCKED):
            with self.subTest(event=event):
                self.assertTrue(EVENT_TEXT[event].strip())
        self.assertEqual(set(WARN_EVENTS), {EVENT_TRAP, EVENT_LOCKED})

    def test_event_resets_on_the_next_move(self):
        game = self.game()
        game.player.position = (9, 11)
        game.move("d")
        self.assertEqual(game.last_event, EVENT_LOCKED)
        game.move("a")
        self.assertIsNone(game.last_event)


class TestRecordHistory(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "records.json"
        self.addCleanup(self.tmp.cleanup)

    def test_history_is_created_on_the_first_clear(self):
        entry = records.update("maze01.txt", 30, 40.0, self.path, mode=CLASSIC)
        self.assertEqual(entry["history"], [{"moves": 30, "time": 40.0,
                                             "mode": CLASSIC}])

    def test_every_clear_is_appended(self):
        for moves in (30, 28, 35):
            records.update("maze01.txt", moves, 40.0, self.path)
        history = records.load(self.path)["maze01.txt"]["history"]
        self.assertEqual([play["moves"] for play in history], [30, 28, 35])

    def test_mode_is_recorded_per_play(self):
        records.update("maze01.txt", 30, 40.0, self.path, mode=CLASSIC)
        records.update("maze01.txt", 25, 50.0, self.path, mode=HORROR)
        modes = [play["mode"] for play in records.load(self.path)["maze01.txt"]["history"]]
        self.assertEqual(modes, [CLASSIC, HORROR])

    def test_best_moves_still_tracks_the_minimum(self):
        records.update("maze01.txt", 30, 40.0, self.path)
        entry = records.update("maze01.txt", 22, 90.0, self.path)
        self.assertEqual(entry["best_moves"], 22)
        self.assertEqual(entry["best_time"], 40.0)

    def test_best_time_is_independent_of_best_moves(self):
        records.update("maze01.txt", 30, 40.0, self.path)
        entry = records.update("maze01.txt", 55, 12.0, self.path)
        self.assertEqual((entry["best_moves"], entry["best_time"]), (30, 12.0))

    def test_old_file_without_history_still_loads(self):
        self.path.write_text('{"maze01.txt": {"best_moves": 40, "best_time": 90.0}}',
                             encoding="utf-8")
        entry = records.update("maze01.txt", 30, 40.0, self.path)
        self.assertEqual(entry["best_moves"], 30)
        self.assertEqual(len(entry["history"]), 1)

    def test_history_of_tolerates_missing_or_broken_field(self):
        self.assertEqual(records.history_of({}), [])
        self.assertEqual(records.history_of(None), [])
        self.assertEqual(records.history_of({"history": "oops"}), [])

    def test_history_is_capped(self):
        for index in range(records.HISTORY_LIMIT + 10):
            records.update("maze01.txt", index + 1, 10.0, self.path)
        history = records.load(self.path)["maze01.txt"]["history"]
        self.assertEqual(len(history), records.HISTORY_LIMIT)
        self.assertEqual(history[-1]["moves"], records.HISTORY_LIMIT + 10)


class TestSearchPaths(unittest.TestCase):
    """SHOW PATH 는 기존 Result.path 를 그대로 쓴다."""

    def setUp(self):
        self.maze = load_maze("maps/maze01.txt")

    def adjacent(self, path):
        return all(abs(a[0] - b[0]) + abs(a[1] - b[1]) == 1
                   for a, b in zip(path, path[1:]))

    def test_every_algorithm_returns_an_adjacent_path(self):
        for name, algorithm in ALGORITHMS.items():
            with self.subTest(name=name):
                path = algorithm(self.maze).path
                self.assertIsNotNone(path)
                self.assertTrue(self.adjacent(path))
                self.assertEqual(path[0], self.maze.start)
                self.assertEqual(path[-1], self.maze.exit)

    def test_moves_for_round_trips_a_path(self):
        path = bfs(self.maze).path
        keys = moves_for(path)
        self.assertEqual(len(keys), len(path) - 1)
        position = path[0]
        for key in keys:
            step = DIRECTIONS[key]
            position = (position[0] + step[0], position[1] + step[1])
        self.assertEqual(position, self.maze.exit)

    def test_bfs_and_astar_agree_dfs_is_not_shorter(self):
        shortest = len(bfs(self.maze).path)
        self.assertEqual(len(astar(self.maze).path), shortest)
        self.assertGreaterEqual(len(dfs(self.maze).path), shortest)


class TestAutoSolve(unittest.TestCase):
    """AUTO SOLVE 는 반드시 Game.move() 를 통해서만 움직인다."""

    def solve(self, game, algorithm):
        from ui.main_window import solution_moves

        keys = solution_moves(game, algorithm)
        for key in keys:
            game.move(key)
        return keys

    def game(self, name="maze01.txt"):
        return Game(load_maze(f"maps/{name}"), map_name=name, play_mode=CLASSIC)

    def test_auto_solve_clears_the_maze(self):
        for algorithm in ALGORITHMS.values():
            with self.subTest(algorithm=algorithm.__name__):
                game = self.game()
                self.solve(game, algorithm)
                self.assertTrue(game.cleared)

    def test_key_and_door_rules_apply_during_auto_solve(self):
        game = self.game()
        self.solve(game, bfs)
        self.assertTrue(game.player.has_key)
        self.assertEqual(game.opened_doors, set(game.maze.doors))

    def test_move_count_matches_steps_plus_trap_penalty(self):
        game = self.game()
        keys = self.solve(game, bfs)
        traps_hit = sum(1 for cell in game.visited_path if game.maze.tile(cell) == "T")
        self.assertEqual(game.player.move_count,
                         len(keys) + traps_hit * TRAP_PENALTY)

    def test_visited_path_records_the_whole_route(self):
        game = self.game()
        keys = self.solve(game, bfs)
        self.assertEqual(len(game.visited_path), len(keys) + 1)
        self.assertEqual(game.visited_path[0], game.maze.start)
        self.assertEqual(game.visited_path[-1], game.maze.exit)

    def test_solution_from_a_partway_position(self):
        from ui.main_window import solution_moves

        game = self.game()
        for key in "dddd":
            game.move(key)
        partway = game.player.position
        keys = solution_moves(game, bfs)
        for key in keys:
            game.move(key)
        self.assertTrue(game.cleared)
        self.assertNotEqual(partway, game.maze.exit)

    def test_no_solution_returns_none(self):
        from ui.main_window import solution_moves

        game = Game(fixtures.maze(fixtures.KEY_BEHIND_DOOR), map_name="x.txt")
        self.assertIsNone(solution_moves(game, bfs))

    def test_auto_solve_does_not_modify_the_map(self):
        game = self.game()
        before = game.maze.as_text()
        self.solve(game, bfs)
        self.assertEqual(game.maze.as_text(), before)


try:
    import tkinter

    from ui import preview
    from ui.main_window import format_records
except ImportError:  # tkinter 가 없는 환경
    HAS_TK = False
else:
    HAS_TK = True


@unittest.skipUnless(HAS_TK, "tkinter 를 불러올 수 없는 환경")
class TestClassicCanvas(unittest.TestCase):
    def setUp(self):
        self.root = tkinter.Tk()
        self.root.withdraw()
        self.canvas = tkinter.Canvas(self.root)
        self.addCleanup(self.root.destroy)

    def texts(self):
        return [self.canvas.itemcget(item, "text")
                for item in self.canvas.find_all()
                if self.canvas.type(item) == "text"]

    def test_player_cell_is_drawn_as_P(self):
        maze = fixtures.maze(fixtures.VALID)
        preview.draw(self.canvas, maze, player=maze.start)
        self.assertIn(PLAYER_TILE, self.texts())

    def test_no_P_when_there_is_no_player(self):
        preview.draw(self.canvas, fixtures.maze(fixtures.VALID))
        self.assertNotIn(PLAYER_TILE, self.texts())

    def test_classic_screen_shows_the_event_text(self):
        from game.engine import EVENT_TRAP, EVENT_TEXT
        from ui.main_window import ClassicScreen, MainWindow

        app = MainWindow()
        app.withdraw()
        self.addCleanup(app.destroy)
        game = Game(load_maze("maps/maze01.txt"), map_name="maze01.txt")
        app.show(ClassicScreen, game=game)
        screen = app.screen
        self.assertEqual(screen.event.cget("text"), "")
        for key in moves_for(bfs(game.maze).path):
            game.move(key)
            screen.announce()
            if game.last_event == EVENT_TRAP:
                break
        self.assertEqual(screen.event.cget("text"), EVENT_TEXT[EVENT_TRAP])

    def test_search_path_adds_canvas_items(self):
        maze = load_maze("maps/maze01.txt")
        preview.draw(self.canvas, maze)
        plain = len(self.canvas.find_all())
        preview.draw(self.canvas, maze, path=bfs(maze).path)
        self.assertGreater(len(self.canvas.find_all()), plain)

    def test_records_table_shows_plays_column(self):
        text = format_records({"maze01.txt": {"best_moves": 21, "best_time": 12.5,
                                              "history": [{"moves": 21, "time": 12.5,
                                                           "mode": "classic"}]}})
        self.assertIn("PLAYS", text)
        self.assertIn("classic", text)

    def test_records_table_handles_old_entries(self):
        text = format_records({"old.txt": {"best_moves": 9, "best_time": 1.0}})
        self.assertIn("old.txt", text)
        self.assertIn("PLAYS", text)


if __name__ == "__main__":
    unittest.main()
