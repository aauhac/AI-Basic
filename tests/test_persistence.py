"""records / save_manager, 그리고 GUI 에서 분리해 둔 순수 헬퍼.

Tkinter widget 자체는 테스트하지 않는다. 표 문자열 생성과 격자 조작처럼
GUI 없이 돌 수 있는 부분만 검증한다.
"""

import json
import tempfile
import unittest
from pathlib import Path

import fixtures
from fixtures import FakeClock
from game import records, save_manager
from game.engine import Game
from maze.loader import load_maze, save_maze


class TestRecords(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "records.json"
        self.addCleanup(self.tmp.cleanup)

    def test_missing_file_starts_empty(self):
        self.assertEqual(records.load(self.path), {})

    def test_first_record_is_created(self):
        entry = records.update("maze01.txt", 30, 42.127, self.path)
        self.assertEqual(entry["best_moves"], 30)
        self.assertEqual(entry["best_time"], 42.13)
        self.assertIn("maze01.txt", records.load(self.path))

    def test_better_moves_replace_old(self):
        records.update("maze01.txt", 30, 40.0, self.path)
        entry = records.update("maze01.txt", 21, 55.0, self.path)
        self.assertEqual(entry["best_moves"], 21)

    def test_worse_record_is_kept(self):
        records.update("maze01.txt", 30, 40.0, self.path)
        entry = records.update("maze01.txt", 99, 99.0, self.path)
        self.assertEqual((entry["best_moves"], entry["best_time"]), (30, 40.0))

    def test_moves_and_time_are_independent(self):
        records.update("maze01.txt", 30, 40.0, self.path)
        entry = records.update("maze01.txt", 50, 12.5, self.path)
        self.assertEqual((entry["best_moves"], entry["best_time"]), (30, 12.5))

    def test_broken_json_does_not_raise(self):
        self.path.write_text("{ this is not json", encoding="utf-8")
        self.assertEqual(records.load(self.path), {})
        self.assertEqual(records.update("maze01.txt", 7, 7.0, self.path)["best_moves"], 7)

    def test_non_dict_json_is_ignored(self):
        self.path.write_text("[1, 2, 3]", encoding="utf-8")
        self.assertEqual(records.load(self.path), {})

    def test_maps_are_recorded_separately(self):
        records.update("maze01.txt", 10, 10.0, self.path)
        records.update("maze02.txt", 20, 20.0, self.path)
        self.assertEqual(sorted(records.load(self.path)), ["maze01.txt", "maze02.txt"])


class TestSaveManager(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        # 원본 TXT 를 임시 maps 디렉터리에 복사해 두고 그것만 건드린다.
        self.maps = self.dir / "maps"
        self.maze = fixtures.maze(fixtures.VALID)
        self.map_path = save_maze(self.maze, self.maps / "valid.txt")
        self.original = self.map_path.read_text(encoding="utf-8")

    def played_game(self):
        game = Game(self.maze, time_limit=120, map_name="valid.txt")
        for key in "dddd":  # (1, 4) 의 Key 까지 이동
            game.move(key)
        return game

    def test_round_trip_keeps_logical_state(self):
        game = self.played_game()
        path = save_manager.save_game(game, self.dir / "s.json")
        loaded = save_manager.load_game(path, maps_dir=self.maps)
        self.assertEqual(loaded.player.position, game.player.position)
        self.assertEqual(loaded.player.has_key, game.player.has_key)
        self.assertEqual(loaded.player.move_count, game.player.move_count)
        self.assertEqual(loaded.visited_path, game.visited_path)
        self.assertEqual(loaded.opened_doors, game.opened_doors)
        self.assertEqual(loaded.time_limit, game.time_limit)
        self.assertEqual(loaded.mode, game.mode)
        self.assertEqual(loaded.maze, game.maze)

    def test_elapsed_time_carries_over(self):
        clock = FakeClock()
        game = Game(self.maze, map_name="valid.txt", clock=clock)
        clock.advance(30.0)
        path = save_manager.save_game(game, self.dir / "s.json")
        loaded = save_manager.load_game(path, maps_dir=self.maps)
        self.assertGreaterEqual(loaded.elapsed, 30.0)

    def test_opened_door_survives_reload(self):
        game = Game(fixtures.maze(fixtures.KEY_THEN_DOOR), map_name="door.txt")
        save_maze(game.maze, self.maps / "door.txt")
        for _ in range(4):
            game.move("d")
        self.assertEqual(game.opened_doors, {(1, 4)})
        path = save_manager.save_game(game, self.dir / "d.json")
        loaded = save_manager.load_game(path, maps_dir=self.maps)
        self.assertEqual(loaded.opened_doors, {(1, 4)})

    def test_original_map_is_untouched(self):
        game = self.played_game()
        save_manager.save_game(game, self.dir / "s.json")
        save_manager.load_game(self.dir / "s.json", maps_dir=self.maps)
        self.assertEqual(self.map_path.read_text(encoding="utf-8"), self.original)

    def test_save_file_holds_no_map_content(self):
        game = self.played_game()
        state = json.loads(save_manager.save_game(game, self.dir / "s.json")
                           .read_text(encoding="utf-8"))
        self.assertEqual(state["map"], "valid.txt")
        self.assertNotIn("grid", state)

    def test_numbered_paths_do_not_collide(self):
        first = save_manager.next_numbered_path(self.dir, "save", ".json")
        first.write_text("{}", encoding="utf-8")
        second = save_manager.next_numbered_path(self.dir, "save", ".json")
        self.assertEqual((first.name, second.name), ("save_001.json", "save_002.json"))

    def test_latest_save_is_none_when_empty(self):
        self.assertIsNone(save_manager.latest_save(self.dir / "empty"))


class TestCreatureSave(unittest.TestCase):
    """Horror 저장에는 Creature 의 기억까지 들어간다. 예전 파일도 그대로 읽힌다."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        self.maps = self.dir / "maps"
        save_maze(load_maze("maps/maze01.txt"), self.maps / "maze01.txt")

    def horror_game(self):
        import random

        from game.engine import HORROR

        game = Game(load_maze("maps/maze01.txt"), map_name="maze01.txt",
                    play_mode=HORROR)
        game.attach_creature(random.Random(5))
        return game

    def round_trip(self, game):
        path = save_manager.save_game(game, self.dir / "s.json")
        return save_manager.load_game(path, maps_dir=self.maps)

    def test_creature_state_survives_the_round_trip(self):
        game = self.horror_game()
        game.creature.activate()
        game.creature.state = "search"
        game.creature.position = (5, 5)
        game.creature.facing = "a"
        game.creature.last_seen_position = (7, 3)
        game.creature.memory_remaining = 2.5
        game.creature.target = (7, 3)
        game.creature.searches_left = 2
        game.creature.move_timer = 0.2

        loaded = self.round_trip(game).creature
        self.assertEqual(loaded.position, (5, 5))
        self.assertEqual(loaded.facing, "a")
        self.assertEqual(loaded.state, "search")
        self.assertTrue(loaded.active)
        self.assertEqual(loaded.last_seen_position, (7, 3))
        self.assertEqual(loaded.memory_remaining, 2.5)
        self.assertEqual(loaded.target, (7, 3))
        self.assertEqual(loaded.searches_left, 2)

    def test_play_mode_is_saved(self):
        from game.engine import HORROR

        self.assertEqual(self.round_trip(self.horror_game()).play_mode, HORROR)

    def test_caught_flag_is_saved(self):
        game = self.horror_game()
        game.creature.activate()
        game.check_caught(game.player.position)
        self.assertTrue(self.round_trip(game).caught)

    def test_classic_save_has_no_creature(self):
        game = Game(load_maze("maps/maze01.txt"), map_name="maze01.txt")
        loaded = self.round_trip(game)
        self.assertIsNone(loaded.creature)
        self.assertEqual(loaded.play_mode, "classic")

    def test_old_save_without_creature_fields_still_loads(self):
        state = json.loads(save_manager.save_game(self.horror_game(),
                                                  self.dir / "s.json")
                           .read_text(encoding="utf-8"))
        for field in ("creature", "play_mode", "caught", "timer_mode"):
            state.pop(field, None)
        legacy = self.dir / "legacy.json"
        legacy.write_text(json.dumps(state), encoding="utf-8")
        loaded = save_manager.load_game(legacy, maps_dir=self.maps)
        self.assertIsNone(loaded.creature)
        self.assertEqual(loaded.play_mode, "classic")
        self.assertFalse(loaded.caught)

    def test_opened_walls_survive_the_round_trip(self):
        from ai import route_guard

        game = self.horror_game()
        walls = set(route_guard.candidate_walls(game.maze)[:2])
        self.assertEqual(len(walls), 2)
        game.opened_walls.update(walls)
        loaded = self.round_trip(game)
        self.assertEqual(loaded.opened_walls, walls)
        for wall in walls:
            self.assertTrue(loaded.is_passable(wall))
            self.assertEqual(loaded.maze.tile(wall), "#")   # 원본은 여전히 벽

    def test_old_save_without_opened_walls_loads_empty(self):
        state = json.loads(save_manager.save_game(self.horror_game(),
                                                  self.dir / "s.json")
                           .read_text(encoding="utf-8"))
        state.pop("opened_walls")
        legacy = self.dir / "legacy_walls.json"
        legacy.write_text(json.dumps(state), encoding="utf-8")
        loaded = save_manager.load_game(legacy, maps_dir=self.maps)
        self.assertEqual(loaded.opened_walls, set())

    def test_resumed_creature_keeps_hunting(self):
        game = self.horror_game()
        game.creature.activate()
        loaded = self.round_trip(game)
        before = loaded.creature.position
        for _ in range(6):
            loaded.tick_creature(0.5)
        self.assertNotEqual(loaded.creature.position, before)


try:
    from ui.editor import blank_grid, grid_to_maze
    from ui.main_window import describe_maze, format_records
except ImportError:  # tkinter 가 없는 환경
    HAS_UI = False
else:
    HAS_UI = True


@unittest.skipUnless(HAS_UI, "tkinter 를 불러올 수 없는 환경")
class TestUiHelpers(unittest.TestCase):
    def test_blank_grid_has_only_outer_wall(self):
        maze = grid_to_maze(blank_grid(12, 11))
        self.assertEqual((maze.width, maze.height), (12, 11))
        self.assertEqual(set(maze.grid[0]), {"#"})
        self.assertEqual(set(maze.grid[-1]), {"#"})
        self.assertEqual(maze.grid[1], "#" + "." * 10 + "#")

    def test_blank_grid_only_needs_start_and_exit_to_be_valid(self):
        from maze.validator import validate

        grid = blank_grid(12, 12)
        grid[1][1], grid[10][10] = "S", "E"
        self.assertEqual(validate(grid_to_maze(grid)), [])

    def test_format_records_empty(self):
        self.assertIn("기록이 없습니다", format_records({}))

    def test_format_records_lists_each_map(self):
        text = format_records({"maze01.txt": {"best_moves": 21, "best_time": 12.5}})
        self.assertIn("maze01.txt", text)
        self.assertIn("21", text)
        self.assertIn("12.50", text)

    def test_format_records_tolerates_missing_fields(self):
        self.assertIn("-", format_records({"maze01.txt": {}}))

    def test_describe_maze_reports_pass_and_algorithms(self):
        text = describe_maze(load_maze("maps/maze01.txt"), "maze01.txt")
        self.assertIn("VALIDATION: PASS", text)
        for name in ("bfs", "dfs", "astar"):
            self.assertIn(name, text)

    def test_describe_maze_reports_failure_reason(self):
        text = describe_maze(fixtures.maze(fixtures.UNREACHABLE_EXIT), "broken.txt")
        self.assertIn("VALIDATION: FAIL", text)
        self.assertIn("Exit에 도달할 수 없습니다", text)


if __name__ == "__main__":
    unittest.main()
