"""보고서용 실험 러너. 게임 기능이 아니라 측정 전용 스크립트다.

    python experiments.py            전부 실행
    python experiments.py a c        일부만 (a=pathfinding, b=generator,
                                     c=rendering, d=creature)

결과는 results/ 아래 CSV 와 로그로 저장한다.
"""

import csv
import random
import sys
import time
from pathlib import Path

from ai.creature import CHASE, DORMANT, PATROL, Creature
from ai.pathfinding import ALGORITHMS, bfs, grid_distances
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
                made = valid = 0
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
                rows.append([f"{width}x{height}", loop_ratio, specials, seeds, made, valid,
                             f"{total_ms / max(made, 1):.2f}",
                             f"{total_moves / max(made, 1):.1f}",
                             f"{total_cells / max(made, 1):.1f}"])
    path = write_csv("generator.csv",
                     ["size", "loop_ratio", "specials", "attempts", "generated",
                      "validated", "avg_ms", "avg_bfs_moves", "avg_walkable_cells"], rows)
    print(f"\n[B] Random Maze Generator  (조합당 seed {seeds}개)")
    show(["size", "loop", "spec", "gen", "valid", "avg_ms", "bfs", "cells"],
         [[r[0], r[1], r[2], r[4], r[5], r[6], r[7], r[8]] for r in rows])
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
    for label, state in ((DORMANT, None), (PATROL, PATROL), (CHASE, CHASE)):
        creature = Creature(position=(8, 1), rng=random.Random(1))
        if state:
            creature.activate()
            creature.state = state
            creature.target = (1, 1) if state == CHASE else None
        seen = Observation(True, (1, 1)) if state == CHASE else Observation(False, None)
        ms = timed(lambda c=creature, o=seen: c.update(o, maze, (), 1 / 60), repeats)
        rows.append([label, f"{ms:.5f}", repeats])
    path = write_csv("creature_update.csv",
                     ["state", "avg_ms_per_update", "repeats"], rows)
    print(f"\n[D] Creature update  (각 {repeats}회 평균)")
    show(["state", "avg_ms", "repeats"], rows)
    return path, scenario_log()


def scenario_log() -> Path:
    """FSM 전이를 순서대로 기록한다. 난수 seed 고정이라 재현 가능하다."""
    maze = parse_maze(SCENARIO_MAP)
    game = Game(maze, map_name="scenario.txt", play_mode=HORROR)
    creature = game.attach_creature(random.Random(4))
    lines = ["MAZE-13 Creature scenario log",
             "seed=4, map=experiments.SCENARIO_MAP", "",
             maze.as_text(),
             f"{'step':<34}{'state':<9}{'pos':<9}{'face':<6}"
             f"{'visible':<9}{'last_seen':<10}{'memory':<8}caught",
             "-" * 92]

    def note(step):
        observation = observe(creature.position, creature.facing,
                              game.player.position, game.maze, game.opened_doors)
        lines.append(f"{step:<34}{creature.state:<9}{str(creature.position):<9}"
                     f"{creature.facing:<6}{str(observation.visible):<9}"
                     f"{str(creature.last_seen_position):<10}"
                     f"{creature.memory_remaining:<8.1f}{game.caught}")

    note("1 start")
    for _ in range(8):
        game.tick_creature(0.5)
    note("2 dormant holds")

    for _ in range(11):
        game.move("d")
        game.tick_creature(0.5)
    note("3 key taken -> activated")

    for _ in range(4):
        game.tick_creature(0.5)
    note("4 patrol")

    # 자리를 잡는 동안에는 Creature 를 멀리 치워 둔다. 지금은 이동 중에도 접촉하면
    # 바로 잡히기 때문에, 보여 주려는 FSM 전이 전에 게임이 끝나 버린다.
    creature.position = (1, 12)
    for _ in range(11):
        game.move("a")
    for _ in range(7):
        game.move("s")
    for _ in range(3):
        game.move("d")
    creature.position, creature.facing = (8, 9), "a"
    creature.state, creature.target, creature.path = PATROL, None, []
    game.tick_creature(0.5)
    note("5 spotted -> chase")

    for _ in range(3):
        game.tick_creature(0.5)
    note("6 chasing")

    for _ in range(4):
        game.move("a")
    for _ in range(5):
        game.move("w")
    game.tick_creature(0.5)
    note("7 corner -> lost sight -> search")

    for _ in range(8):
        game.tick_creature(0.5)
    note("8 walked to last seen cell")

    for _ in range(5):
        game.move("s")
    game.tick_creature(0.5)
    note("9 re-spotted -> chase")

    for _ in range(40):
        game.tick_creature(0.5)
        if game.caught:
            break
    note("10 contact")

    lines += ["", f"caught={game.caught}  over={game.over}  "
                  f"player={game.player.position}  creature={creature.position}",
              f"reachable cells from creature spawn: "
              f"{len(grid_distances(maze, maze.creature_spawns[0]))}"]
    RESULTS.mkdir(exist_ok=True)
    path = RESULTS / "creature_scenario.txt"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n[D] Creature scenario -> {path}")
    print("\n".join(lines[4:]))
    return path


EXPERIMENTS = {"a": experiment_pathfinding, "b": experiment_generator,
               "c": experiment_rendering, "d": experiment_creature}


def main(argv) -> int:
    chosen = [key for key in (argv or EXPERIMENTS) if key in EXPERIMENTS]
    if not chosen:
        print(f"사용법: python experiments.py [{' '.join(EXPERIMENTS)}]")
        return 1
    written = []
    for key in chosen:
        result = EXPERIMENTS[key]()
        written += list(result) if isinstance(result, tuple) else [result]
    print("\n생성된 파일:")
    for path in written:
        print("  ", path)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
