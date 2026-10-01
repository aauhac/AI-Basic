"""MAZE-13 진입점.

    python app.py                     Tkinter 메인 메뉴
    python app.py --info [맵경로]      검증 + BFS/DFS/A* 결과만 출력 (개발용 CLI)
    python app.py --bench [프레임수]    맵 크기별 평균 frame time 측정 (창 없이)
"""

import sys
import time

from ai.pathfinding import ALGORITHMS
from maze.loader import load_maze
from maze.validator import validate

DEFAULT_MAP = "maps/maze01.txt"


def report(path: str = DEFAULT_MAP) -> int:
    maze = load_maze(path)
    print(maze.as_text(), end="")
    print(f"\n[{path}]  {maze.width} x {maze.height}")
    print(f"S={maze.start}  E={maze.exit}  K={maze.keys}  D={maze.doors}  "
          f"T={maze.traps}  G={maze.creature_spawns}")

    errors = validate(maze)
    if errors:
        print("\nVALIDATION: FAIL")
        for message in errors:
            print("  -", message)
        return 1
    print("\nVALIDATION: PASS")

    print(f"\n{'ALGO':<8}{'MOVES':>8}{'VISITED':>10}{'TIME(ms)':>10}")
    for name, algorithm in ALGORITHMS.items():
        started = time.perf_counter()
        result = algorithm(maze)
        elapsed = (time.perf_counter() - started) * 1000
        moves = len(result.path) - 1 if result.path else -1
        print(f"{name:<8}{moves:>8}{result.visited:>10}{elapsed:>10.2f}")
    return 0


def bench(frames: str | int = 120) -> int:
    """창을 만들지 않고 render_frame 만 반복해서 맵 크기 민감도를 본다."""
    import math
    import pygame

    from maze.generator import generate
    from renderer.game_view import INTERNAL_SIZE, background, render_frame
    from renderer.raycaster import Camera

    frames = int(frames)
    pygame.init()
    surface = pygame.Surface(INTERNAL_SIZE)
    sky = background(INTERNAL_SIZE)

    targets = [(f"maps/maze0{n}.txt", load_maze(f"maps/maze0{n}.txt")) for n in (1, 2, 3)]
    targets += [(f"random {w}x{h}", generate(w, h, seed=7, loop_ratio=0.1, specials=True))
                for w, h in ((11, 11), (21, 15), (31, 21))]

    print(f"internal {INTERNAL_SIZE[0]}x{INTERNAL_SIZE[1]}, {frames} frames each")
    print()
    print(f"{'MAP':<20}{'SIZE':>9}{'CELLS':>8}{'ms/frame':>10}{'FPS':>8}")
    for label, maze in targets:
        row, col = maze.start
        camera = Camera(row + 0.5, col + 0.5)
        started = time.perf_counter()
        for frame in range(frames):
            camera.angle = frame * math.tau / frames  # 한 바퀴 돌며 측정
            render_frame(surface, maze, camera, (), sky)
        per_frame = (time.perf_counter() - started) * 1000 / frames
        print(f"{label:<20}{f'{maze.width}x{maze.height}':>9}"
              f"{maze.width * maze.height:>8}{per_frame:>10.2f}{1000 / per_frame:>8.0f}")

    print()
    print(f"{'CREATURE STATE':<20}{'ms/frame':>10}{'FPS':>8}   (maze03, 렌더 + AI)")
    for label, setup in _creature_cases():
        maze, game, camera = setup()
        started = time.perf_counter()
        for frame in range(frames):
            camera.angle = frame * math.tau / frames
            game.tick_creature(1 / 60)
            render_frame(surface, maze, camera, game.opened_doors, sky)
        per_frame = (time.perf_counter() - started) * 1000 / frames
        print(f"{label:<20}{per_frame:>10.2f}{1000 / per_frame:>8.0f}")
    pygame.quit()
    return 0


def _creature_cases():
    """inactive / patrol / chase 세 상태에서 프레임 비용을 비교한다."""
    import random

    from ai.creature import CHASE
    from game.engine import HORROR, Game
    from renderer.raycaster import Camera

    def build(activate, state=None):
        def setup():
            maze = load_maze("maps/maze03.txt")
            game = Game(maze, map_name="maze03.txt", play_mode=HORROR)
            creature = game.attach_creature(random.Random(1))
            if activate:
                creature.activate()
            if state:
                creature.state = state
                creature.target = game.player.position
            row, col = game.player.position
            return maze, game, Camera(row + 0.5, col + 0.5)
        return setup

    return [("inactive (dormant)", build(False)),
            ("patrol", build(True)),
            ("chase", build(True, CHASE))]


def main(argv) -> int:
    if argv and argv[0] == "--info":
        return report(*argv[1:2])
    if argv and argv[0] == "--bench":
        return bench(*argv[1:2])
    from ui.main_window import MainWindow

    MainWindow().mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
