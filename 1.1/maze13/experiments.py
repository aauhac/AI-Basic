"""보고서용 실험 러너. 게임 기능이 아니라 측정 전용 스크립트다.

    python experiments.py            전부 실행
    python experiments.py a c        일부만 (a=pathfinding, b=generator,
                                     c=rendering, d=creature,
                                     e=adaptive escape route)

결과는 results/ 아래 CSV 와 로그로 저장한다.
"""

import csv
import random
import sys
import time
from pathlib import Path

from ai import route_guard
from ai.creature import CHASE, DORMANT, PATROL, SEARCH, Creature
from ai.pathfinding import ALGORITHMS, bfs, grid_astar, grid_distances, moves_for
from ai.perception import Observation, observe
from game.engine import HORROR, Game
from maze.generator import generate
from maze.loader import load_maze, parse_maze
from maze.validator import validate, walkable_positions

RESULTS = Path("results")
BASE_MAPS = ("maze01.txt", "maze02.txt", "maze03.txt")


def write_csv(name: str, header, rows) -> Path:
    RESULTS.mkdir(exist_ok=True)
    path = RESULTS / name
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)
    return path


def show(header, rows, widths=None) -> None:
    widths = widths or [max(len(str(r[i])) for r in [header] + rows) for i in range(len(header))]
    line = "  ".join(str(cell).ljust(width) for cell, width in zip(header, widths))
    print(line)
    print("-" * len(line))
    for row in rows:
        print("  ".join(str(cell).ljust(width) for cell, width in zip(row, widths)))


def timed(call, repeats: int, warmup: int = 0) -> float:
    """한 번 호출이 너무 짧아 noise 가 크므로 반복 평균을 ms 로 돌려준다.

    warmup 은 첫 대상이 초기화 비용을 혼자 떠안아 느리게 보이는 것을 막는다.
    """
    for _ in range(warmup):
        call()
    started = time.perf_counter()
    for _ in range(repeats):
        call()
    return (time.perf_counter() - started) * 1000 / repeats


# --- A. BFS / DFS / A* -------------------------------------------------------

def experiment_pathfinding(repeats=300):
    rows = []
    for name in BASE_MAPS:
        maze = load_maze(f"maps/{name}")
        for algo, algorithm in ALGORITHMS.items():
            result = algorithm(maze)
            moves = len(result.path) - 1 if result.path else -1
            ms = timed(lambda a=algorithm, m=maze: a(m), repeats)
            rows.append([name, algo, moves, result.visited, f"{ms:.4f}", repeats])
    path = write_csv("pathfinding.csv",
                     ["map", "algorithm", "moves", "visited_states",
                      "avg_ms", "repeats"], rows)
    print(f"\n[A] Pathfinding  (각 {repeats}회 평균)")
    show(["map", "algo", "moves", "visited", "avg_ms"],
         [[r[0], r[1], r[2], r[3], r[4]] for r in rows])
    return path


# --- B. Random Maze Generator ------------------------------------------------

def experiment_generator(seeds=30):
    rows = []
    for width, height in ((11, 11), (21, 15), (31, 21)):
        for loop_ratio in (0.0, 0.05, 0.10):
            for specials in (True, False):
                made = valid = trap_safe = 0
                total_ms = total_moves = total_cells = 0.0
                for seed in range(seeds):
                    started = time.perf_counter()
                    try:
                        maze = generate(width, height, seed=seed,
                                        loop_ratio=loop_ratio, specials=specials)
                    except ValueError:
                        continue          # 구조적으로 Door 자리가 없어 거부된 경우
                    total_ms += (time.perf_counter() - started) * 1000
                    made += 1
                    if not validate(maze):
                        valid += 1
                    total_moves += len(bfs(maze).path) - 1
                    total_cells += len(walkable_positions(maze))
                    # 모든 Trap 을 동시에 막아도 클리어 가능한지 (생성 단계 보정 확인)
                    if bfs(maze, extra_blocked=set(maze.traps)).path is not None:
                        trap_safe += 1
                rows.append([f"{width}x{height}", loop_ratio, specials, seeds, made,
                             valid, trap_safe, f"{made / seeds * 100:.1f}",
                             f"{total_ms / max(made, 1):.2f}",
                             f"{total_moves / max(made, 1):.1f}",
                             f"{total_cells / max(made, 1):.1f}"])
    path = write_csv("generator.csv",
                     ["size", "loop_ratio", "specials", "attempts", "generated",
                      "validated", "trap_safe", "success_rate",
                      "avg_ms", "avg_bfs_moves", "avg_walkable_cells"], rows)
    print(f"\n[B] Random Maze Generator  (조합당 seed {seeds}개)")
    show(["size", "loop", "spec", "gen", "valid", "trapsafe", "rate%",
          "avg_ms", "bfs", "cells"],
         [[r[0], r[1], r[2], r[4], r[5], r[6], r[7], r[8], r[9], r[10]] for r in rows])
    return path


# --- C. Raycasting -----------------------------------------------------------

def experiment_rendering(frames=300):
    import math

    import pygame

    from renderer.game_view import INTERNAL_SIZE, background, render_frame
    from renderer.raycaster import Camera

    pygame.init()
    surface = pygame.Surface(INTERNAL_SIZE)
    sky = background(INTERNAL_SIZE)
    targets = [(name, load_maze(f"maps/{name}")) for name in BASE_MAPS]
    targets += [(f"random_{w}x{h}", generate(w, h, seed=7, loop_ratio=0.1, specials=True))
                for w, h in ((11, 11), (21, 15), (31, 21))]

    rows = []
    for label, maze in targets:
        row, col = maze.start
        camera = Camera(row + 0.5, col + 0.5)

        def one_frame(frame=[0], cam=camera, m=maze):
            cam.angle = frame[0] * math.tau / frames
            frame[0] += 1
            render_frame(surface, m, cam, (), sky)

        ms = timed(one_frame, frames, warmup=60)
        rows.append([label, f"{maze.width}x{maze.height}", maze.width * maze.height,
                     f"{ms:.3f}", f"{1000 / ms:.0f}"])
    pygame.quit()
    path = write_csv("rendering.csv",
                     ["map", "size", "cells", "avg_ms_per_frame", "estimated_fps"], rows)
    print(f"\n[C] Raycasting  (내부 {INTERNAL_SIZE[0]}x{INTERNAL_SIZE[1]}, {frames} frames)")
    show(["map", "size", "cells", "ms/frame", "fps"], rows)
    return path


# --- D. Creature AI ----------------------------------------------------------

SCENARIO_MAP = """\
##############
#S..........K#
#.############
#.############
#.############
#.############
#.############
#.############
#G..........E#
##############
"""


def experiment_creature(repeats=2000):
    maze = parse_maze(SCENARIO_MAP)
    rows = []
    for label, state in ((DORMANT, None), (PATROL, PATROL),
                         (SEARCH, SEARCH), (CHASE, CHASE)):
        creature = Creature(position=(8, 1), rng=random.Random(1))
        if state:
            creature.activate()
            creature.state = state
            creature.target = (1, 1) if state in (CHASE, SEARCH) else None
            if state == SEARCH:
                creature.last_seen_position = (1, 1)
                creature.memory_remaining = 5.0
        seen = Observation(True, (1, 1)) if state == CHASE else Observation(False, None)
        ms = timed(lambda c=creature, o=seen: c.update(o, maze, (), 1 / 60), repeats)
        rows.append([label, f"{ms:.5f}", repeats])
    path = write_csv("creature_update.csv",
                     ["state", "avg_ms_per_update", "repeats"], rows)
    print(f"\n[D] Creature update  (각 {repeats}회 평균)")
    show(["state", "avg_ms", "repeats"], rows)
    return path, scenario_log()


def scenario_log() -> Path:
    """FSM 전이를 순서대로 기록한다. seed 와 위치를 전부 고정해 재현 가능하다.

    각 단계에서 상황만 배치하고, 상태 전이는 실제 observe() + Creature.update() 가
    만든다. 그래서 label 과 실제 state 가 어긋나면 그대로 드러난다.
    """
    maze = parse_maze(SCENARIO_MAP)
    game = Game(maze, map_name="scenario.txt", play_mode=HORROR)
    creature = game.attach_creature(random.Random(4))
    rows = []

    def note(step, setup="-"):
        seen = observe(creature.position, creature.facing, game.player.position,
                       game.maze, game.opened_doors, game.opened_walls)
        rows.append([step, setup, creature.state, str(creature.position),
                     str(game.player.position), creature.facing, str(seen.visible),
                     str(creature.last_seen_position),
                     f"{creature.memory_remaining:.1f}",
                     str(creature.target), len(creature.path), str(game.caught)])

    note("1 시작")
    for _ in range(8):
        game.tick_creature(0.5)
    note("2 DORMANT 유지")

    for _ in range(11):                       # 위쪽 복도를 걸어 Key 까지
        game.move("d")
        game.tick_creature(0.5)
    note("3 Key 획득 -> 활성화")

    for _ in range(4):
        game.tick_creature(0.5)
    note("4 PATROL 이동")

    # 아래 복도에서 마주치는 상황을 만든다. 이동 중 접촉하면 FSM 을 보여주기 전에
    # 게임이 끝나므로 Player 와 Creature 를 직접 배치한다 (전이 자체는 실제 판정).
    game.player.position = (8, 4)
    creature.position, creature.facing = (8, 9), "a"
    creature.state, creature.target, creature.path = PATROL, None, []
    game.tick_creature(0.5)
    note("5 발견 -> CHASE", "player=(8,4) creature=(8,9) 서향")

    for _ in range(3):
        game.tick_creature(0.5)
    note("6 CHASE 지속")

    game.player.position = (5, 1)             # 세로 통로로 꺾어 시야를 끊는다
    game.tick_creature(0.5)
    note("7 모퉁이 -> LOS 상실 -> SEARCH", "player=(5,1)")

    for _ in range(8):
        game.tick_creature(0.5)
    note("8 마지막 관측 위치 탐색")

    game.player.position = (8, 3)             # 다시 Creature 시야 안으로
    creature.position, creature.facing = (8, 6), "a"
    game.tick_creature(0.5)
    note("9 재발견 -> CHASE", "player=(8,3) creature=(8,6) 서향")

    for _ in range(40):
        game.tick_creature(0.5)
        if game.caught:
            break
    note("10 접촉 -> CAUGHT")

    header = (f"{'step':<30}{'setup':<34}{'state':<9}{'creature':<9}{'player':<9}"
              f"{'face':<6}{'visible':<9}{'last_seen':<10}{'mem':<6}"
              f"{'target':<9}{'path':<6}caught")
    lines = ["MAZE-13 Creature scenario log",
             "seed=4, map=experiments.SCENARIO_MAP (위치는 고정, 전이는 실제 FSM)", "",
             maze.as_text(), header, "-" * len(header)]
    for row in rows:
        lines.append(f"{row[0]:<30}{row[1]:<34}{row[2]:<9}{row[3]:<9}{row[4]:<9}"
                     f"{row[5]:<6}{row[6]:<9}{row[7]:<10}{row[8]:<6}"
                     f"{row[9]:<9}{row[10]:<6}{row[11]}")
    lines += ["", f"caught={game.caught}  over={game.over}  "
                  f"player={game.player.position}  creature={creature.position}",
              f"creature spawn 에서 도달 가능한 칸: "
              f"{len(grid_distances(maze, maze.creature_spawns[0]))}"]
    RESULTS.mkdir(exist_ok=True)
    path = RESULTS / "creature_scenario.txt"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n[D] Creature scenario -> {path}")
    print("\n".join(lines[4:]))
    return path


# --- E. Adaptive Escape Route ------------------------------------------------
#
# Trap 과 Creature 를 "지나가고 싶지 않은 칸" 으로 보고 현재 목표까지 안전한 길이
# 남아 있는지 검사한다. 막혀 있을 때만 내부 벽을 최소 개수로 연다.
# 아래 미로는 전부 결정적이다 (난수 없음).

# 완전한 고리. 한쪽이 막혀도 반대쪽으로 돌아갈 수 있어 벽을 열 필요가 없다.
LOOP_MAZE = """\
############
#S...T..G..#
#.########.#
#.########.#
#.########.#
#.########.#
#.########.#
#.........E#
############
"""

# 고리가 (4, 10) 한 칸에서 끊겨 있다. 그 벽을 열어야 우회로가 생긴다.
# T 를 지우면 Creature 만, G 를 지우면 Trap 만 막는 변형이 된다.
BROKEN_MAZE = """\
############
#S...T..G.E#
#.########.#
#.########.#
#.##########
#.########.#
#.########.#
#..........#
############
"""

# Key / Door / Exit 가 있는 미로. Creature spawn (3, 1) 이 세로 통로의 길목이고
# 반대편 우회로는 (3, 11) 한 칸에서 끊겨 있다.
DOOR_MAZE = """\
#############
#SK.........#
#.#########.#
#G###########
#.#########.#
#...........#
#####D#######
#####E#######
#############
"""

ROUTE_SCENARIOS = (
    # (이름, 미로, 열쇠 보유, 문을 연 상태인가)
    ("already_safe", LOOP_MAZE, False, False),
    ("creature_block", BROKEN_MAZE.replace("T", "."), False, False),
    ("trap_block", BROKEN_MAZE.replace("G", "."), False, False),
    ("creature_trap", BROKEN_MAZE, False, False),
    ("door_block", DOOR_MAZE, True, False),     # 문이 닫혀 있으니 목표는 Door
    ("exit_block", DOOR_MAZE, True, True),      # 문을 연 뒤라 목표는 Exit
)


def _route_case(name, text, has_key, doors_open):
    """시나리오 하나를 실제 route_guard 로 돌리고 결과를 모은다."""
    maze = parse_maze(text)
    opened_doors = set(maze.doors) if doors_open else set()
    goal = route_guard.current_goal(maze, opened_doors)

    creature = None
    if maze.creature_spawns:
        creature = Creature(position=maze.creature_spawns[0], rng=random.Random(0))
        creature.activate()
    blocked = route_guard.danger_cells(maze, creature)

    before = route_guard.safe_path(maze, maze.start, goal, has_key,
                                   opened_doors, (), blocked)
    opened: set = set()
    started = time.perf_counter()
    guard = route_guard.ensure_safe_route(maze, maze.start, has_key, opened_doors,
                                          opened, creature, goal)
    elapsed = (time.perf_counter() - started) * 1000
    after = route_guard.safe_path(maze, maze.start, goal, has_key,
                                  opened_doors, opened, blocked)
    return [name,
            "DOOR" if goal in maze.doors else "EXIT",
            before is not None,
            guard.status,
            len(opened),
            " ".join(str(w) for w in sorted(opened)) or "-",
            after is not None,
            route_guard.keeps_door_required(maze, opened, opened_doors),
            f"{elapsed:.3f}"]


def route_performance(repeats=800):
    """already_safe 와 wall_search 비용을 나눠 잰다.

    반복마다 opened_walls 를 새로 만든다. 그러지 않으면 첫 실행에서 벽이 열린 뒤
    두 번째부터는 already_safe 가 되어 측정이 무의미해진다.
    """
    cases = []
    for name, text in (("already_safe", LOOP_MAZE), ("wall_search", BROKEN_MAZE)):
        maze = parse_maze(text)                 # Maze 는 불변이라 재사용해도 된다
        goal = route_guard.current_goal(maze)
        creature = Creature(position=maze.creature_spawns[0], rng=random.Random(0))
        creature.activate()

        samples = []
        for _ in range(repeats):
            fresh = set()                       # 매번 깨끗한 runtime 상태
            started = time.perf_counter()
            route_guard.ensure_safe_route(maze, maze.start, False, (),
                                          fresh, creature, goal)
            samples.append((time.perf_counter() - started) * 1000)
        cases.append([name, repeats, f"{sum(samples) / len(samples):.4f}",
                      f"{min(samples):.4f}", f"{max(samples):.4f}"])
    return cases


def experiment_adaptive_route():
    rows = [_route_case(*scenario) for scenario in ROUTE_SCENARIOS]
    path = write_csv("adaptive_route.csv",
                     ["scenario", "goal", "safe_before", "status", "opened_count",
                      "opened_walls", "safe_after", "door_required_preserved",
                      "elapsed_ms"], rows)
    print("\n[E] Adaptive Escape Route")
    show(["scenario", "goal", "before", "status", "opened", "walls",
          "after", "door_ok", "ms"], rows)

    perf = route_performance()
    perf_path = write_csv("adaptive_route_performance.csv",
                          ["case", "repeats", "avg_ms", "min_ms", "max_ms"], perf)
    print("\n[E] Route Guard 비용 (반복마다 opened_walls 초기화)")
    show(["case", "repeats", "avg_ms", "min_ms", "max_ms"], perf)
    return path, perf_path, route_smoke()


def route_smoke() -> Path:
    """기본 맵에서의 Route Guard 동작 + 열린 벽 일관성 + Exit/Creature 회귀."""
    from ai.perception import has_line_of_sight
    from maze.model import blocks
    from renderer.game_view import result_text
    from renderer.raycaster import blocks_ray

    lines = ["MAZE-13 Adaptive Escape Route smoke", "",
             "[1] 기본 맵의 대표 Creature 위치",
             f"  {'map':<12}{'creature':<10}{'goal':<10}{'before':<8}"
             f"{'status':<14}{'opened':<8}after",
             "  " + "-" * 70]
    for name in BASE_MAPS:
        maze = load_maze(f"maps/{name}")
        route = bfs(maze).path
        spots = [maze.creature_spawns[0], route[len(route) // 3],
                 route[len(route) * 2 // 3], route[-2]]
        for spot in spots:
            game = Game(load_maze(f"maps/{name}"), map_name=name, play_mode=HORROR)
            creature = game.attach_creature(random.Random(1))
            creature.activate()
            creature.position = spot
            goal = game.current_goal
            blocked = route_guard.danger_cells(game.maze, creature)
            before = route_guard.safe_path(game.maze, game.player.position, goal,
                                           game.player.has_key, game.opened_doors,
                                           (), blocked) is not None
            game.guard_route()
            after = route_guard.safe_path(game.maze, game.player.position, goal,
                                          game.player.has_key, game.opened_doors,
                                          game.opened_walls, blocked) is not None
            lines.append(f"  {name:<12}{str(spot):<10}{str(goal):<10}"
                         f"{str(before):<8}{game.route_status:<14}"
                         f"{len(game.opened_walls):<8}{after}")

    lines += ["", "[2] 열린 벽 일관성 (이동 / Creature 경로 / Ray / 시야)"]
    maze = load_maze("maps/maze01.txt")
    wall = route_guard.candidate_walls(maze)[0]
    game = Game(load_maze("maps/maze01.txt"), map_name="maze01.txt")
    game.opened_walls.add(wall)
    above, below = (wall[0] - 1, wall[1]), (wall[0] + 1, wall[1])
    checks = {
        "원본 타일이 여전히 '#'": maze.tile(wall) == "#",
        "model.blocks 닫힘/열림": blocks(maze, wall) and not blocks(maze, wall, (), {wall}),
        "Player 통과": game.is_passable(wall),
        "Creature 경로 사용": (grid_astar(maze, above, wall).path is None
                           and grid_astar(maze, above, wall,
                                          opened_walls={wall}).path is not None),
        "Ray 통과": blocks_ray(maze, wall) and not blocks_ray(maze, wall, (), {wall}),
        "시야 통과": (not has_line_of_sight(above, below, maze)
                  and has_line_of_sight(above, below, maze, (), {wall})),
    }
    for label, ok in checks.items():
        lines.append(f"  {'PASS' if ok else 'FAIL'}  {label}")
    lines.append(f"  opened wall consistency = "
                 f"{'PASS' if all(checks.values()) else 'FAIL'}   (wall={wall})")

    lines += ["", "[3] Exit + Creature 회귀 (조사 당시 실제로 났던 버그 상황)"]
    game = Game(load_maze("maps/maze01.txt"), map_name="maze01.txt", play_mode=HORROR)
    game.attach_creature(random.Random(1))
    game.creature.activate()
    game.creature.position = game.maze.exit
    keys = moves_for(bfs(game.maze).path)
    for key in keys[:-1]:
        game.move(key)
        game.creature.position = game.maze.exit
    game.move(keys[-1])
    first = result_text(game).splitlines()[0]
    lines += [f"  player={game.player.position}  creature={game.creature.position}  "
              f"exit={game.maze.exit}",
              f"  cleared={game.cleared}  caught={game.caught}",
              f"  result = {first}",
              f"  기대값 ENTITY CONTACT 와 일치: {first == 'ENTITY CONTACT'}"]

    RESULTS.mkdir(exist_ok=True)
    path = RESULTS / "adaptive_route_smoke.txt"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n[E] Route smoke -> {path}")
    print("\n".join(lines))
    return path


EXPERIMENTS = {"a": experiment_pathfinding, "b": experiment_generator,
               "c": experiment_rendering, "d": experiment_creature,
               "e": experiment_adaptive_route}


# --- 보고서용 요약 -----------------------------------------------------------

def _read_csv(name):
    path = RESULTS / name
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _find_line(name, needle, default="(없음)"):
    path = RESULTS / name
    if not path.exists():
        return default
    for line in path.read_text(encoding="utf-8").splitlines():
        if needle in line:
            return line.strip()
    return default


def _test_result():
    """보고서에 적을 테스트 수와 성공 여부.

    같은 프로세스에서 discover 하면 experiments 가 이미 올려 둔 모듈 상태와 섞여
    결과가 달라진다. 사용자가 실제로 치는 명령 그대로 별도 프로세스에서 돌린다.
    """
    import re
    import subprocess

    done = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests"],
                          capture_output=True, text=True)
    output = done.stdout + done.stderr
    found = re.search(r"Ran (\d+) tests?", output)
    return (int(found.group(1)) if found else 0), done.returncode == 0


def write_report_summary() -> Path:
    """results/ 에 있는 결과를 보고서에 옮기기 좋은 형태로 한 장에 모은다."""
    out = ["MAZE-13 실험 요약", "=" * 60, ""]

    rows = _read_csv("pathfinding.csv")
    out.append("[Pathfinding]  BFS / DFS / A*")
    if rows:
        out.append(f"  {'map':<12}{'algo':<7}{'moves':>7}{'visited':>9}{'avg_ms':>9}")
        for row in rows:
            out.append(f"  {row['map']:<12}{row['algorithm']:<7}{row['moves']:>7}"
                       f"{row['visited_states']:>9}{float(row['avg_ms']):>9.3f}")
        for name in sorted({row["map"] for row in rows}):
            group = {row["algorithm"]: row for row in rows if row["map"] == name}
            same = group["bfs"]["moves"] == group["astar"]["moves"]
            out.append(f"  - {name}: BFS 와 A* 최단 이동 동일 {same} "
                       f"({group['bfs']['moves']}), DFS {group['dfs']['moves']}, "
                       f"방문 상태 BFS {group['bfs']['visited_states']} vs "
                       f"A* {group['astar']['visited_states']}")
    out.append("")

    rows = _read_csv("generator.csv")
    out.append("[Generator]  Randomized DFS + Braiding")
    if rows:
        specials = [row for row in rows if row["specials"] == "True"]
        plain = [row for row in rows if row["specials"] == "False"]
        for label, group in (("specials=True ", specials), ("specials=False", plain)):
            made = sum(int(row["generated"]) for row in group)
            tried = sum(int(row["attempts"]) for row in group)
            valid = sum(int(row["validated"]) for row in group)
            safe = sum(int(row["trap_safe"]) for row in group)
            out.append(f"  {label}: 성공 {made}/{tried} ({made / tried * 100:.1f}%), "
                       f"검증 통과 {valid}, Trap-safe {safe}")
        out.append("  크기별 성공률:")
        for size in sorted({row["size"] for row in rows}):
            group = [row for row in rows if row["size"] == size]
            made = sum(int(row["generated"]) for row in group)
            tried = sum(int(row["attempts"]) for row in group)
            worst = max(float(row["avg_ms"]) for row in group)
            out.append(f"    {size:<8} {made}/{tried} ({made / tried * 100:.1f}%)  "
                       f"최대 평균 생성시간 {worst:.1f} ms")
        bad = [row for row in specials
               if int(row["trap_safe"]) != int(row["generated"])]
        out.append(f"  Trap-safe 검증 실패 조합: {len(bad)}개"
                   f"{'' if not bad else ' -> ' + str([row['size'] for row in bad])}")
    out.append("")

    rows = _read_csv("rendering.csv")
    out.append("[Raycasting]")
    if rows:
        times = [float(row["avg_ms_per_frame"]) for row in rows]
        out.append(f"  프레임 계산 시간 {min(times):.2f} ~ {max(times):.2f} ms "
                   f"(셀 수 {min(int(r['cells']) for r in rows)} ~ "
                   f"{max(int(r['cells']) for r in rows)})")
        out.append("  * estimated_fps 는 off-screen 계산량 환산값이며 실제 화면 주사율이 아니다.")
    out.append("")

    rows = _read_csv("creature_update.csv")
    out.append("[Creature]")
    for row in rows:
        out.append(f"  {row['state']:<9} update 평균 "
                   f"{float(row['avg_ms_per_update']) * 1000:.2f} us "
                   f"({row['repeats']}회)")
    out.append(f"  FSM 시나리오: {_find_line('creature_scenario.txt', 'caught=')}")
    out.append("")

    rows = _read_csv("adaptive_route.csv")
    out.append("[Adaptive Escape Route]")
    if rows:
        blocked = [row for row in rows if row["safe_before"] == "False"]
        recovered = [row for row in blocked if row["safe_after"] == "True"]
        opened = [int(row["opened_count"]) for row in rows]
        safe_rows = [row for row in rows if row["safe_before"] == "True"]
        out.append(f"  시나리오 {len(rows)}개 (already_safe {len(safe_rows)}, "
                   f"막힘 {len(blocked)})")
        out.append(f"  already_safe 에서 연 벽: "
                   f"{sum(int(row['opened_count']) for row in safe_rows)}개")
        out.append(f"  막힌 시나리오 복구: {len(recovered)}/{len(blocked)}")
        out.append(f"  연 벽 평균 {sum(opened) / len(opened):.2f}개, 최대 {max(opened)}개")
        out.append(f"  Door 필수 조건 유지: "
                   f"{all(row['door_required_preserved'] == 'True' for row in rows)}")
    for row in _read_csv("adaptive_route_performance.csv"):
        out.append(f"  {row['case']:<13} 평균 {float(row['avg_ms']):.3f} ms "
                   f"({row['repeats']}회, {row['min_ms']} ~ {row['max_ms']})")
    out.append(f"  {_find_line('adaptive_route_smoke.txt', 'opened wall consistency')}")
    out.append(f"  Exit+Creature 회귀: "
               f"{_find_line('adaptive_route_smoke.txt', 'result = ')}")
    out.append("")

    count, ok = _test_result()
    out.append("[Tests]")
    out.append(f"  {count} tests  {'PASS' if ok else 'FAIL'}")
    out.append("")
    out.append("주의: 위 수치는 구성한 검증 시나리오와 측정 조건에서의 결과이며,")
    out.append("      모든 미로에 대한 보장을 뜻하지 않는다.")

    RESULTS.mkdir(exist_ok=True)
    path = RESULTS / "report_summary.txt"
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"\n[요약] -> {path}")
    print("\n".join(out))
    return path


def main(argv) -> int:
    chosen = [key for key in (argv or EXPERIMENTS) if key in EXPERIMENTS]
    if not chosen:
        print(f"사용법: python experiments.py [{' '.join(EXPERIMENTS)}]")
        return 1
    written = []
    for key in chosen:
        result = EXPERIMENTS[key]()
        written += list(result) if isinstance(result, tuple) else [result]
    written.append(write_report_summary())   # results/ 에 있는 결과를 한 장으로 모은다
    print("\n생성된 파일:")
    for path in written:
        print("  ", path)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
