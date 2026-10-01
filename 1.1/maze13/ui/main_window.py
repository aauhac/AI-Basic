"""Tkinter 단일 창 UI.

창을 여러 개 띄우지 않는다. MainWindow 하나에 머리글 + 화면 영역이 있고,
각 화면은 Toplevel 이 아니라 Frame 이라 MainWindow.show() 로 갈아 끼운다.

CLASSIC 2D 가 과제 기본 모드(W/A/S/D = 상/좌/하/우, P 표시, AUTO SOLVE)이고
3D HORROR 가 확장 모드(Raycasting + Creature)다. 두 모드 모두 같은 Game 규칙을 쓴다.
3D 만 pygame 창이 따로 뜨며, MainWindow._run_3d() 한 곳에서만 실행한다.
"""

import tkinter as tk
from pathlib import Path
from tkinter import messagebox

from ai.pathfinding import ALGORITHMS, moves_for
from game import records, save_manager
from game.engine import CLASSIC, EVENT_TEXT, HORROR, WARN_EVENTS, Game
from maze.generator import generate
from maze.loader import load_maze, save_maze
from maze.validator import validate
from ui import preview
from ui.editor import EditorScreen

MAPS_DIR = Path("maps")
AUTO_STEP_MS = 140          # AUTO SOLVE 한 칸 간격


def button(parent, text, command, width=22):
    return tk.Button(parent, text=text, width=width, command=command,
                     bg=preview.PANEL, fg=preview.FG, font=preview.FONT,
                     relief="flat", activebackground=preview.DIM,
                     activeforeground=preview.BG)


def text_panel(parent, height=10):
    widget = tk.Text(parent, height=height, bg=preview.PANEL, fg=preview.FG,
                     font=preview.FONT, relief="flat", wrap="word")
    widget.pack(fill="both", expand=True)
    return widget


def format_records(data: dict) -> str:
    """기록 표 + 최근 플레이. GUI 없이 테스트할 수 있게 순수 함수로 둔다."""
    if not data:
        return "기록이 없습니다."
    lines = [f"{'MAP':<22}{'BEST MOVES':>12}{'BEST TIME':>12}{'PLAYS':>8}", "-" * 54]
    for name, entry in sorted(data.items()):
        best_time = entry.get("best_time")
        shown_time = "-" if best_time is None else f"{best_time:.2f}"
        plays = len(records.history_of(entry))
        lines.append(f"{name:<22}{entry.get('best_moves', '-'):>12}"
                     f"{shown_time:>12}{plays:>8}")

    for name, entry in sorted(data.items()):
        history = records.history_of(entry)
        if not history:
            continue
        lines += ["", f"[{name}]  최근 플레이",
                  f"  {'#':>3}{'MOVES':>8}{'TIME':>10}{'MODE':>10}"]
        start = len(history) - len(history[-8:]) + 1
        for index, play in enumerate(history[-8:], start=start):
            lines.append(f"  {index:>3}{play.get('moves', '-'):>8}"
                         f"{play.get('time', 0):>10.2f}{play.get('mode', '-'):>10}")
    return "\n".join(lines)


def describe_maze(maze, name: str, record=None) -> str:
    """검증 결과 + 경로 탐색 요약. 역시 GUI 와 분리해 둔다."""
    lines = [f"{name}   {maze.width} x {maze.height}",
             f"S={maze.start}  E={maze.exit}  K={maze.keys}",
             f"D={maze.doors}  T={maze.traps}  G={maze.creature_spawns}", ""]
    errors = validate(maze)
    if errors:
        lines.append("VALIDATION: FAIL")
        lines += [f"  - {error}" for error in errors]
        return "\n".join(lines)

    lines += ["VALIDATION: PASS", "", f"{'ALGO':<8}{'MOVES':>8}{'VISITED':>10}"]
    for algo_name, algorithm in ALGORITHMS.items():
        result = algorithm(maze)
        moves = len(result.path) - 1 if result.path else -1
        lines.append(f"{algo_name:<8}{moves:>8}{result.visited:>10}")
    if record:
        lines += ["", f"BEST MOVES {record.get('best_moves', '-')}   "
                      f"BEST TIME {record.get('best_time', '-')}   "
                      f"PLAYS {len(records.history_of(record))}"]
    return "\n".join(lines)


def solution_moves(game, algorithm) -> list[str] | None:
    """현재 위치/열쇠 상태에서 출구까지의 W/A/S/D 입력 목록. AUTO SOLVE 가 쓴다."""
    result = algorithm(game.maze, start=game.player.position,
                       has_key=game.player.has_key)
    return moves_for(result.path) if result.path else None


class MainWindow(tk.Tk):
    """창 하나. 머리글 + BACK + 화면 한 칸."""

    def __init__(self):
        super().__init__()
        self.title("MAZE-13  FACILITY CONTROL")
        self.configure(bg=preview.BG)
        self.minsize(460, 420)

        bar = tk.Frame(self, bg=preview.PANEL)
        bar.pack(fill="x")
        self.header = tk.Label(bar, text="", bg=preview.PANEL, fg=preview.FG,
                               font=preview.FONT, anchor="w")
        self.header.pack(side="left", padx=10, pady=6)
        self.back = button(bar, "< BACK", self.open_menu, width=9)

        self.container = tk.Frame(self, bg=preview.BG)
        self.container.pack(fill="both", expand=True)
        self.screen = None
        self.open_menu()

    # ---- 화면 전환 ---------------------------------------------------------

    def show(self, factory, **kwargs) -> None:
        """현재 화면을 버리고 새 화면을 끼운다. 창은 계속 하나다."""
        if self.screen is not None:
            self.screen.destroy()
        # 머리글을 먼저 세워 두면 화면이 자기 이름으로 덮어쓸 수 있다 (예: 맵 이름).
        self.header.configure(text=f"MAZE-13   //   {factory.TITLE}")
        self.screen = factory(self.container, self, **kwargs)
        self.screen.pack(fill="both", expand=True)
        if factory is MenuScreen:
            self.back.pack_forget()
        else:
            self.back.pack(side="right", padx=8, pady=4)
        self.geometry("")          # 화면 내용에 맞춰 창 크기를 다시 잡는다

    def open_menu(self):
        self.show(MenuScreen)

    def open_play(self):
        self.show(MapSelectScreen)

    def open_generator(self):
        self.show(GeneratorScreen)

    def open_editor(self):
        self.show(EditorScreen)

    def open_records(self):
        self.show(RecordsScreen)

    def open_continue(self):
        path = save_manager.latest_save()
        if path is None:
            messagebox.showinfo("CONTINUE", "저장된 게임이 없습니다.", parent=self)
            return
        try:
            game = save_manager.load_game(path)
        except (OSError, ValueError, KeyError) as error:
            messagebox.showerror("CONTINUE", f"저장 파일을 읽을 수 없습니다.\n{error}",
                                 parent=self)
            return
        if game.play_mode == CLASSIC:
            self.show(ClassicScreen, game=game)
        else:
            self._run_3d(game)

    # ---- 플레이 진입 -------------------------------------------------------

    def start_game(self, map_path, time_limit=None, classic=False):
        """플레이 진입점. CLASSIC / HORROR 어느 쪽이든 반드시 이 함수를 지난다.

        메모리의 Maze 를 넘기지 않고 TXT 를 다시 읽고 다시 검증한다.
        """
        try:
            maze = load_maze(map_path)
        except (OSError, ValueError) as error:
            messagebox.showerror("PLAY", str(error), parent=self)
            return
        errors = validate(maze)
        if errors:
            messagebox.showerror("PLAY", "검증 실패:\n" + "\n".join(errors), parent=self)
            return

        game = Game(maze, time_limit=time_limit, map_name=Path(map_path).name,
                    play_mode=CLASSIC if classic else HORROR)
        if classic:
            self.show(ClassicScreen, game=game)   # 과제 기본 모드에는 Creature 가 없다
        else:
            game.attach_creature()                # 맵에 G 가 있을 때만 붙는다
            self._run_3d(game)

    def _run_3d(self, game):
        """pygame 창이 닫힐 때까지 Tk 를 숨긴다. ESC 로 여기 복귀."""
        from renderer import game_view

        self.withdraw()
        try:
            game_view.run(game)
        except Exception as error:  # 렌더러가 죽어도 메뉴로는 돌아온다
            messagebox.showerror("PLAY 3D", f"3D 실행 중 오류: {error}", parent=self)
        finally:
            self.deiconify()


class MenuScreen(tk.Frame):
    TITLE = "MAIN MENU"

    def __init__(self, parent, app):
        super().__init__(parent, bg=preview.BG)
        self.app = app
        tk.Label(self, text="MAZE-13", bg=preview.BG, fg=preview.FG,
                 font=preview.TITLE_FONT).pack(pady=(28, 2))
        tk.Label(self, text="MAZE ESCAPE   //   CLASSIC 2D + 3D HORROR", bg=preview.BG,
                 fg=preview.DIM, font=preview.FONT).pack(pady=(0, 24))
        for label, command in (("PLAY", app.open_play),
                               ("RANDOM MAZE", app.open_generator),
                               ("MAP EDITOR", app.open_editor),
                               ("CONTINUE", app.open_continue),
                               ("RECORDS", app.open_records),
                               ("EXIT", app.destroy)):
            button(self, label, command).pack(pady=3)


class RecordsScreen(tk.Frame):
    TITLE = "RECORDS"

    def __init__(self, parent, app):
        super().__init__(parent, bg=preview.BG)
        panel = text_panel(self, height=22)
        panel.insert("1.0", format_records(records.load()))
        panel.configure(state="disabled")


class MapSelectScreen(tk.Frame):
    """maps/ 목록 + 검증 결과 + 경로 탐색 정보 + 탐색 경로 시각화."""

    TITLE = "PLAY  //  SELECT MAP"

    def __init__(self, parent, app):
        super().__init__(parent, bg=preview.BG)
        self.app = app
        self.maze = None
        self.path = None
        self.shown_path = ()

        left = tk.Frame(self, bg=preview.BG)
        left.pack(side="left", fill="y", padx=10, pady=10)
        self.listbox = tk.Listbox(left, width=24, height=12, bg=preview.PANEL,
                                  fg=preview.FG, font=preview.FONT, relief="flat",
                                  selectbackground=preview.DIM, exportselection=False)
        self.listbox.pack()
        self.listbox.bind("<<ListboxSelect>>", lambda _event: self.select())

        tk.Label(left, text="TIME LIMIT (sec, 비우면 무제한)", bg=preview.BG,
                 fg=preview.DIM, font=preview.FONT).pack(anchor="w", pady=(8, 0))
        self.limit = tk.Entry(left, bg=preview.PANEL, fg=preview.FG, font=preview.FONT,
                              relief="flat", insertbackground=preview.FG)
        self.limit.pack(fill="x")
        button(left, "CLASSIC 2D", lambda: self.play(classic=True),
               width=20).pack(fill="x", pady=(10, 0))
        button(left, "3D HORROR", self.play, width=20).pack(fill="x", pady=3)

        tk.Label(left, text="SHOW SEARCH PATH", bg=preview.BG, fg=preview.DIM,
                 font=preview.FONT).pack(anchor="w", pady=(12, 0))
        for name in ALGORITHMS:
            button(left, f"SHOW {name.upper()} PATH",
                   lambda n=name: self.show_path(n), width=20).pack(fill="x", pady=1)
        button(left, "CLEAR PATH", lambda: self.show_path(None), width=20).pack(fill="x")
        button(left, "REFRESH", self.reload, width=20).pack(fill="x", pady=(8, 0))

        right = tk.Frame(self, bg=preview.BG)
        right.pack(side="left", fill="both", expand=True, padx=(0, 10), pady=10)
        self.canvas = tk.Canvas(right, bg=preview.BG, highlightthickness=0)
        self.canvas.pack()
        self.info = text_panel(right, height=12)
        self.reload()

    def reload(self):
        self.listbox.delete(0, "end")
        for path in sorted(MAPS_DIR.glob("*.txt")):
            self.listbox.insert("end", path.name)

    def select(self):
        selection = self.listbox.curselection()
        if not selection:
            return
        self.path = MAPS_DIR / self.listbox.get(selection[0])
        self.shown_path = ()
        try:
            self.maze = load_maze(self.path)
        except (OSError, ValueError) as error:
            self.show(str(error))
            return
        self.redraw()
        self.show(describe_maze(self.maze, self.path.name,
                                records.load().get(self.path.name)))

    def redraw(self):
        preview.draw(self.canvas, self.maze, path=self.shown_path)

    def show_path(self, name):
        """경로를 그려 보기만 한다. Player 를 움직이지는 않는다 (그건 AUTO SOLVE)."""
        if self.maze is None:
            messagebox.showinfo("PLAY", "미로를 먼저 선택하세요.", parent=self.app)
            return
        if name is None:
            self.shown_path = ()
        else:
            result = ALGORITHMS[name](self.maze)
            if result.path is None:
                messagebox.showwarning("PLAY", f"{name.upper()} 경로를 찾지 못했습니다.",
                                       parent=self.app)
                return
            self.shown_path = result.path
        self.redraw()

    def show(self, text):
        self.info.delete("1.0", "end")
        self.info.insert("1.0", text)

    def play(self, classic=False):
        if self.path is None:
            messagebox.showinfo("PLAY", "미로를 먼저 선택하세요.", parent=self.app)
            return
        raw = self.limit.get().strip()
        try:
            limit = float(raw) if raw else None
        except ValueError:
            messagebox.showerror("PLAY", "시간 제한은 숫자로 입력하세요.", parent=self.app)
            return
        self.app.start_game(self.path, time_limit=limit, classic=classic)


class GeneratorScreen(tk.Frame):
    """RANDOM MAZE. 생성 -> TXT 저장 -> 저장한 TXT 를 다시 읽어 검증."""

    TITLE = "RANDOM MAZE"
    WIDTH, HEIGHT, SEED, LOOP = "width", "height", "seed (optional)", "loop ratio (0 ~ 1)"
    FIELDS = ((WIDTH, "21"), (HEIGHT, "15"), (SEED, ""), (LOOP, "0.10"))

    def __init__(self, parent, app):
        super().__init__(parent, bg=preview.BG)
        self.app = app

        form = tk.Frame(self, bg=preview.BG)
        form.pack(side="left", fill="y", padx=10, pady=10)
        self.entries = {}
        for label, default in self.FIELDS:
            tk.Label(form, text=label, bg=preview.BG, fg=preview.DIM,
                     font=preview.FONT).pack(anchor="w")
            entry = tk.Entry(form, bg=preview.PANEL, fg=preview.FG, font=preview.FONT,
                             relief="flat", insertbackground=preview.FG, width=20)
            entry.insert(0, default)
            entry.pack(fill="x", pady=(0, 6))
            self.entries[label] = entry

        self.specials = tk.BooleanVar(value=True)
        tk.Checkbutton(form, text="special tiles (K/D/T/G)", variable=self.specials,
                       bg=preview.BG, fg=preview.FG, font=preview.FONT,
                       selectcolor=preview.PANEL, activebackground=preview.BG,
                       activeforeground=preview.FG).pack(anchor="w", pady=(4, 8))
        button(form, "GENERATE", self.run, width=20).pack(fill="x")

        right = tk.Frame(self, bg=preview.BG)
        right.pack(side="left", fill="both", expand=True, padx=(0, 10), pady=10)
        self.canvas = tk.Canvas(right, bg=preview.BG, highlightthickness=0)
        self.canvas.pack()
        self.info = text_panel(right, height=10)

    def run(self):
        try:
            width = int(self.entries[self.WIDTH].get())
            height = int(self.entries[self.HEIGHT].get())
            loop_ratio = float(self.entries[self.LOOP].get() or 0)
            raw_seed = self.entries[self.SEED].get().strip()
            seed = int(raw_seed) if raw_seed else None
        except ValueError:
            messagebox.showerror("RANDOM MAZE", "숫자 입력을 확인하세요.", parent=self.app)
            return

        try:
            maze = generate(width, height, seed=seed, loop_ratio=loop_ratio,
                            specials=self.specials.get())
        except ValueError as error:
            messagebox.showerror("RANDOM MAZE", str(error), parent=self.app)
            return

        path = save_manager.next_numbered_path(MAPS_DIR, "random", ".txt")
        save_maze(maze, path)

        # 메모리의 Maze 를 그대로 쓰지 않고 방금 쓴 파일을 다시 읽어 검증한다.
        reloaded = load_maze(path)
        errors = validate(reloaded)
        preview.draw(self.canvas, reloaded)
        self.info.delete("1.0", "end")
        self.info.insert("1.0", f"{path} 저장 완료.\n"
                                f"{reloaded.width} x {reloaded.height}\n\n"
                                + ("VALIDATION: PASS" if not errors else
                                   "VALIDATION: FAIL\n" + "\n".join(errors)))
        if errors:
            return
        if messagebox.askyesno("RANDOM MAZE",
                               f"{path.name} 생성 완료.\n생성한 미로를 플레이하시겠습니까?",
                               parent=self.app):
            self.app.start_game(path)


class ClassicScreen(tk.Frame):
    """CLASSIC 2D - 과제 기본 모드.

    W/A/S/D 는 화면 기준 상/좌/하/우 절대 방향이고 (3D 의 카메라 상대 이동과 다름),
    현재 위치는 P 로 표시한다. Creature 는 이 모드에 없다.
    """

    TITLE = "CLASSIC 2D"

    def __init__(self, parent, app, game):
        super().__init__(parent, bg=preview.BG)
        self.app = app
        self.game = game
        self.finished = False
        self.shown_path = ()
        self.auto_keys = []

        app.header.configure(text=f"MAZE-13   //   CLASSIC 2D  //  {game.map_name}")
        self.status = tk.Label(self, text="", bg=preview.BG, fg=preview.FG,
                               font=preview.FONT, anchor="w")
        self.status.pack(fill="x", padx=10, pady=(10, 4))
        tk.Label(self, text="W = UP    A = LEFT    S = DOWN    D = RIGHT"
                            "        P = 현재 위치", bg=preview.BG, fg=preview.DIM,
                 font=preview.FONT, anchor="w").pack(fill="x", padx=10)
        # 함정 / 열쇠 / 문 같은 사건은 3D 와 같은 문구로 알려 준다.
        self.event = tk.Label(self, text="", bg=preview.BG, fg=preview.FG,
                              font=preview.FONT, anchor="w")
        self.event.pack(fill="x", padx=10, pady=(2, 0))
        self.canvas = tk.Canvas(self, bg=preview.BG, highlightthickness=0)
        self.canvas.pack(padx=10, pady=(6, 0))

        bar = tk.Frame(self, bg=preview.BG)
        bar.pack(fill="x", padx=10, pady=(8, 2))
        button(bar, "SAVE", self.save, width=8).pack(side="left")
        for name in ALGORITHMS:
            button(bar, f"SHOW {name.upper()}", lambda n=name: self.show_path(n),
                   width=10).pack(side="left", padx=2)
        button(bar, "CLEAR", lambda: self.show_path(None), width=8).pack(side="left")

        auto = tk.Frame(self, bg=preview.BG)
        auto.pack(fill="x", padx=10, pady=(0, 8))
        tk.Label(auto, text="AUTO SOLVE ", bg=preview.BG, fg=preview.DIM,
                 font=preview.FONT).pack(side="left")
        for name in ALGORITHMS:
            button(auto, name.upper(), lambda n=name: self.auto_solve(n),
                   width=8).pack(side="left", padx=2)

        # Frame 은 키 포커스를 받지 않으므로 창(root)에 걸고, 화면을 나갈 때 떼어 낸다.
        self.sequences = []
        for key in "wasd":
            for sequence in (f"<{key}>", f"<{key.upper()}>"):
                self._bind(sequence, self.on_key)
        for key, mapped in (("Up", "w"), ("Left", "a"), ("Down", "s"), ("Right", "d")):
            self._bind(f"<{key}>", lambda _event, m=mapped: self.step(m))
        self.redraw()
        self.tick()

    def _bind(self, sequence, handler):
        self.app.bind(sequence, handler)
        self.sequences.append(sequence)

    def destroy(self):
        for sequence in self.sequences:
            self.app.unbind(sequence)
        self.finished = True          # 남아 있는 after() 콜백을 멈춘다
        super().destroy()

    # ---- 입력 -------------------------------------------------------------

    def on_key(self, event):
        self.step(event.keysym.lower())

    def step(self, key):
        if self.finished or self.auto_keys:
            return
        self.game.move(key)
        self.announce()
        self.redraw()
        self.check_over()

    def announce(self):
        """마지막 이동에서 벌어진 일을 한 줄로 보여 준다. 없으면 지운다."""
        event = self.game.last_event
        self.event.configure(
            text=EVENT_TEXT.get(event, ""),
            fg=preview.ALERT if event in WARN_EVENTS else preview.FG)

    def show_path(self, name):
        """경로 시각화만 한다. Player 는 움직이지 않는다."""
        if name is None:
            self.shown_path = ()
        else:
            result = ALGORITHMS[name](self.game.maze, start=self.game.player.position,
                                      has_key=self.game.player.has_key)
            self.shown_path = result.path or ()
        self.redraw()

    def auto_solve(self, name):
        """계산된 경로를 따라 Game.move() 로 실제 이동한다 (사람 플레이와 동일 규칙)."""
        if self.finished or self.auto_keys:
            return
        keys = solution_moves(self.game, ALGORITHMS[name])
        if not keys:
            messagebox.showwarning("AUTO SOLVE", "경로를 찾지 못했습니다.", parent=self.app)
            return
        self.shown_path = ()
        self.auto_keys = keys
        self.auto_step()

    def auto_step(self):
        if self.finished or not self.auto_keys or not self.winfo_exists():
            self.auto_keys = []
            return
        self.game.move(self.auto_keys.pop(0))
        self.announce()
        self.redraw()
        self.check_over()
        if self.auto_keys:
            self.after(AUTO_STEP_MS, self.auto_step)

    # ---- 화면 -------------------------------------------------------------

    def tick(self):
        if self.finished or not self.winfo_exists():
            return
        self.refresh_status()
        self.check_over()
        self.after(200, self.tick)

    def refresh_status(self):
        game = self.game
        remaining = game.remaining
        clock = (f"TIME {game.elapsed:6.2f}" if remaining is None
                 else f"LEFT {remaining:6.2f} / {game.time_limit:.0f}")
        self.status.configure(
            text=f"{clock}   MOVES {game.player.move_count:4d}   "
                 f"KEY {'1' if game.player.has_key else '0'}   "
                 f"TIMER {game.mode}   MODE {game.play_mode}")

    def redraw(self):
        preview.draw(self.canvas, self.game.maze, visited=self.game.visited_path,
                     player=self.game.player.position,
                     opened_doors=self.game.opened_doors, path=self.shown_path)
        self.refresh_status()

    def check_over(self):
        if self.finished or not self.game.over:
            return
        self.finished = True
        self.auto_keys = []
        if self.game.cleared:
            entry = records.update(self.game.map_name, self.game.player.move_count,
                                   self.game.elapsed, mode=self.game.play_mode)
            messagebox.showinfo(
                "MAZE CLEARED",
                f"MOVES {self.game.player.move_count}\n"
                f"TIME  {self.game.elapsed:.2f}\n\n"
                f"BEST MOVES {entry['best_moves']}\n"
                f"BEST TIME  {entry['best_time']:.2f}\n"
                f"PLAYS      {len(records.history_of(entry))}",
                parent=self.app)
        else:
            messagebox.showwarning("TIME OVER", "제한 시간을 초과했습니다.",
                                   parent=self.app)

    def save(self):
        path = save_manager.save_game(self.game, save_manager.next_save_path())
        messagebox.showinfo("SAVE", f"{path} 에 저장했습니다.", parent=self.app)
