"""Tkinter Canvas 기반 미로 편집기 화면. 저장 전 검증은 기존 validator 를 그대로 쓴다.

창을 따로 띄우지 않고 MainWindow 안에 끼워지는 Frame 이다.
"""

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox

from maze.loader import load_maze, save_maze
from maze.model import CREATURE, EXIT, FLOOR, MIN_SIZE, START, WALL, Maze
from maze.validator import unreachable_cells, validate
from ui import preview

DEFAULT_SIZE = 15


def blank_grid(width=DEFAULT_SIZE, height=DEFAULT_SIZE) -> list[list[str]]:
    """외곽만 벽인 빈 격자."""
    return [
        [WALL if row in (0, height - 1) or col in (0, width - 1) else FLOOR
         for col in range(width)]
        for row in range(height)
    ]


def grid_to_maze(grid) -> Maze:
    return Maze(tuple("".join(row) for row in grid))


class EditorScreen(tk.Frame):
    TITLE = "MAP EDITOR"

    def __init__(self, parent, app):
        super().__init__(parent, bg=preview.BG)
        self.app = app
        self.on_play = app.start_game
        self.grid_data = blank_grid()
        self.brush = WALL
        self.cell = 0
        self.alerts: list[tuple[int, int]] = []

        left = tk.Frame(self, bg=preview.BG)
        left.pack(side="left", fill="y", padx=10, pady=10)
        tk.Label(left, text="SELECT TILE", bg=preview.BG, fg=preview.FG,
                 font=preview.FONT).pack(anchor="w", pady=(0, 6))
        self.brush_buttons = {}
        for tile in preview.PALETTE:
            button = tk.Button(
                left, text=f" {tile}  {preview.TILE_NAMES[tile]}", anchor="w", width=16,
                bg=preview.TILE_COLORS[tile], fg=preview.FG, font=preview.FONT,
                relief="flat", command=lambda t=tile: self.set_brush(t))
            button.pack(fill="x", pady=1)
            self.brush_buttons[tile] = button
        self.set_brush(WALL)

        for label, command in (("VALIDATE", self.validate_now), ("SAVE TXT", self.save),
                               ("LOAD TXT", self.load), ("CLEAR", self.clear)):
            tk.Button(left, text=label, width=16, bg=preview.PANEL, fg=preview.FG,
                      font=preview.FONT, relief="flat", command=command).pack(fill="x", pady=(8, 0))

        self.size_label = tk.Label(left, text="", bg=preview.BG, fg=preview.DIM,
                                   font=preview.FONT)
        self.size_label.pack(anchor="w", pady=(10, 0))

        right = tk.Frame(self, bg=preview.BG)
        right.pack(side="left", fill="both", expand=True, padx=(0, 10), pady=10)
        self.canvas = tk.Canvas(right, bg=preview.BG, highlightthickness=0)
        self.canvas.pack()
        self.canvas.bind("<Button-1>", self.paint)
        self.canvas.bind("<B1-Motion>", self.paint)

        self.message = tk.Text(right, height=9, bg=preview.PANEL, fg=preview.FG,
                               font=preview.FONT, relief="flat", wrap="word")
        self.message.pack(fill="both", expand=True, pady=(10, 0))
        self.redraw()

    # ---- 편집 -------------------------------------------------------------

    def set_brush(self, tile) -> None:
        for other, button in self.brush_buttons.items():
            button.configure(relief="sunken" if other == tile else "flat")
        self.brush = tile

    def paint(self, event) -> None:
        if not self.cell:
            return
        row, col = event.y // self.cell, event.x // self.cell
        if not (0 <= row < len(self.grid_data) and 0 <= col < len(self.grid_data[0])):
            return
        if self.grid_data[row][col] == self.brush:
            return
        self.alerts = []
        # S / E / G 는 하나만 남긴다. 편집 중 중복을 아예 못 만들게 하는 편이 쓰기 쉽다.
        if self.brush in (START, EXIT, CREATURE):
            for r, line in enumerate(self.grid_data):
                for c, tile in enumerate(line):
                    if tile == self.brush:
                        self.grid_data[r][c] = FLOOR
        self.grid_data[row][col] = self.brush
        self.redraw()

    def clear(self) -> None:
        height, width = len(self.grid_data), len(self.grid_data[0])
        self.grid_data = blank_grid(width, height)
        self.alerts = []
        self.say("빈 미로로 초기화했습니다.")
        self.redraw()

    def redraw(self) -> None:
        maze = grid_to_maze(self.grid_data)
        self.cell = preview.draw(self.canvas, maze, alerts=self.alerts)
        self.size_label.configure(text=f"{maze.width} x {maze.height}  (최소 {MIN_SIZE})")

    def say(self, text) -> None:
        self.message.delete("1.0", "end")
        self.message.insert("1.0", text)

    # ---- 검증 / 파일 ------------------------------------------------------

    def validate_now(self) -> list[str]:
        maze = grid_to_maze(self.grid_data)
        errors = validate(maze)
        self.alerts = unreachable_cells(maze) if maze.start else []
        self.redraw()
        if errors:
            self.say("VALIDATION: FAIL\n" + "\n".join(f"  - {e}" for e in errors))
        else:
            self.say("VALIDATION: PASS\n  이 미로는 실제로 클리어할 수 있습니다.")
        return errors

    def save(self) -> None:
        if self.validate_now():
            messagebox.showwarning("MAZE EDITOR", "검증을 통과하지 못해 저장할 수 없습니다.",
                                   parent=self.app)
            return
        path = filedialog.asksaveasfilename(
            parent=self.app, title="미로 저장", initialdir="maps",
            defaultextension=".txt",
            filetypes=[("Maze TXT", "*.txt")])
        if not path:
            return
        save_maze(grid_to_maze(self.grid_data), path)
        self.say(f"{path} 저장 완료.")
        if self.on_play and messagebox.askyesno(
                "MAZE EDITOR",
                "미로가 저장되었습니다.\n지금 플레이하시겠습니까?", parent=self.app):
            # 메모리의 격자가 아니라 방금 저장한 TXT 를 다시 읽는다.
            self.on_play(Path(path))

    def load(self) -> None:
        path = filedialog.askopenfilename(parent=self.app, title="미로 열기", initialdir="maps",
                                          filetypes=[("Maze TXT", "*.txt")])
        if not path:
            return
        try:
            maze = load_maze(path)
        except (OSError, ValueError) as error:
            messagebox.showerror("MAZE EDITOR", str(error), parent=self.app)
            return
        self.grid_data = [list(line.ljust(maze.width, WALL)) for line in maze.grid]
        self.redraw()
        self.validate_now()
