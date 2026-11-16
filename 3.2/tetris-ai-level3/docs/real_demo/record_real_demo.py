"""Record the real-play demo of the finished game.

How it works (nothing here touches the game's Python objects -- the game is a separate process):
  1. `python run.py` is started as a normal child process (the unmodified program).
  2. A recorder thread captures ONLY that process's windows with Win32 PrintWindow.
  3. An automated player reads the board from those captured pixels (vision.py), decides a
     placement with its own offline planner, and presses keys / clicks buttons through Win32
     SendInput (winio.py) -- the same OS input path as a physical keyboard and mouse.
     Before every input it checks that the foreground window belongs to the game process.
  4. Every input, caption and segment marker is logged with a timestamp (events.json) so the
     edited video (compose_video.py) can show exactly which keys were pressed.

Usage:  python docs/real_demo/record_real_demo.py <output_dir>
"""
import ctypes
import json
import subprocess
import sys
import threading
import time
from pathlib import Path

import imageio_ffmpeg
import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
PROJ = HERE.parents[1]
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(PROJ))
import winio      # noqa: E402
import vision     # noqa: E402
# Offline planning helpers only (pure functions run inside THIS process on the screen-parsed board).
from tetris.engine import Piece, W, H, valid, try_rotate, drop, lock_piece      # noqa: E402
from tetris.ai import choose, plan_actions                                       # noqa: E402
from tetris.puzzles import explore, _key, _path, _grounded                       # noqa: E402

OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / 'raw'
SHOTS = PROJ / 'docs' / 'screens_real'
CLIENT_W, CLIENT_H = 1600, 900
P1 = {'left': 'left', 'right': 'right', 'cw': 'up', 'ccw': 'z', 'soft': 'down', 'hard': 'space', 'hold': 'c'}
P2 = {'left': 'a', 'right': 'd', 'cw': 'w', 'ccw': 'e', 'soft': 's', 'hard': 'f', 'hold': 'q'}
KEY_LABEL = {'left': '←', 'right': '→', 'up': '↑', 'down': '↓', 'space': 'Space', 'escape': 'Esc'}


# ============================================================================ logging / recorder
class Log:
    def __init__(self):
        self.t0 = time.perf_counter()
        self.events = []
        self.lock = threading.Lock()

    def __call__(self, kind, value=None, **kw):
        with self.lock:
            self.events.append({'t': round(time.perf_counter() - self.t0, 4), 'kind': kind, 'value': value, **kw})


class LazyFrame:
    """Raw BGRX bytes of the whole window; RGB (cropped to the visible frame) is built on demand."""

    def __init__(self, raw, w, h, crop):
        self.raw, self.w, self.h, self.crop = raw, w, h, crop
        self._rgb = None

    def rgb(self):
        if self._rgb is None:
            cx, cy, fw, fh = self.crop
            a = np.frombuffer(self.raw, np.uint8).reshape(self.h, self.w, 4)
            self._rgb = np.ascontiguousarray(a[cy:cy + fh, cx:cx + fw, 2::-1])
        return self._rgb


class _Ctx:
    """One GDI memory DC + bitmap (each capture thread owns one)."""

    def __init__(self, hwnd, w, h):
        u, g = winio.user32, winio.gdi32
        self.hwnd = hwnd
        self.hdc = u.GetDC(hwnd)
        self.mdc = g.CreateCompatibleDC(self.hdc)
        self.bmp = g.CreateCompatibleBitmap(self.hdc, w, h)
        g.SelectObject(self.mdc, self.bmp)
        self.bih = winio.BITMAPINFOHEADER(ctypes.sizeof(winio.BITMAPINFOHEADER), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
        self.buf = ctypes.create_string_buffer(w * h * 4)

    def free(self):
        winio.gdi32.DeleteObject(self.bmp); winio.gdi32.DeleteDC(self.mdc); winio.user32.ReleaseDC(self.hwnd, self.hdc)


class Recorder:
    """Captures the game's own windows (main + e.g. the records dialog) with PrintWindow at 30 fps.
    Two capture threads take alternate 1/30 s ticks (one PrintWindow takes ~35 ms); a writer thread
    re-orders the frames and streams raw BGRX to ffmpeg (ffmpeg crops the invisible resize border)."""
    PERIOD = 1 / 30

    def __init__(self, log, pid, hwnd, path, session):
        self.log, self.pid, self.hwnd, self.session = log, pid, hwnd, session
        l, t, r, b = winio.window_rect(hwnd)
        fl, ft, fr, fb = winio.frame_bounds(hwnd)
        self.w, self.h = r - l, b - t
        self.crop = (fl - l, ft - t, fr - fl, fb - ft)
        self.size = (fr - fl, fb - ft)
        cx, cy, fw, fh = self.crop
        self.writer = imageio_ffmpeg.write_frames(str(path), (self.w, self.h), fps=30, codec='libx264', quality=None,
                                                  pix_fmt_in='bgr0', pix_fmt_out='yuv444p', macro_block_size=1,
                                                  output_params=['-vf', f'crop={fw}:{fh}:{cx}:{cy}',
                                                                 '-crf', '8', '-preset', 'ultrafast'])
        self.writer.send(None)
        self.ctx = [_Ctx(hwnd, self.w, self.h), _Ctx(hwnd, self.w, self.h)]
        self.frames = []          # per written frame: t, cursor relative to the visible window, stale flag
        self.latest = (-1.0, None)
        self.cv = threading.Condition()
        self.done = {}
        self.running = True
        self.t_start = time.perf_counter() + 0.05
        self.threads = [threading.Thread(target=self._capture, args=(k,), daemon=True) for k in (0, 1)]
        self.wthread = threading.Thread(target=self._write, daemon=True)

    def start(self):
        for th in self.threads:
            th.start()
        self.wthread.start()

    def grab(self, ctx):
        u, g = winio.user32, winio.gdi32
        if u.IsIconic(self.hwnd) or not u.IsWindow(self.hwnd):
            return None
        l, t, r, b = winio.window_rect(self.hwnd)
        if (r - l, b - t) != (self.w, self.h):
            return None
        if not u.PrintWindow(self.hwnd, ctx.mdc, winio.PW_RENDERFULLCONTENT):
            return None
        if not g.GetDIBits(ctx.mdc, ctx.bmp, 0, self.h, ctx.buf, ctypes.byref(ctx.bih), 0):
            return None
        raw = ctx.buf.raw
        others = [h for h in winio.windows_of_pid(self.pid) if h != self.hwnd and winio.window_title(h)]
        if others:                                         # e.g. the records dialog: paste it where it is on screen
            arr = np.frombuffer(raw, np.uint8).reshape(self.h, self.w, 4).copy()
            for h in reversed(others):                     # bottom-most first
                im = winio.grab_window(h)
                if im is None:
                    continue
                hl, ht, _, _ = winio.frame_bounds(h)
                x, y = hl - l, ht - t
                x0, y0 = max(0, x), max(0, y)
                x1, y1 = min(self.w, x + im.shape[1]), min(self.h, y + im.shape[0])
                if x1 > x0 and y1 > y0:
                    arr[y0:y1, x0:x1, :3] = im[y0 - y:y1 - y, x0 - x:x1 - x, ::-1]
            raw = arr.tobytes()
        return raw, (l + self.crop[0], t + self.crop[1])

    def _capture(self, k):
        i = k
        while self.running:
            target = self.t_start + i * self.PERIOD
            now = time.perf_counter()
            if now > target + self.PERIOD / 2:          # this tick is already late: skip it (no frame)
                with self.cv:
                    self.done[i] = 'skip'; self.cv.notify_all()
                i += 2
                continue
            if target > now:
                time.sleep(target - now)
            res = self.grab(self.ctx[k])
            ts = time.perf_counter()                     # content time = when PrintWindow returned
            cur = winio.cursor_pos()
            if res is not None:
                with self.cv:
                    if ts > self.latest[0]:
                        self.latest = (ts, LazyFrame(res[0], self.w, self.h, self.crop))
            with self.cv:
                self.done[i] = (ts, res, cur)
                self.cv.notify_all()
            i += 2

    def _write(self):
        i, prev = 0, None
        while True:
            with self.cv:
                while i not in self.done:
                    if not self.running and not any(th.is_alive() for th in self.threads):
                        return
                    self.cv.wait(0.2)
                item = self.done.pop(i)
            i += 1
            if item == 'skip':
                continue
            ts, res, cur = item
            if self.frames and ts <= self.frames[-1]['t'] + self.log.t0:
                continue                                  # finished after a later tick: keep time monotonic
            if res is None:
                if prev is None:
                    continue
                (raw, origin), stale = prev, True
            else:
                (raw, origin), stale = res, False
                prev = res
            self.writer.send(raw)
            self.frames.append({'t': ts - self.log.t0, 'cursor': [cur[0] - origin[0], cur[1] - origin[1]],
                                'stale': stale})

    def stop(self):
        self.running = False
        for th in self.threads:
            th.join(5)
        with self.cv:
            self.cv.notify_all()
        self.wthread.join(120)
        self.writer.close()
        for c in self.ctx:
            c.free()


# ============================================================================ controller
class Demo:
    def __init__(self):
        OUT.mkdir(parents=True, exist_ok=True); SHOTS.mkdir(parents=True, exist_ok=True)
        self.log = Log()
        self.proc = None; self.rec = None; self.hwnd = None; self.session = 0
        self.inp = winio.Input(0, self.log)
        self.buttons = None; self.boards = []
        self.speed = 1.0

    # ----- process / window
    def launch(self):
        self.session += 1
        self.log('launch', 'python run.py', session=self.session)
        self.proc = subprocess.Popen([sys.executable, 'run.py'], cwd=str(PROJ))
        for _ in range(150):
            time.sleep(0.1)
            ws = [w for w in winio.windows_of_pid(self.proc.pid) if 'TETRIS' in winio.window_title(w)]
            if ws:
                self.hwnd = ws[0]; break
        else:
            raise RuntimeError('game window did not appear')
        time.sleep(0.4)
        winio.set_client_size(self.hwnd, 32, 8, CLIENT_W, CLIENT_H)
        time.sleep(0.4)
        self.inp.set_pid(self.proc.pid, self.hwnd)
        if not winio.bring_to_front(self.hwnd):
            raise winio.FocusLost('could not focus the game window')
        self.log('window', winio.window_title(self.hwnd), pid=self.proc.pid, session=self.session)
        self.rec = Recorder(self.log, self.proc.pid, self.hwnd, OUT / f'session{self.session}.mp4', self.session)
        self.rec.start()
        self.frame()
        self.buttons = vision.find_buttons(self.frame())
        self.log('buttons', repr(self.buttons))

    def end_session(self):
        if self.rec:
            self.rec.stop()
            (OUT / f'session{self.session}_frames.json').write_text(json.dumps(self.rec.frames), encoding='utf-8')
            self.rec = None
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.wait(5)
            except subprocess.TimeoutExpired:
                self.proc.terminate()

    # ----- frames
    def frame(self, after=None, timeout=3.0):
        after = time.perf_counter() if after is None else after
        end = time.perf_counter() + timeout
        while time.perf_counter() < end:
            ts, fr = self.rec.latest
            if fr is not None and ts >= after:
                return fr.rgb()
            time.sleep(0.005)
        raise TimeoutError('no fresh frame')

    def snap(self, name):
        Image.fromarray(self.frame()).save(SHOTS / f'{name}.png')
        self.log('snap', name)

    # ----- editing markers
    def caption(self, text):
        self.log('caption', text)

    def card(self, title, body=''):
        self.log('card', title, body=body)

    def seg(self, name, speed=1.0):
        self.speed = speed
        self.log('seg_start', name, speed=speed, session=self.session)

    def seg_end(self):
        self.log('seg_end', None, session=self.session)

    def set_speed(self, s):
        if s != self.speed:
            self.speed = s
            self.log('speed', s)

    # ----- input helpers
    def click(self, pt, label):
        l, t, _, _ = winio.frame_bounds(self.hwnd)
        self.inp.click(l + int(pt[0]), t + int(pt[1]), label)

    def tap(self, key, label=None, hold=0.03):
        self.inp.tap(key, hold=hold, label=label or KEY_LABEL.get(key, key.upper()))

    def wait(self, s):
        time.sleep(s)

    def detect_boards(self, n):
        for _ in range(30):
            bs = vision.find_boards(self.frame())
            if len(bs) == n:
                self.boards = bs
                self.log('boards', repr(bs))
                return bs
            time.sleep(0.1)
        raise RuntimeError(f'expected {n} boards, found {len(bs)}')


# ============================================================================ planning (offline, on parsed pixels)
def to_board(grid, exclude=()):
    ex = set(exclude)
    return [[(None if (x, y) in ex or k is None else ('G' if k == '?' else k)) for x, k in enumerate(row)]
            for y, row in enumerate(grid)]


def detect_spawn(grid, max_dy=1):
    """The current piece right after spawning (spawn column/rotation; it may have fallen max_dy rows)."""
    for dy in range(max_dy + 1):
        for k in 'IOTSZJL':
            p = Piece(k); p.y += dy
            vis = [(x, y) for x, y in p.squares() if y >= 0]
            if vis and all(grid[y][x] == k for x, y in vis):
                return k, p, vis
    return None


ROT_SEQS = [[], ['cw'], ['cw', 'cw'], ['ccw']]


def candidates(board, kind, start=None):
    out = {}
    for rs in ([[]] if kind == 'O' else ROT_SEQS):
        p = (start or Piece(kind)).copy()
        ok = True
        for a in rs:
            q = try_rotate(board, p, 1 if a == 'cw' else -1)
            if q is None:
                ok = False; break
            p = q
        if not ok:
            continue
        for d in (-1, 1):
            q, seq = p, []
            while True:
                land = drop(board, q)
                key = frozenset(land.squares())
                if key not in out:
                    out[key] = (rs + seq + ['hard'], land)
                z = q.copy(); z.x += d; z.rotated_last = False
                if not valid(board, z):
                    break
                q, seq = z, seq + ['left' if d < 0 else 'right']
    return out


def features(b):
    heights, holes = [], 0
    for x in range(W):
        top = next((y for y in range(H) if b[y][x] is not None), H)
        heights.append(H - top)
        holes += sum(1 for y in range(top, H) if b[y][x] is None)
    return heights, holes


def tetris_policy(board, kind, piece=None, well=9):
    """Human-style 'keep a well, clear several lines at once' plan (used for the automated player)."""
    h0, _ = features(board)
    best = None
    for key, (acts, land) in candidates(board, kind, piece).items():
        new, n, spin, topped = lock_piece(board, land)
        if topped:
            continue
        hs, holes = features(new)
        others = [h for i, h in enumerate(hs) if i != well]
        bump = sum(abs(others[i] - others[i + 1]) for i in range(len(others) - 1))
        maxh = max(hs)
        danger = max(h0) >= 11
        sc = 0.0
        if n >= 2:
            sc += 320 * n
        elif n == 1:
            sc += 40 if danger else -70
        in_well = sum(1 for x, _ in land.squares() if x == well)
        if in_well and n < 2 and not danger:
            sc -= 160
        sc -= 85 * holes + 3.2 * sum(others) + 7.5 * bump + 12 * max(0, maxh - 9) ** 1.4
        if best is None or sc > best[0]:
            best = (sc, acts, n)
    if best is None:
        return ['hard'], 0
    return best[1], best[2]


def coach_policy(board, kind, piece=None):
    """Same choice the in-game coach shows (tetris.ai.choose, 'normal')."""
    best, _ = choose(board, kind, None, 'normal')
    if best is None:
        return ['hard'], 0
    new, n, spin, topped = lock_piece(board, drop(board, best.piece))
    return plan_actions(board, piece or Piece(kind), best.piece), n


# ============================================================================ cooperative multi-player scheduler
def agent(demo, idx, keys, policy, label, gap=0.085, on_plan=None, stop=lambda: False, hook=None):
    """Generator: observe the board on screen -> plan -> press keys. Yields scheduler commands."""
    pieces = 0
    while not stop():
        yield ('sleep', 0.14)
        spawn = None
        for _ in range(12):
            img = yield ('frame',)
            grid = vision.read_grid(img, demo.boards[idx])
            spawn = detect_spawn(grid, max_dy=12)
            if spawn:
                break
            yield ('sleep', 0.07)
        if spawn is None:
            demo.log('agent_idle', label)
            return
        kind, piece, vis = spawn
        board = to_board(grid, vis)
        if hook:
            r = yield from hook(pieces, board, kind, piece)
            if r == 'placed':
                pieces += 1
                continue
            if r == 'reobserve':
                continue
        acts, n = policy(board, kind, piece)
        if on_plan:
            on_plan(label, kind, n)
        for a in acts:
            yield ('key', keys[a])
            yield ('sleep', gap)
        pieces += 1


def run_agents(demo, gens, until):
    st = [{'g': g, 't': time.perf_counter(), 'want': None} for g in gens]
    while st and not until():
        s = min(st, key=lambda e: e['t'])
        dt = s['t'] - time.perf_counter()
        if dt > 0:
            time.sleep(min(dt, 0.02)); continue
        send = None
        if s['want'] is not None:
            ts, fr = demo.rec.latest
            if fr is None or ts < s['want']:
                s['t'] = time.perf_counter() + 0.01; continue
            send, s['want'] = fr.rgb(), None
        try:
            cmd = s['g'].send(send)
        except StopIteration:
            st.remove(s); continue
        if cmd[0] == 'sleep':
            s['t'] = time.perf_counter() + cmd[1]
        elif cmd[0] == 'key':
            demo.tap(cmd[1])
            s['t'] = time.perf_counter()
        elif cmd[0] == 'frame':
            s['want'] = time.perf_counter(); s['t'] = time.perf_counter()


# ============================================================================ puzzle executor (closed loop)
def apply_action(board, p, a):
    if a in ('cw', 'ccw'):
        return try_rotate(board, p, 1 if a == 'cw' else -1) or p
    z = p.copy(); z.x += {'left': -1, 'right': 1}.get(a, 0); z.y += 1 if a == 'down' else 0; z.rotated_last = False
    return z if valid(board, z) else p


def visible(p):
    return frozenset((x, y) for x, y in p.squares() if y >= 0)


def solve_piece(demo, g, B, kind, target, need_spin, start=None):
    keys = {'left': 'left', 'right': 'right', 'down': 'down', 'cw': 'up', 'ccw': 'z'}
    sim = (start or Piece(kind)).copy()
    for _ in range(80):
        img = demo.frame(time.perf_counter() + 0.03)
        grid = vision.read_grid(img, g)
        obs = frozenset((x, y) for y, row in enumerate(grid) for x, k in enumerate(row) if k == kind and B[y][x] is None)
        if obs != visible(sim):                                  # gravity pulled it down
            for k in range(1, H + 1):
                z = sim.copy(); z.y += k; z.rotated_last = False
                if valid(B, z) and visible(z) == obs:
                    sim = z; break
            else:
                time.sleep(0.05); continue
        if need_spin:
            if frozenset(sim.squares()) == target and sim.rotated_last:
                demo.wait(0.7); demo.tap('space'); return True
        elif frozenset(drop(B, sim).squares()) == target:
            demo.wait(0.4); demo.tap('space'); return True
        parents, order = explore(B, kind, start=sim)
        goal = next((p for p in order if frozenset(p.squares()) == target and _grounded(B, p)
                     and (p.rotated_last or not need_spin)), None)
        if goal is None:
            demo.log('puzzle_no_path', kind); return False
        path = _path(parents, _key(goal))
        if not need_spin:                                  # stop as soon as a hard drop lands on target
            q = sim
            for i, a in enumerate(path):
                if frozenset(drop(B, q).squares()) == target:
                    path = path[:i]; break
                q = apply_action(B, q, a)
        if not path:
            continue
        a = path[0]
        demo.tap(keys[a])
        sim = apply_action(B, sim, a)
        demo.wait(0.2)
    return False


# ============================================================================ scenes
def scene_launch(d):
    d.card('자동화된 GUI 입력 시연', '실제 프로그램(python run.py)을 실행하고 Windows SendInput 키보드·마우스 입력만으로 조작했습니다.\n'
           '게임 창만 PrintWindow로 녹화 · 게임 내부 상태(보드·블록·점수·승패)는 변경하지 않음')
    d.card('장면 1 · 프로그램 실행', '프로젝트 폴더에서 python run.py 실행 → 메인 화면')
    d.launch()
    d.seg('launch')
    d.caption('python run.py로 실행한 실제 메인 화면 · 저장된 기록(records.json) 표시')
    d.wait(2.5); d.snap('01_main')
    b = d.buttons
    d.caption('게임 모드 선택 (마우스 클릭)')
    for m in ('solo', 'two', 'versus', 'ai', 'puzzle'):
        d.click(b['modes'][m], m); d.wait(0.75)
    d.caption('AI 난이도 선택 (쉬움 · 보통 · 어려움)')
    for v in ('easy', 'normal', 'hard'):
        d.click(b['diff'][v], v); d.wait(0.75)
    d.click(b['diff']['normal'], 'normal'); d.wait(0.6)
    d.snap('02_mode_select')
    d.seg_end()


def scene_solo(d):
    d.card('장면 2 · 1인용 테트리스', '이동 · 회전 · Wall Kick · Hard Drop · Next/Hold · 줄 제거 · 점수')
    b = d.buttons
    d.seg('solo')
    d.click(b['modes']['solo'], 'solo'); d.wait(0.5)
    d.caption('1인용 선택 → R 키로 시작')
    d.tap('r'); d.wait(0.6)
    d.detect_boards(1)
    state = {'kick': False, 'hold': False, 'pieces': 0, 'big': 0, 'slow_until': 0.0}

    def hook(n, board, kind, piece):
        if n == 0 and not state['kick'] and kind != 'O':
            # Wall-kick demonstration with real keys: rotate, walk to the left wall, rotate again.
            d.caption('회전(↑) 후 왼쪽 벽까지 이동(←)')
            p = piece
            yield ('key', 'up'); yield ('sleep', 0.35)
            p = try_rotate(board, p, 1)
            while True:
                z = p.copy(); z.x -= 1
                if not valid(board, z):
                    break
                p = z
                yield ('key', 'left'); yield ('sleep', 0.2)
            q = try_rotate(board, p, 1)
            kicked = q is not None and q.kick_used > 0
            d.caption('벽에 붙은 상태에서 다시 회전(↑) → SRS Wall Kick으로 옆 칸으로 밀려 회전 성공' if kicked
                      else '벽 옆에서 회전(↑)')
            yield ('sleep', 0.6)
            yield ('key', 'up'); yield ('sleep', 0.9)
            img = yield ('frame',)
            grid = vision.read_grid(img, d.boards[0])
            obs = frozenset((x, y) for y, row in enumerate(grid) for x, k in enumerate(row) if k == kind and board[y][x] is None)
            exp = {(x, y) for x, y in q.squares()} if q else set()
            d.log('kick_check', bool(kicked), expected=sorted(exp), observed=sorted(obs),
                  match=bool(q) and {x for x, _ in obs} == {x for x, _ in exp})
            state['kick'] = kicked
            yield ('sleep', 0.5)
            d.snap('03_wall_kick')
            d.caption('Hard Drop (Space)')
            yield ('key', 'space'); yield ('sleep', 0.4)
            return 'placed'
        if n == 2 and not state['hold']:
            state['hold'] = True
            d.caption('Next(다음 블록 3개)와 Hold: C 키로 현재 블록을 보관 → 다음 블록이 나옴')
            yield ('sleep', 0.5)
            yield ('key', 'c'); yield ('sleep', 1.2)
            d.snap('04_hold_next')
            return 'reobserve'
        if time.perf_counter() > state['slow_until'] and state['pieces'] > 4 and d.speed == 1.0:
            d.set_speed(2.0)
            d.caption('블록 쌓기 (2배속 편집)')
        return None

    def on_plan(label, kind, n):
        state['pieces'] += 1
        if n >= 2:
            state['big'] += 1
            state['slow_until'] = time.perf_counter() + 3.0
            d.set_speed(1.0)
            d.caption(f'{n}줄 동시 제거 → 점수 증가 (STATUS의 SCORE · LINES)')

    def solo_gen():
        return agent(d, 0, P1, tetris_policy, 'P1', on_plan=on_plan, hook=hook,
                     stop=lambda: (state['big'] >= 2 and time.perf_counter() > state['slow_until']) or state['pieces'] >= 45)

    run_agents(d, [solo_gen()], until=lambda: False)
    d.set_speed(1.0)
    d.wait(1.6); d.snap('05_solo_lines')
    d.caption('Esc: 게임 종료 (중단 기록)')
    d.tap('escape'); d.wait(1.2)
    d.seg_end()
    return state


def scene_two(d):
    d.card('장면 3 · 2인 동시 플레이', 'P1: ←→↑ Space · P2: A D W F — 서로 다른 키로 각자의 보드를 독립 조작')
    b = d.buttons
    d.seg('two')
    d.click(b['modes']['two'], 'two'); d.wait(0.5)
    d.tap('r'); d.wait(0.6)
    d.detect_boards(2)
    d.caption('P1(방향키·Space)과 P2(A·D·W·F)가 동시에 입력 · 보드·점수·Next 독립')
    t_end = time.perf_counter() + 22
    gens = [agent(d, 0, P1, tetris_policy, 'P1', stop=lambda: time.perf_counter() > t_end),
            agent(d, 1, P2, coach_policy, 'P2', gap=0.1, stop=lambda: time.perf_counter() > t_end)]
    run_agents(d, gens, until=lambda: False)
    d.snap('06_two_players')
    d.wait(0.8)
    d.tap('escape'); d.wait(1.0)
    d.seg_end()


def scene_versus(d):
    d.card('장면 4 · 2인 대전 · 공격', '2줄 이상 동시 제거 → 상대에게 방해 줄 전송 (편집으로 대기 구간 2배속)')
    b = d.buttons
    d.seg('versus')
    d.click(b['modes']['versus'], 'versus'); d.wait(0.5)
    d.tap('r'); d.wait(0.6)
    d.detect_boards(2)
    st = {'attacks': 0, 'slow_until': 0.0, 'end': None}
    d.caption('2인 대전 시작 · P1은 오른쪽 끝 한 줄을 비워 여러 줄 동시 제거를 노림')

    def on_plan(label, kind, n):
        if n >= 2:
            st['attacks'] += 1
            st['slow_until'] = time.perf_counter() + 5.0
            d.set_speed(1.0)
            d.caption(f'{label} {n}줄 동시 제거 → 상대에게 공격 전송 · 상대는 다음 블록 고정 때 회색 방해 줄을 받음')
            if st['attacks'] >= 2 and st['end'] is None:
                st['end'] = time.perf_counter() + 6.0

    def until():
        now = time.perf_counter()
        if now > st['slow_until'] and d.speed == 1.0 and now > t_fast:
            d.set_speed(2.0); d.caption('대전 진행 (2배속 편집)')
        return (st['end'] is not None and now > st['end']) or now > t_limit
    t_fast = time.perf_counter() + 5
    t_limit = time.perf_counter() + 150
    gens = [agent(d, 0, P1, tetris_policy, 'P1', on_plan=on_plan),
            agent(d, 1, P2, coach_policy, 'P2', gap=0.1, on_plan=on_plan)]
    run_agents(d, gens, until=until)
    d.set_speed(1.0)
    d.snap('07_versus_attack')
    d.wait(0.8)
    d.tap('escape'); d.wait(1.0)
    d.seg_end()
    return st


def scene_ai(d):
    d.card('장면 5 · 인간 vs AI', '사람 쪽(P1)은 자동 키 입력 · 오른쪽 AI는 게임 자체 AI가 직접 판단·조작')
    b = d.buttons
    d.seg('ai')
    d.click(b['modes']['ai'], 'ai'); d.wait(0.5)
    d.caption('AI 난이도 선택: 쉬움 → 보통 → 어려움')
    for v in ('easy', 'normal', 'hard'):
        d.click(b['diff'][v], v); d.wait(0.8)
    d.tap('r'); d.wait(0.6)
    d.detect_boards(2)
    d.caption('AI(어려움)가 목표 위치(금색 점선)와 평가 점수를 계산하고 실제 키 동작으로 이동 · 계산은 백그라운드 스레드')
    t_end = time.perf_counter() + 24
    run_agents(d, [agent(d, 0, P1, tetris_policy, 'P1', stop=lambda: time.perf_counter() > t_end)], until=lambda: False)
    d.snap('08_human_vs_ai')
    d.caption('결과 화면을 보여 주기 위해 P1(자동 입력)이 회전·이동 없이 Space만 눌러 블록을 쌓음 → Top-out')
    for _ in range(40):
        d.tap('space'); d.wait(0.3)
        img = d.frame()
        if _game_over(img, d.boards[0]):
            break
    d.wait(0.5)
    d.caption('AI 승리 · 경기 결과가 records.json에 자동 저장됨')
    d.wait(3.0); d.snap('09_ai_result')
    d.seg_end()


def _game_over(img, g):
    # the GAME OVER banner is drawn in '#472334' across the board at 58% height
    y = g.y0 + int(g.cell * 20 * .58) + 6
    row = img[y, g.x0 + 5:g.x0 + g.cell * 10 - 5]
    return np.mean(np.all(np.abs(row.astype(int) - (71, 35, 52)) < 8, axis=1)) > 0.3


def scene_coach(d):
    d.card('장면 6 · AI 도우미', '블록 위치에 따라 평가 점수와 항목(줄 제거·높이·구멍·평탄화)이 실시간으로 바뀜')
    b = d.buttons
    d.seg('coach')
    d.click(b['modes']['solo'], 'solo'); d.wait(0.5)
    d.tap('r'); d.wait(0.7)
    d.detect_boards(1)
    g = d.boards[0]
    d.caption('AI 도우미 ON: 오른쪽 패널 = 지금 위치에 떨어뜨렸을 때의 평가, 청록 점선 = AI 추천 위치')
    for k in range(3):                       # two pieces placed on recommendation first (build a real stack)
        img = d.frame(time.perf_counter() + 0.1)
        sp = detect_spawn(vision.read_grid(img, g), max_dy=12)
        if not sp:
            d.wait(0.2); continue
        kind, piece, vis = sp
        board = to_board(vision.read_grid(img, g), vis)
        if k == 2:
            d.caption('블록을 한 칸씩 이동·회전 → 현재 위치 평가와 항목별 점수가 변함')
            sim = piece
            for a in ['left', 'left', 'left', 'up', 'right', 'right', 'right', 'right', 'right']:
                d.tap(a); d.wait(0.75)
                sim = apply_action(board, sim, {'up': 'cw'}.get(a, a))
            d.snap('10_coach_eval')
            best, _ = choose(board, kind, None, 'normal')
            d.caption('AI 추천 위치(청록 점선)로 이동 후 Space')
            for a in plan_actions(board, sim, best.piece):
                d.tap(P1[a]); d.wait(0.35)
        else:
            for a in coach_policy(board, kind, piece)[0]:
                d.tap(P1[a]); d.wait(0.18)
        d.wait(0.5)
    d.caption('AI 도우미 OFF (체크박스 클릭) → 추천 표시와 평가 패널이 사라짐')
    d.click(b['coach'], 'coach off'); d.wait(0.6)
    t_end = time.perf_counter() + 4.5
    run_agents(d, [agent(d, 0, P1, tetris_policy, 'P1', gap=0.15, stop=lambda: time.perf_counter() > t_end)], until=lambda: False)
    d.snap('11_coach_off')
    d.caption('AI 도우미 다시 ON')
    d.click(b['coach'], 'coach on'); d.wait(0.6)
    t_end = time.perf_counter() + 4.5
    run_agents(d, [agent(d, 0, P1, coach_policy, 'P1', gap=0.2, stop=lambda: time.perf_counter() > t_end)], until=lambda: False)
    d.tap('escape'); d.wait(1.0)
    d.seg_end()


def scene_puzzle(d):
    d.card('장면 7 · T-Spin 퍼즐 (어려움)', '게임이 생성·검증한 퍼즐 · H 키 단계별 힌트 · I → O → T 순서 · 실제 키 입력으로 풀이')
    b = d.buttons
    d.seg('puzzle')
    d.click(b['modes']['puzzle'], 'puzzle'); d.wait(0.5)
    d.click(b['diff']['hard'], 'hard'); d.wait(0.5)
    d.caption('R 키 → 게임이 어려움 퍼즐을 생성·검증하여 출제')
    d.tap('r'); d.wait(1.5)
    d.detect_boards(1)
    g = d.boards[0]
    d.wait(1.0); d.snap('12_puzzle_start')
    ok = True
    for step, (kind_expected, hints) in enumerate((('I', 3), ('O', 2), ('T', 3))):
        img = d.frame(time.perf_counter() + 0.1)
        grid = vision.read_grid(img, g)
        sp = detect_spawn(grid, max_dy=14)
        if not sp:
            d.log('puzzle_spawn_missing', step, grid=vision.grid_text(grid)); ok = False; break
        kind, piece, vis = sp
        B = to_board(grid, vis)
        d.caption(f'{kind} 블록 · H 키로 힌트 확인 (1단계: 목표 열 → 2단계: 목표 칸 금색 표시'
                  + (' → 3단계: 정답 조작)' if hints == 3 else ')'))
        target = frozenset()
        for h in range(hints):
            d.tap('h'); d.wait(1.15)
            target = vision.read_hint_cells(d.frame(), g) or target
        d.log('puzzle_target', kind, cells=sorted(target))
        if len(target) != 4:
            ok = False; break
        if step == 0:
            d.snap('13_puzzle_hint')
        d.caption(f'힌트의 금색 칸을 보고 {kind} 블록을 키보드(← → ↓ ↑/Z)로 이동' +
                  (' · 마지막 동작은 회전 → T-Spin' if kind == 'T' else ' 후 Space'))
        if not solve_piece(d, g, B, kind, target, need_spin=(kind == 'T'), start=piece):
            ok = False; break
        d.wait(1.2)
    d.caption('T-Spin Double 성공 · 퍼즐 성공 기록 갱신 (T-Spin 횟수 +1)' if ok else '퍼즐 풀이 실패')
    d.wait(3.5); d.snap('14_puzzle_success')
    d.seg_end()
    return ok


def scene_records(d):
    d.card('장면 8 · 기록 저장', '기록 창 확인 → 프로그램 종료 → 다시 실행해도 records.json에서 기록 유지')
    b = d.buttons
    d.seg('records')
    d.caption('☰ 기록 버튼 → 최고 점수 · 승패 · 퍼즐 성공 기록')
    d.click(b['records'], 'records'); d.wait(1.0)
    _center_dialog(d)
    d.wait(3.5); d.snap('15_records_window')
    _close_dialog(d)
    d.caption('창 닫기(Alt+F4) → 프로그램 종료')
    d.wait(0.8)
    d.inp.combo('alt', 'f4'); d.wait(0.25)
    d.seg_end()
    d.wait(1.0)
    d.end_session()
    d.card('프로그램 재실행', '다시 python run.py 실행 → 저장된 기록을 자동으로 불러옴')
    d.launch()
    d.seg('relaunch')
    d.caption('재실행 직후 메인 화면: 앞에서 저장된 경기·퍼즐 기록이 그대로 표시됨')
    d.wait(3.5); d.snap('16_relaunch_records')
    d.click(d.buttons['records'], 'records'); d.wait(1.0)
    _center_dialog(d)
    d.wait(3.0)
    _close_dialog(d)
    d.wait(0.8)
    d.seg_end()
    d.inp.combo('alt', 'f4'); d.wait(1.0)


def _dialog(d):
    ws = [h for h in winio.windows_of_pid(d.proc.pid) if h != d.hwnd]
    return ws[0] if ws else None


def _center_dialog(d):
    h = _dialog(d)
    if not h:
        return
    l, t, r, bt = winio.frame_bounds(d.hwnd)
    dl, dt_, dr, db = winio.window_rect(h)
    w, hh = dr - dl, db - dt_
    winio.user32.SetWindowPos(h, 0, l + (r - l - w) // 2, t + 260, 0, 0, 0x1 | 0x4)   # NOSIZE|NOZORDER
    time.sleep(0.4)


def _close_dialog(d):
    h = _dialog(d)
    if not h:
        return
    img = winio.grab_window(h)
    l, t, _, _ = winio.frame_bounds(h)
    m = vision.color_mask(img, vision.SURFACE2, 3)
    ys = np.where(m.sum(axis=1) > 20)[0]
    ys = ys[ys > img.shape[0] - 70]
    if len(ys):
        xs = np.where(m[ys[len(ys) // 2]])[0]
        d.inp.click(l + int(xs.mean()), t + int(ys.mean()), '닫기')
    else:
        d.inp.combo('alt', 'f4')
    time.sleep(0.8)


def main():
    rec_file = PROJ / 'save' / 'records.json'
    if rec_file.exists():
        raise SystemExit('save/records.json already exists -- move it away first for a clean demo')
    d = Demo()
    result = {}
    only = sys.argv[2].split(',') if len(sys.argv) > 2 else None      # rehearsal: run selected scenes
    scenes = [('solo', scene_solo), ('two', scene_two), ('versus', scene_versus), ('ai', scene_ai),
              ('coach', scene_coach), ('puzzle', scene_puzzle), ('records', scene_records)]
    try:
        scene_launch(d)
        for name, fn in scenes:
            if only is None or name in only:
                result[name] = fn(d)
        if only is not None and 'records' not in only:
            d.inp.combo('alt', 'f4'); time.sleep(1.0)
        d.end_session()
    except BaseException as exc:
        d.log('error', repr(exc))
        try:
            d.end_session()
        finally:
            if d.proc and d.proc.poll() is None:
                d.proc.terminate()
        raise
    finally:
        (OUT / 'events.json').write_text(json.dumps(d.log.events, ensure_ascii=False, indent=1), encoding='utf-8')
        (OUT / 'result.json').write_text(json.dumps(result, ensure_ascii=False, default=str), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, default=str))


if __name__ == '__main__':
    main()
