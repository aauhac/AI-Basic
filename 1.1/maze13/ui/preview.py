"""2D 미로를 Tkinter Canvas 에 그린다. 팔레트도 여기서 관리한다.

낡은 시설 제어 단말 느낌의 어두운 녹색 계열. 3D 렌더러와는 무관한 관리/개발용 화면이다.
"""

from maze.model import (CREATURE, DOOR, EXIT, FLOOR, KEY, PLAYER_TILE,
                        START, TRAP, WALL)

BG = "#0a0d0a"
FG = "#8cff8c"
DIM = "#3f5f3f"
PANEL = "#101610"
ALERT = "#ff6b5c"
FONT = ("Consolas", 10)
TITLE_FONT = ("Consolas", 18, "bold")

TILE_COLORS = {
    WALL: "#18291c",
    FLOOR: "#0d140d",
    START: "#1d4a6b",
    EXIT: "#1f7a2e",
    KEY: "#7a7020",
    DOOR: "#7a4420",
    TRAP: "#7a2020",
    CREATURE: "#4d2070",
}
TILE_NAMES = {
    WALL: "Wall", FLOOR: "Floor", START: "Start", EXIT: "Exit",
    KEY: "Key", DOOR: "Door", TRAP: "Trap", CREATURE: "Creature",
}
PALETTE = (WALL, FLOOR, START, EXIT, KEY, DOOR, TRAP, CREATURE)

VISITED = "#2b4f7a"
PLAYER = "#f2ff5c"
OPENED = "#3a5f28"
ALERT_OUTLINE = "#ff5a4a"
SEARCH_PATH = "#2f7d9e"
PLAYER_TEXT = "#101410"


def cell_size(maze, max_width=780, max_height=560, largest=34) -> int:
    return max(6, min(largest, max_width // maze.width, max_height // maze.height))


def draw(canvas, maze, cell: int | None = None, visited=(), player=None,
         opened_doors=(), alerts=(), path=()) -> int:
    """미로를 다시 그리고 사용한 cell 크기를 돌려준다."""
    cell = cell or cell_size(maze)
    canvas.delete("all")
    canvas.configure(width=maze.width * cell, height=maze.height * cell, bg=BG)
    opened_doors = set(opened_doors)

    for row in range(maze.height):
        for col in range(maze.width):
            tile = maze.tile((row, col))
            fill = OPENED if (row, col) in opened_doors and tile == DOOR \
                else TILE_COLORS.get(tile, TILE_COLORS[FLOOR])
            canvas.create_rectangle(col * cell, row * cell,
                                    (col + 1) * cell, (row + 1) * cell,
                                    fill=fill, outline=BG)
            if tile not in (WALL, FLOOR) and cell >= 12:
                canvas.create_text(col * cell + cell / 2, row * cell + cell / 2,
                                   text=tile, fill=FG, font=("Consolas", max(7, cell // 2)))

    for row, col in path:  # BFS / DFS / A* 가 찾은 경로
        canvas.create_rectangle(col * cell + 2, row * cell + 2,
                                (col + 1) * cell - 2, (row + 1) * cell - 2,
                                fill=SEARCH_PATH, outline="")

    inset = max(1, cell // 3)
    for row, col in visited:
        canvas.create_rectangle(col * cell + inset, row * cell + inset,
                                (col + 1) * cell - inset, (row + 1) * cell - inset,
                                fill=VISITED, outline="")
    for row, col in alerts:  # 접근 불가 칸을 붉은 테두리로 표시
        canvas.create_rectangle(col * cell + 1, row * cell + 1,
                                (col + 1) * cell - 1, (row + 1) * cell - 1,
                                outline=ALERT_OUTLINE, width=2)
    if player is not None:
        # 과제 기호 그대로 현재 위치는 P. 원본 TXT 에는 쓰지 않고 화면에만 그린다.
        row, col = player
        pad = max(1, cell // 6)
        canvas.create_oval(col * cell + pad, row * cell + pad,
                           (col + 1) * cell - pad, (row + 1) * cell - pad,
                           fill=PLAYER, outline="")
        canvas.create_text(col * cell + cell / 2, row * cell + cell / 2,
                           text=PLAYER_TILE, fill=PLAYER_TEXT,
                           font=("Consolas", max(7, cell // 2), "bold"))
    return cell
