"""Dependency-free desktop frontend using Tkinter (Python standard library).

Threading model
  * The Tk main thread owns every widget and every Player object.
  * AI searches run on tetris.ai.AIWorker (one background thread). The GUI submits a deep copy of
    the board plus a token (kind, game id, player index, piece id) and later polls the result queue
    from its own timer; a result is applied only if its token still matches the current piece.
    Restart / mode change / stop increase game_id and invalidate queued jobs, so stale AI results
    can never be applied to a new game.
  * The main loop runs every 16 ms; it redraws only when the state changed (or at most every 250 ms
    for timers), using a static canvas layer (grid, panel frames) and a dynamic layer (blocks, text).
"""
from __future__ import annotations
import sys
import time
import tkinter as tk
from collections import deque
from pathlib import Path
from .engine import Match, Player, W, H, COLORS, ghost, cells
from .ai import AIWorker, preview_at, plan_actions
from .puzzles import generate, validate_puzzle, PuzzleSession, PuzzleGenerationError
from .storage import load_stats, save_stats, finish_match

BG = '#101522'; SURFACE = '#192234'; SURFACE2 = '#212d43'; EDGE = '#32415e'; GRID = '#1b2538'
WHITE = '#eaf1fa'; MUTED = '#a7b5c7'; ACCENT = '#4ad6c8'; GOLD = '#efc26f'; RED = '#f08389'; GREEN = '#7ee2a0'
FONT = 'Malgun Gothic' if sys.platform == 'win32' else 'Noto Sans CJK KR'
MODE_NAMES = {'solo': '1인용', 'two': '2인 동시 플레이', 'versus': '2인 대전', 'ai': '인간 vs AI', 'puzzle': 'AI T-Spin 퍼즐'}
DIFF_NAMES = {'easy': '쉬움', 'normal': '보통', 'hard': '어려움'}
P1_KEYS = {'left': 'left', 'right': 'right', 'up': 'cw', 'x': 'cw', 'z': 'ccw', 'down': 'soft', 'space': 'hard', 'c': 'hold'}
P2_KEYS = {'a': 'left', 'd': 'right', 'w': 'cw', 'e': 'ccw', 's': 'soft', 'f': 'hard', 'q': 'hold'}
SYSTEM_KEYS = {'p', 'r', 'escape', 'h'}
REPEATABLE = {'left', 'right', 'soft'}
DAS, ARR, SOFT_ARR = 0.17, 0.05, 0.035          # delayed auto shift / auto repeat rate (seconds)
AI_TIMING = {'easy': (0.45, 0.16), 'normal': (0.30, 0.10), 'hard': (0.20, 0.07)}   # think delay, per action
TICK_MS = 16
ACTION_LABEL = {'cw': '↻', 'ccw': '↺', 'left': '←', 'right': '→', 'hard': '⤓'}


class GameApp:
    def __init__(self, root, save_path=None, worker=None):
        self.root = root
        self.root.title('TETRIS · HUMAN × AI | Level 3')
        self.root.configure(bg=BG)
        self.root.geometry('1320x820'); self.root.minsize(900, 620)
        self.mode = tk.StringVar(master=root, value='ai')
        self.difficulty = tk.StringVar(master=root, value='normal')
        self.coach = tk.BooleanVar(master=root, value=True)
        self.match = None; self.session = None; self.puzzle = None
        self.players = []
        self.active = False; self.paused = False; self.finished = False
        self.game_id = 0; self.seed = int(time.time() * 1000) % 100000
        self.last_fall = []
        self.ai_plan = {}; self.coach_cache = {}; self.coach_pending = set(); self.preview_cache = {}
        self.held = {}; self.release_pending = {}
        self.hint_level = 0; self.hint_cells = None; self.puzzle_recorded = False
        self.result_text = ''
        self.dirty = True; self.last_draw = 0.0; self._static_sig = None
        self.draw_ms = deque(maxlen=3000); self.ai_ms = deque(maxlen=1000)
        self.message_var = tk.StringVar(master=root, value='모드를 선택하고 [시작]을 누르세요.')
        self.help_var = tk.StringVar(master=root, value='')
        self.save_path = Path(save_path) if save_path else Path(__file__).resolve().parents[1] / 'save' / 'records.json'
        self.records = load_stats(self.save_path)
        self.worker = worker or AIWorker()
        self.s = 1.0; self.cell = 26; self.layout = {}
        self.setup_ui(); self.bind_keys(); self.update_help()
        self.root.protocol('WM_DELETE_WINDOW', self.close)
        self.loop_id = self.root.after(TICK_MS, self.loop)

    # ------------------------------------------------------------------ widgets
    def button(self, parent, text, fn, accent=False):
        return tk.Button(parent, text=text, command=fn, bg=ACCENT if accent else SURFACE2,
                         fg=BG if accent else WHITE, activebackground='#6ceade', activeforeground=BG,
                         bd=0, relief='flat', cursor='hand2', font=(FONT, 10, 'bold'), padx=11, pady=7,
                         takefocus=0)

    def setup_ui(self):
        top = tk.Frame(self.root, bg=BG); top.pack(side='top', fill='x', padx=18, pady=(12, 4))
        tk.Label(top, text='TETRIS', font=('Arial', 21, 'bold'), bg=BG, fg=WHITE).pack(side='left')
        tk.Label(top, text='  HUMAN × AI  /  LEVEL 03', font=('Arial', 10, 'bold'), bg=BG, fg=ACCENT).pack(side='left', padx=(6, 14), pady=(8, 0))
        self.mode_buttons = {}
        for title, v in [('1인용', 'solo'), ('2인 동시', 'two'), ('2인 대전', 'versus'), ('인간 vs AI', 'ai'), ('T-SPIN 퍼즐', 'puzzle')]:
            rb = tk.Radiobutton(top, text=title, variable=self.mode, value=v, indicatoron=False, command=self.mode_changed,
                                bg=SURFACE2, fg=WHITE, selectcolor='#2e635f', activebackground='#2e635f', activeforeground=WHITE,
                                font=(FONT, 9, 'bold'), bd=0, padx=9, pady=7, takefocus=0)
            rb.pack(side='left', padx=2); self.mode_buttons[v] = rb
        tool = tk.Frame(self.root, bg=BG); tool.pack(fill='x', padx=18, pady=(2, 4))
        self.button(tool, '▶ 시작 / 재시작 (R)', self.start, True).pack(side='left', padx=(0, 5))
        self.button(tool, 'Ⅱ 일시정지 / 재개 (P)', self.toggle_pause).pack(side='left', padx=(0, 5))
        self.button(tool, '■ 종료 (Esc)', self.stop).pack(side='left', padx=(0, 5))
        self.button(tool, '? 퍼즐 힌트 (H)', self.puzzle_hint).pack(side='left', padx=(0, 5))
        self.button(tool, '☰ 기록', self.show_records).pack(side='left', padx=(0, 10))
        tk.Label(tool, text='AI 난이도', bg=BG, fg=MUTED, font=(FONT, 10)).pack(side='left')
        self.diff_buttons = {}
        for name, val in [('쉬움', 'easy'), ('보통', 'normal'), ('어려움', 'hard')]:
            rb = tk.Radiobutton(tool, text=name, variable=self.difficulty, value=val, indicatoron=False,
                                command=self.difficulty_changed, bg=SURFACE2, fg=WHITE, selectcolor='#2e635f',
                                activebackground='#2e635f', activeforeground=WHITE, font=(FONT, 9), bd=0, padx=9, pady=6, takefocus=0)
            rb.pack(side='left', padx=2); self.diff_buttons[val] = rb
        tk.Checkbutton(tool, text='AI 도우미', variable=self.coach, bg=BG, fg=WHITE, selectcolor=SURFACE2,
                       activebackground=BG, activeforeground=WHITE, font=(FONT, 10), takefocus=0,
                       command=self.mark_dirty).pack(side='left', padx=10)
        bottom = tk.Frame(self.root, bg=SURFACE, highlightbackground=EDGE, highlightthickness=1)
        bottom.pack(side='bottom', fill='x', padx=18, pady=(2, 12))
        tk.Label(bottom, textvariable=self.message_var, bg=SURFACE, fg=ACCENT, anchor='w',
                 font=(FONT, 11, 'bold')).pack(fill='x', padx=12, pady=(7, 0))
        tk.Label(bottom, textvariable=self.help_var, bg=SURFACE, fg=MUTED, anchor='w',
                 font=(FONT, 9)).pack(fill='x', padx=12, pady=(1, 7))
        self.canvas = tk.Canvas(self.root, bg=BG, highlightthickness=0, width=1280, height=640)
        self.canvas.pack(fill='both', expand=True, padx=10, pady=2)
        self.canvas.bind('<Configure>', lambda e: self.mark_dirty())

    def bind_keys(self):
        self.root.bind_all('<KeyPress>', self.key_down)
        self.root.bind_all('<KeyRelease>', self.key_up)
        self.root.bind('<FocusOut>', lambda e: self.held.clear())

    def update_help(self):
        mode = self.mode.get()
        if mode in ('two', 'versus'):
            self.help_var.set('P1: ← → 이동 · ↑/X 회전 · Z 반대회전 · ↓ 빠르게 · Space 즉시 낙하 · C Hold    |    '
                              'P2: A D 이동 · W 회전 · E 반대회전 · S 빠르게 · F 즉시 낙하 · Q Hold    |    P 일시정지 · R 재시작 · Esc 종료')
        elif mode == 'puzzle':
            self.help_var.set('← → 이동 · ↑/X 회전 · Z 반대회전 · ↓ 한 칸 내리기 · Space 고정 · H 힌트(3단계) · R 새 퍼즐 · '
                              '퍼즐은 바닥에 닿아도 자동 고정되지 않음')
        else:
            self.help_var.set('← → 이동 · ↑/X 회전 · Z 반대회전 · ↓ 빠르게 · Space 즉시 낙하 · C Hold · '
                              'P 일시정지/재개 · R 재시작 · Esc 종료')

    def mark_dirty(self):
        self.dirty = True

    # ------------------------------------------------------------------ game control
    def _record_abort(self):
        """A match left before it was decided is stored as 'aborted' (no win/loss)."""
        if self.active and not self.finished and self.match is not None:
            finish_match(self.records, self.players, None, self.match.mode, aborted=True)
            save_stats(self.save_path, self.records)

    def _reset_runtime(self):
        self.game_id += 1
        self.worker.invalidate()
        self.ai_plan.clear(); self.coach_cache.clear(); self.coach_pending.clear(); self.preview_cache.clear()
        self.held.clear(); self.release_pending.clear()
        self.hint_level = 0; self.hint_cells = None; self.puzzle_recorded = False; self.result_text = ''

    def mode_changed(self):
        self._record_abort()
        self._reset_runtime()
        self.active = False; self.finished = False; self.paused = False
        self.players = []; self.match = None; self.session = None; self.puzzle = None
        self.message_var.set('선택한 모드: ' + MODE_NAMES[self.mode.get()] + ' · [시작] 또는 R 키를 누르세요.')
        self.update_help(); self.mark_dirty()

    def difficulty_changed(self):
        d = DIFF_NAMES[self.difficulty.get()]
        if self.active and self.mode.get() == 'ai':
            self.message_var.set(f'AI 난이도 → {d} (다음 블록부터 적용)')
        elif self.mode.get() == 'puzzle':
            self.message_var.set(f'퍼즐 난이도 → {d} · R 키로 새 퍼즐을 생성하세요.')
        else:
            self.message_var.set(f'AI 난이도: {d}')
        self.mark_dirty()

    def start(self):
        self._record_abort()
        self._reset_runtime()
        mode = self.mode.get(); diff = self.difficulty.get()
        self.seed = (self.seed * 7919 + 17) % 999983
        self.paused = False; self.finished = False
        if mode == 'puzzle':
            try:
                p = generate(self.seed, diff)
                if not validate_puzzle(p):
                    raise PuzzleGenerationError('생성된 퍼즐이 검증을 통과하지 못했습니다.')
            except PuzzleGenerationError as exc:
                self.active = False; self.players = []; self.session = None
                self.message_var.set('퍼즐 생성 실패: ' + str(exc) + ' 다시 시도하세요.')
                self.mark_dirty(); return
            self.puzzle = p; self.match = None
            self.players = [Player('P1', seed=self.seed)]
            self.session = PuzzleSession(p, self.players[0])
            self.records['puzzles_attempted'] += 1; save_stats(self.save_path, self.records)
            self.message_var.set(f'AI가 생성·검증한 {DIFF_NAMES[diff]} 퍼즐: {p.note}')
        else:
            self.match = Match(mode, self.seed, diff); self.session = None; self.puzzle = None
            self.players = self.match.players
            self.message_var.set(f'{MODE_NAMES[mode]} 시작!' + (f'  AI 난이도: {DIFF_NAMES[diff]}' if mode == 'ai' else '')
                                 + '  ·  P 일시정지 · R 재시작')
        self.active = True
        now = time.monotonic()
        self.last_fall = [now] * len(self.players)
        self.update_help(); self.mark_dirty()

    def toggle_pause(self):
        if not self.active or self.finished:
            return
        self.paused = not self.paused
        self.held.clear()
        if not self.paused:
            now = time.monotonic()
            self.last_fall = [now] * len(self.players)
            for plan in self.ai_plan.values():
                plan['ready_at'] = now + 0.15
        self.message_var.set('일시정지 · P 키로 재개' if self.paused else '재개했습니다.')
        self.mark_dirty()

    def stop(self):
        if not self.active:
            return
        if not self.finished:
            self._record_abort()
        self._reset_runtime()
        self.active = False; self.paused = False; self.finished = True
        self.message_var.set('게임을 종료했습니다. [시작] 또는 R 키로 다시 플레이하세요.')
        self.mark_dirty()

    def close(self):
        try:
            self._record_abort()
        finally:
            self.worker.close()
            try:
                self.root.after_cancel(self.loop_id)
            except Exception:
                pass
            # release Tk variables while the interpreter still exists (avoids Variable.__del__ errors)
            for name in ('mode', 'difficulty', 'coach', 'message_var', 'help_var'):
                setattr(self, name, None)
            self.root.destroy()

    # ------------------------------------------------------------------ input
    def _keyname(self, event):
        k = (event.keysym or '').lower()
        if k in P1_KEYS or k in P2_KEYS or k in SYSTEM_KEYS:
            return k
        code = getattr(event, 'keycode', 0) or 0
        if sys.platform == 'win32' and 65 <= code <= 90:      # letters typed while a Korean IME is active
            return chr(code).lower()
        return k

    def _binding(self, key):
        if not self.players:
            return None
        if key in P1_KEYS:
            return 0, P1_KEYS[key]
        if key in P2_KEYS and len(self.players) > 1 and not self.players[1].is_ai:
            return 1, P2_KEYS[key]
        return None

    def playable(self):
        return self.active and not self.paused and not self.finished and bool(self.players)

    def key_down(self, event):
        key = self._keyname(event)
        if key in self.release_pending:          # X11 auto-repeat sends release+press pairs
            del self.release_pending[key]
        if key in self.held:                      # OS auto-repeat: our own DAS handles repetition
            return
        if key in SYSTEM_KEYS:
            self.held[key] = None
            {'p': self.toggle_pause, 'r': self.start, 'escape': self.stop, 'h': self.puzzle_hint}[key]()
            return
        b = self._binding(key)
        if b is None or not self.playable():
            return
        idx, action = b
        now = time.monotonic()
        self.held[key] = {'idx': idx, 'action': action, 't0': now, 'last': now} if action in REPEATABLE else None
        self.handle_action(idx, action)

    def key_up(self, event):
        key = self._keyname(event)
        if key in self.held:
            self.release_pending[key] = time.monotonic()

    def _process_keys(self, now):
        for key, t in list(self.release_pending.items()):
            if now - t >= 0.03:
                self.held.pop(key, None); del self.release_pending[key]
        for key, h in list(self.held.items()):
            if not h or key in self.release_pending:
                continue
            rate = SOFT_ARR if h['action'] == 'soft' else ARR
            if now - h['t0'] >= DAS and now - h['last'] >= rate:
                h['last'] = now
                self.handle_action(h['idx'], h['action'])

    def handle_action(self, index, action):
        if index >= len(self.players):
            return
        p = self.players[index]
        if p.over or p.active is None or not self.playable():
            return
        puzzle = self.session is not None
        if action == 'left':
            p.move(-1, 0)
        elif action == 'right':
            p.move(1, 0)
        elif action == 'cw':
            p.rotate(1)
        elif action == 'ccw':
            p.rotate(-1)
        elif action == 'soft':
            if puzzle:
                p.move(0, 1)
            elif p.soft_drop():
                self.last_fall[index] = time.monotonic()
        elif action == 'hold':
            if not puzzle and p.swap_hold():
                self.last_fall[index] = time.monotonic()
        elif action == 'hard':
            if puzzle:
                self.puzzle_lock()
            else:
                self.process_lock(index, p.hard_drop())
                self.last_fall[index] = time.monotonic()
        self.mark_dirty()

    # ------------------------------------------------------------------ rules glue
    def process_lock(self, index, result):
        if result is None or self.match is None:
            return
        sent = self.match.after_lock(index, result)
        p = self.players[index]
        parts = []
        if result.label and result.label != 'LOCK':
            parts.append(f'{p.name} {result.label}')
        if result.cancelled:
            parts.append(f'{p.name} 공격 상쇄 {result.cancelled}줄')
        if sent:
            parts.append(f'{p.name} → {self.players[1 - index].name} 공격 +{sent}줄')
        if result.received:
            parts.append(f'{p.name} 방해 줄 {result.received}줄 수신')
        if parts:
            self.message_var.set('  ·  '.join(parts))
        self.check_end()
        self.mark_dirty()

    def check_end(self):
        if self.match is None or self.finished or not self.match.check_end():
            return
        self.finished = True
        self.held.clear()
        m = self.match
        finish_match(self.records, self.players, m.winner, m.mode)
        save_stats(self.save_path, self.records)
        if m.mode == 'solo':
            self.result_text = f'GAME OVER · 점수 {self.players[0].score:,}'
        elif m.winner:
            self.result_text = f'{m.winner} 승리!  ({m.reason})'
        else:
            self.result_text = f'무승부  ({m.reason})'
        self.message_var.set(self.result_text + '  ·  기록 저장 완료 · R 키로 다시 시작')
        self.mark_dirty()

    def puzzle_lock(self):
        res = self.session.lock(hard=True)
        if res is None:
            return
        n, spin = res
        self.hint_level = 0; self.hint_cells = None
        s = self.session
        if s.complete:
            self.finished = True
            if not self.puzzle_recorded:
                self.puzzle_recorded = True
                self.records['puzzles_solved'] += 1
                save_stats(self.save_path, self.records)
            self.result_text = f'퍼즐 성공! T-Spin {n}줄 제거 · 블록 {s.moves}개 사용'
            self.message_var.set(self.result_text + ' · R 키로 새 퍼즐')
        elif s.failed:
            self.finished = True
            self.result_text = '퍼즐 실패' + (' (T-Spin 아님)' if not spin else f' (T-Spin {n}줄 < 목표 {s.puzzle.target_lines}줄)')
            self.message_var.set(self.result_text + ' · R 키로 새 문제에 도전하세요.')
        else:
            self.message_var.set(f'준비 블록 배치 완료 ({s.moves}/{len(s.puzzle.sequence)}) · 다음: {s.puzzle.sequence[s.moves]}')
        self.mark_dirty()

    def puzzle_hint(self):
        if self.session is None or not self.active or self.finished:
            return
        self.hint_level = min(3, self.hint_level + 1)
        text, sq = self.session.hint(self.hint_level)
        self.hint_cells = sq
        self.message_var.set(text)
        self.mark_dirty()

    # ------------------------------------------------------------------ AI glue
    def _apply_worker_results(self):
        for token, best, ms in self.worker.poll():
            self.ai_ms.append(ms)
            kind, gid, idx, pid = token
            if gid != self.game_id or idx >= len(self.players) or self.players[idx].piece_id != pid:
                continue                              # stale: game restarted or piece already locked
            if kind == 'ai':
                plan = self.ai_plan.get(idx)
                if plan and plan['token'] == token:
                    plan['best'] = best; plan['ms'] = ms
                    p = self.players[idx]
                    plan['actions'] = deque(plan_actions(p.board, p.active, best.piece) if best else ['hard'])
                    self.mark_dirty()
            else:
                self.coach_cache[idx] = (token, best)
                self.coach_pending.discard(token)
                self.mark_dirty()

    def _ai_step(self, i, p, now):
        token = ('ai', self.game_id, i, p.piece_id)
        plan = self.ai_plan.get(i)
        diff = self.difficulty.get()
        if plan is None or plan['token'] != token:
            self.worker.submit(token, p.board, p.active.kind, p.next[0] if p.next else None, diff)
            think = max(0.05, AI_TIMING[diff][0] - (p.level - 1) * 0.015)
            self.ai_plan[i] = {'token': token, 'best': None, 'actions': None, 'ms': None,
                               'ready_at': now + think, 'difficulty': diff}
            return
        if plan['actions'] is None or now < plan['ready_at']:
            return
        action = plan['actions'].popleft() if plan['actions'] else 'hard'
        plan['ready_at'] = now + AI_TIMING[plan['difficulty']][1]
        if action == 'hard':
            self.process_lock(i, p.hard_drop())
            self.last_fall[i] = now
        else:
            ok = p.rotate(1 if action == 'cw' else -1) if action in ('cw', 'ccw') else p.move(-1 if action == 'left' else 1, 0)
            if not ok:                               # blocked by the stack: drop where it is (real rules)
                plan['actions'] = deque(['hard'])
        self.mark_dirty()

    def _request_coach(self):
        if not self.coach.get() or self.session is not None:
            return
        for i, p in enumerate(self.players):
            if p.is_ai or p.over or p.active is None:
                continue
            token = ('coach', self.game_id, i, p.piece_id)
            cached = self.coach_cache.get(i)
            if (cached and cached[0] == token) or token in self.coach_pending:
                continue
            self.coach_pending.add(token)
            self.worker.submit(token, p.board, p.active.kind, p.next[0] if p.next else None, 'normal')

    def coach_best(self, i):
        p = self.players[i]
        cached = self.coach_cache.get(i)
        if cached and cached[0] == ('coach', self.game_id, i, p.piece_id):
            return cached[1]
        return None

    def preview(self, i):
        """Evaluation of the current position (cached per piece position; cheap single evaluation)."""
        p = self.players[i]
        if p.active is None:
            return None
        a = p.active
        key = (self.game_id, p.piece_id, a.x, a.y, a.rot, a.rotated_last, p.version if self.session else 0)
        hit = self.preview_cache.get(i)
        if hit and hit[0] == key:
            return hit[1]
        cand = preview_at(p.board, a)
        self.preview_cache[i] = (key, cand)
        return cand

    # ------------------------------------------------------------------ main loop
    def loop(self):
        if self.mode is None:          # window closed
            return
        try:
            self._apply_worker_results()
            now = time.monotonic()
            if self.playable():
                self._process_keys(now)
                for i, p in enumerate(self.players):
                    if p.over or p.active is None or not self.playable():
                        continue
                    if p.is_ai:
                        self._ai_step(i, p, now)
                        if p.active is None or p.over:
                            continue
                    if now - self.last_fall[i] >= p.gravity_delay():
                        self.last_fall[i] = now
                        if self.session is not None:
                            if p.move(0, 1):          # puzzle: gravity never locks (careful rotations)
                                self.mark_dirty()
                        else:
                            res = p.step()
                            self.mark_dirty()
                            if res is not None:
                                self.process_lock(i, res)
                self._request_coach()
                self.check_end()
            if self.dirty or now - self.last_draw > 0.25:
                self.redraw()
        finally:
            if self.mode is not None and self.root.winfo_exists():
                self.loop_id = self.root.after(TICK_MS, self.loop)

    # ------------------------------------------------------------------ drawing helpers
    def T(self, x, y, text, size=11, color=WHITE, bold=False, anchor='nw', tag='dyn', width=None):
        kw = {'width': width} if width else {}
        self.canvas.create_text(x, y, text=text, fill=color, anchor=anchor, tags=tag,
                                font=(FONT, max(7, int(round(size * self.s))), 'bold' if bold else 'normal'), **kw)

    def block(self, x, y, color, cell, ghost_block=False, tag='dyn'):
        c = self.canvas
        if ghost_block:
            c.create_rectangle(x + 2, y + 2, x + cell - 2, y + cell - 2, outline=color, width=2, tags=tag)
        else:
            c.create_rectangle(x + 1, y + 1, x + cell - 1, y + cell - 1, fill=color, outline='#0c1723', tags=tag)
            if cell >= 12:
                c.create_line(x + 3, y + 3, x + cell - 3, y + 3, fill='#ffffff', tags=tag)

    def outline_cells(self, bx, by, squares, color, dash=(3, 2), width=2):
        cell = self.cell
        for x, y in squares:
            if y >= 0:
                self.canvas.create_rectangle(bx + x * cell + 3, by + y * cell + 3, bx + (x + 1) * cell - 3,
                                             by + (y + 1) * cell - 3, outline=color, width=width, dash=dash, tags='dyn')

    def mini_piece(self, x, y, kind, size):
        if kind is None:
            return
        sq = cells(kind, 0)
        xs = [a for a, b in sq]; ys = [b for a, b in sq]
        for dx, dy in sq:
            self.block(x + (dx - min(xs)) * size, y + (dy - min(ys)) * size, COLORS[kind], size)

    def panel(self, x, y, w, h, title):
        s = self.s
        self.canvas.create_rectangle(x, y, x + w, y + h, fill=SURFACE, outline=EDGE, tags='static')
        self.T(x + 12 * s, y + 9 * s, title, 11, WHITE, True, tag='static')

    # ------------------------------------------------------------------ layout & redraw
    def compute_layout(self, cw, ch):
        n = len(self.players)
        two = n > 1
        base_w = 1110 if two else 850
        s = max(.5, min(1.6, min(cw / base_w, ch / 640)))
        self.s = s; self.cell = cell = max(10, int(26 * s))
        bw, bh = cell * W, cell * H
        top = int((78 if two else 56) * s)        # 2-board layout starts at the left edge: keep clear of the mode title
        L = {'top': top, 'bw': bw, 'bh': bh, 'right': None}
        if two:
            side_w = int(245 * s); gi = int(16 * s); gm = int(40 * s)
            total = 2 * (bw + gi + side_w) + gm
            x0 = max(int(8 * s), (cw - total) // 2)
            L['boards'] = [(x0, top), (x0 + bw + gi + side_w + gm, top)]
            L['sides'] = [(bx + bw + gi, top, side_w) for bx, _ in L['boards']]
        else:
            side_w = int(270 * s); rw = int(250 * s); gi = int(20 * s); gr = int(16 * s)
            total = bw + gi + side_w + gr + rw
            x0 = max(int(8 * s), (cw - total) // 2)
            L['boards'] = [(x0, top)]
            L['sides'] = [(x0 + bw + gi, top, side_w)]
            L['right'] = (x0 + bw + gi + side_w + gr, top, rw)
        self.layout = L
        return L

    def redraw(self):
        t0 = time.perf_counter()
        c = self.canvas
        if not c.winfo_exists():
            return
        cw = max(c.winfo_width(), 300); ch = max(c.winfo_height(), 300)
        if self.mode is None:
            return
        sig = (cw, ch, len(self.players), self.mode.get() if self.players else None, bool(self.coach.get()),
               tuple(p.is_ai for p in self.players), self.session is not None)
        if sig != self._static_sig:
            c.delete('all')
            self._static_sig = sig
            self.compute_layout(cw, ch)
            self.draw_static(cw, ch)
        else:
            c.delete('dyn')
        self.draw_dynamic(cw, ch)
        self.last_draw = time.monotonic(); self.dirty = False
        self.draw_ms.append((time.perf_counter() - t0) * 1000)

    def side_bottom_title(self, p):
        if p.is_ai:
            return 'AI 자동 판단'
        if self.coach.get():
            return 'AI 도우미 · 배치 평가'
        return '조작 정보'

    def draw_static(self, cw, ch):
        s = self.s; L = self.layout; c = self.canvas
        if not self.players:
            return
        for i, (bx, by) in enumerate(L['boards']):
            bw, bh = L['bw'], L['bh']
            c.create_rectangle(bx - 7 * s, by - 7 * s, bx + bw + 7 * s, by + bh + 7 * s, fill=SURFACE, outline=EDGE, width=2, tags='static')
            c.create_rectangle(bx, by, bx + bw, by + bh, fill='#111a2a', outline='', tags='static')
            for x in range(1, W):
                c.create_line(bx + x * self.cell, by, bx + x * self.cell, by + bh, fill=GRID, tags='static')
            for y in range(1, H):
                c.create_line(bx, by + y * self.cell, bx + bw, by + y * self.cell, fill=GRID, tags='static')
            sx, sy, sw = L['sides'][i]
            p = self.players[i]
            self.panel(sx, sy, sw, 118 * s, 'NEXT / HOLD')
            self.panel(sx, sy + 128 * s, sw, 112 * s, 'STATUS')
            self.panel(sx, sy + 250 * s, sw, L['bh'] - 250 * s, self.side_bottom_title(p))
        if L['right']:
            rx, ry, rw = L['right']
            self.panel(rx, ry, rw, 196 * s, '저장된 기록 · records.json')
            self.panel(rx, ry + 206 * s, rw, L['bh'] - 206 * s, 'T-SPIN 챌린지' if self.session else '확장 기능 · 조작')

    def draw_dynamic(self, cw, ch):
        s = self.s
        status = '일시정지' if self.paused else '게임 진행 중' if self.active and not self.finished else '대기 / 종료'
        self.T(16 * s, 8 * s, MODE_NAMES[self.mode.get()], 17, WHITE, True)
        extra = f'   AI 난이도: {DIFF_NAMES[self.difficulty.get()]}' if self.mode.get() in ('ai', 'puzzle') else ''
        self.T(cw - 16 * s, 12 * s, '●  ' + status + extra, 10, GOLD if self.paused else ACCENT, anchor='ne')
        if not self.players:
            self.draw_idle(cw, ch); return
        L = self.layout
        for i, p in enumerate(self.players):
            bx, by = L['boards'][i]
            self.draw_player(i, p, bx, by)
            sx, sy, sw = L['sides'][i]
            self.draw_side(i, p, sx, sy, sw)
        if L['right']:
            rx, ry, rw = L['right']
            self.draw_records(rx, ry, rw)
            if self.session:
                self.draw_puzzle_panel(rx, ry + 206 * s, rw)
            else:
                self.draw_feature_panel(rx, ry + 206 * s, rw)
        if self.paused or (self.finished and self.result_text):
            bx0 = L['boards'][0][0]; bx1 = L['boards'][-1][0] + L['bw']
            cx = (bx0 + bx1) / 2 if len(self.players) > 1 else bx0 + L['bw'] / 2
            cy = L['top'] + L['bh'] * .42
            text = 'PAUSED' if self.paused else self.result_text
            tid = self.canvas.create_text(cx, cy, text=text, fill=GOLD, anchor='center', tags='dyn',
                                          font=(FONT, max(7, int(round(15 * s))), 'bold'))
            x0, _, x1, _ = self.canvas.bbox(tid)          # measured width: the box always fits the text
            w = max(L['bw'] * .9, (x1 - x0) + 40 * s)
            self.canvas.create_rectangle(cx - w / 2, cy - 30 * s, cx + w / 2, cy + 30 * s, fill='#0d1320', outline=GOLD, width=2, tags='dyn')
            self.canvas.tag_raise(tid)

    def draw_player(self, i, p, bx, by):
        s = self.s; cell = self.cell; L = self.layout
        for y, row in enumerate(p.board):
            for x, v in enumerate(row):
                if v:
                    self.block(bx + x * cell, by + y * cell, COLORS.get(v, '#758397'), cell)
        if p.active is not None and not p.over:
            sh = ghost(p.board, p.active)
            for x, y in sh.squares():
                if y >= 0:
                    self.block(bx + x * cell, by + y * cell, '#73839d', cell, ghost_block=True)
            if p.is_ai:
                plan = self.ai_plan.get(i)
                if plan and plan.get('best') and plan['token'][3] == p.piece_id:
                    self.outline_cells(bx, by, plan['best'].piece.squares(), GOLD)
            elif self.session is None and self.coach.get():
                best = self.coach_best(i)
                if best:
                    self.outline_cells(bx, by, best.piece.squares(), ACCENT)
            if self.session is not None and self.hint_cells:
                self.outline_cells(bx, by, self.hint_cells, GOLD, dash=(), width=3)
            for x, y in p.active.squares():
                if y >= 0:
                    self.block(bx + x * cell, by + y * cell, COLORS[p.active.kind], cell)
        role = f'AI · {DIFF_NAMES[self.difficulty.get()]}' if p.is_ai else 'PLAYER'
        self.T(bx, by - 34 * s, f'{p.name}   {role}', 14, ACCENT if p.is_ai else WHITE, True)
        self.T(bx + L['bw'], by - 31 * s, f'{p.score:,} PTS  ·  LV.{p.level}', 10, MUTED, anchor='ne')
        self.T(bx, by + L['bh'] + 11 * s, f'제거 {p.lines}줄 · T-Spin {p.spins}회 · 보낸 공격 {p.total_attacks}줄', 9, MUTED)
        if p.pending:
            self.T(bx + L['bw'], by + L['bh'] + 11 * s, f'받을 공격 {p.pending}줄', 10, RED, True, anchor='ne')
            h = min(H, p.pending) * cell
            self.canvas.create_rectangle(bx - 6 * s, by + L['bh'] - h, bx - 2 * s, by + L['bh'], fill=RED, outline='', tags='dyn')
        if self.finished and self.match and len(self.players) > 1 and self.match.winner == p.name:
            self.canvas.create_rectangle(bx, by + 8 * s, bx + L['bw'], by + 46 * s, fill='#1f4b3a', outline=GREEN, tags='dyn')
            self.T(bx + L['bw'] / 2, by + 27 * s, 'WINNER', 15, GREEN, True, anchor='center')
        if p.over:
            self.canvas.create_rectangle(bx, by + L['bh'] * .58, bx + L['bw'], by + L['bh'] * .58 + 52 * s, fill='#472334', outline=RED, tags='dyn')
            self.T(bx + L['bw'] / 2, by + L['bh'] * .58 + 26 * s, 'GAME OVER', 16, WHITE, True, anchor='center')

    def draw_side(self, i, p, x, y, w):
        s = self.s
        self.T(x + 12 * s, y + 34 * s, 'NEXT', 9, MUTED)
        if p.next:
            self.mini_piece(x + 14 * s, y + 56 * s, p.next[0], int(15 * s))
            for k, kind in enumerate(list(p.next)[1:3]):
                self.mini_piece(x + (82 + k * 46) * s, y + 64 * s, kind, int(9 * s))
        self.T(x + w - 92 * s, y + 34 * s, 'HOLD', 9, MUTED)
        if p.held:
            self.mini_piece(x + w - 88 * s, y + 58 * s, p.held, int(14 * s))
        elif self.session:
            self.T(x + w - 92 * s, y + 60 * s, '퍼즐 사용 불가', 8, MUTED)
        y2 = y + 128 * s
        self.T(x + 12 * s, y2 + 34 * s, f'SCORE  {p.score:,}', 12, GOLD, True)
        self.T(x + 12 * s, y2 + 58 * s, f'LINES  {p.lines}    LEVEL  {p.level}    COMBO {max(0, p.combo)}', 9, MUTED)
        self.T(x + 12 * s, y2 + 79 * s, '최근: ' + (p.last_action or '—'), 9, WHITE)
        if not p.is_ai and self.session is None:
            self.T(x + 12 * s, y2 + 97 * s, f'낙하 간격 {p.gravity_delay():.2f}s / 칸', 8, MUTED)
        y3 = y + 250 * s
        if p.is_ai:
            self.draw_ai_panel(i, p, x, y3, w)
        elif self.coach.get():
            self.draw_coach(i, p, x, y3, w)
        else:
            self.T(x + 12 * s, y3 + 40 * s, 'AI 도우미가 꺼져 있습니다.\n상단 체크박스로 켤 수 있습니다.', 9, MUTED)

    def draw_ai_panel(self, i, p, x, y, w):
        s = self.s
        plan = self.ai_plan.get(i)
        self.T(x + 12 * s, y + 34 * s, f'난이도: {DIFF_NAMES[(plan or {}).get("difficulty", self.difficulty.get())]}'
               + ('  (다음 블록 2단계 탐색)' if (plan or {}).get('difficulty', self.difficulty.get()) == 'hard' else ''), 9, MUTED)
        if p.over or not plan or plan['token'][3] != p.piece_id:
            return
        best = plan.get('best')
        if best is None:
            self.T(x + 12 * s, y + 56 * s, '탐색 중… (백그라운드 스레드)', 10, ACCENT, True); return
        self.T(x + 12 * s, y + 54 * s, f'목표 x={best.piece.x} · 회전={best.piece.rot} · 평가 {best.score:+.1f}', 10, GOLD, True)
        off = 78
        for label, val in best.parts.items():
            self.T(x + 14 * s, y + off * s, label, 9, MUTED)
            self.T(x + w - 14 * s, y + off * s, f'{val:+.1f}', 9, ACCENT if val >= 0 else RED, anchor='ne')
            off += 19
        acts = ' '.join(ACTION_LABEL.get(a, a) for a in (plan.get('actions') or []))
        self.T(x + 12 * s, y + (off + 6) * s, f'계산 {plan["ms"]:.1f} ms · 남은 동작 {acts or "-"}', 8, MUTED)

    def draw_coach(self, i, p, x, y, w):
        s = self.s
        if p.over or p.active is None:
            return
        hint = self.preview(i)
        if hint is None:
            self.T(x + 12 * s, y + 36 * s, '현재 위치에서는 고정할 수 없습니다.', 9, MUTED); return
        self.T(x + 12 * s, y + 32 * s, f'현재 위치 평가  {hint.score:+.1f}', 11, GOLD, True)
        off = 56
        for title, value in hint.parts.items():
            self.T(x + 14 * s, y + off * s, title, 9, MUTED)
            self.T(x + w - 14 * s, y + off * s, f'{value:+.1f}', 9, ACCENT if value >= 0 else RED, anchor='ne')
            off += 18
        spin_txt = f'실제 T-Spin 판정: {"성립" if hint.spin else "아님"} · 예상 제거 {hint.lines}줄'
        self.T(x + 12 * s, y + (off + 2) * s, spin_txt, 9, GREEN if hint.spin else WHITE)
        off += 22
        if self.session is None:
            best = self.coach_best(i)
            txt = (f'AI 추천: x={best.piece.x}, 회전={best.piece.rot} · 평가 {best.score:+.1f}' if best
                   else 'AI 추천 계산 중…' if self.playable() else 'AI 추천: 게임 진행 중에만 계산')
            self.T(x + 12 * s, y + off * s, txt, 10, ACCENT, True)
            off += 21
        self.T(x + 12 * s, y + off * s, '※ AI 휴리스틱 점수 (게임 점수와 별개)', 8, MUTED)

    def draw_records(self, x, y, w):
        s = self.s; r = self.records
        self.T(x + 12 * s, y + 32 * s, f'완료 경기 {r["matches"]} · 중단 {r.get("aborted", 0)} · 퍼즐 {r["puzzles_solved"]}/{r["puzzles_attempted"]}', 9, MUTED)
        off = 54
        for name in ('P1', 'P2', 'AI'):
            self.T(x + 12 * s, y + off * s, name, 10, ACCENT if name == 'AI' else WHITE, True)
            self.T(x + 46 * s, y + off * s, f'최고 {r["best_score"].get(name, 0):,}', 9, GOLD)
            self.T(x + 46 * s, y + (off + 16) * s,
                   f'승 {r["wins"].get(name, 0)} · 패 {r["losses"].get(name, 0)} · {r["lines"].get(name, 0)}줄', 9, MUTED)
            off += 42

    def draw_feature_panel(self, x, y, w):
        s = self.s
        lines = ['SRS 회전 + Wall Kick', 'T-Spin 판정 · 공격 보너스', 'Combo / Back-to-Back / 상쇄',
                 'AI 도우미: 평가 근거 시각화', '청록 점선 = AI 추천 위치', '회색 테두리 = 낙하 예상(Ghost)',
                 '↓/←/→ 길게 누르면 자동 반복', '전적은 종료 시 자동 저장']
        for k, line in enumerate(lines):
            self.T(x + 14 * s, y + (36 + k * 22) * s, '• ' + line, 9, MUTED)

    def draw_puzzle_panel(self, x, y, w):
        s = self.s; ses = self.session; pz = ses.puzzle
        self.T(x + 12 * s, y + 34 * s, f'난이도: {DIFF_NAMES[pz.difficulty]}  ·  목표 T-Spin {pz.target_lines}줄', 10, ACCENT, True)
        seq = '  →  '.join(('[' + k + ']') if j == ses.moves and not ses.done else k for j, k in enumerate(pz.sequence))
        self.T(x + 12 * s, y + 60 * s, '블록 순서: ' + seq, 10, WHITE)
        self.T(x + 12 * s, y + 84 * s, f'사용 {ses.moves} / {len(pz.sequence)}  ·  남은 블록 {max(0, ses.remaining)}', 10, WHITE)
        state = '성공' if ses.complete else '실패' if ses.failed else '진행 중'
        self.T(x + 12 * s, y + 108 * s, '상태: ' + state, 10, GREEN if ses.complete else RED if ses.failed else GOLD, True)
        self.T(x + 12 * s, y + 132 * s, f'힌트 단계 {self.hint_level}/3  (H 키)', 9, MUTED)
        self.T(x + 12 * s, y + 154 * s, '검증: BFS로 실제 키 입력 경로 확인\n(이동·회전·SRS 킥 포함)', 8, MUTED, width=w - 24 * s)
        self.T(x + 12 * s, y + 196 * s, pz.note, 8, MUTED, width=w - 24 * s)

    def draw_idle(self, cw, ch):
        s = self.s = max(.6, min(1.4, min(cw / 900, ch / 600)))
        w = 760 * s; x = (cw - w) / 2; y = 50 * s
        self.canvas.create_rectangle(x, y, x + w, y + 470 * s, fill=SURFACE, outline=EDGE, tags='dyn')
        self.T(x + 20 * s, y + 16 * s, '게임 모드를 선택한 뒤 [시작]을 누르세요', 14, WHITE, True)
        lines = ['필수: 1인용 · 2인 동시 플레이 · 2인 대전(공격) · 인간 vs AI(공격)',
                 'AI 난이도: 쉬움(단순 평가) · 보통(7개 항목 평가) · 어려움(다음 블록 2단계 탐색)',
                 '확장: SRS·T-Spin·Combo/B2B 공격 · AI 도우미(평가 근거 표시) · AI 생성 T-Spin 퍼즐',
                 'AI 연산은 백그라운드 스레드에서 실행되어 화면과 입력이 멈추지 않습니다.']
        for k, line in enumerate(lines):
            self.T(x + 24 * s, y + (62 + k * 34) * s, '• ' + line, 11, MUTED)
        r = self.records
        self.T(x + 24 * s, y + 210 * s, '저장된 기록 (재실행 시 자동 불러오기)', 12, GOLD, True)
        self.T(x + 24 * s, y + 240 * s, f'완료 경기 {r["matches"]}회 · 중단 {r.get("aborted", 0)}회 · 퍼즐 성공 {r["puzzles_solved"]}/{r["puzzles_attempted"]}', 10, WHITE)
        for k, name in enumerate(('P1', 'P2', 'AI')):
            self.T(x + 24 * s, y + (272 + k * 28) * s,
                   f'{name:>3}   최고 점수 {r["best_score"].get(name, 0):>8,}   승 {r["wins"].get(name, 0):>3}   패 {r["losses"].get(name, 0):>3}   누적 제거 {r["lines"].get(name, 0):>5}줄', 10, MUTED)
        hist = r.get('history', [])[-3:]
        for k, h in enumerate(reversed(hist)):
            sc = ', '.join(f'{n} {v:,}' for n, v in h.get('scores', {}).items())
            self.T(x + 24 * s, y + (370 + k * 24) * s, f'최근: {MODE_NAMES.get(h.get("mode"), h.get("mode", "?"))} · 결과 {h.get("result") or h.get("winner") or "-"} · {sc}', 9, MUTED)

    def show_records(self):
        r = self.records
        top = tk.Toplevel(self.root); top.title('저장된 플레이 기록'); top.configure(bg=BG)
        rows = [('플레이어', '최고 점수', '승', '패', '누적 제거 줄')]
        for name in sorted(set(r['best_score']) | set(r['wins']) | {'P1', 'P2', 'AI'}):
            rows.append((name, f'{r["best_score"].get(name, 0):,}', r['wins'].get(name, 0), r['losses'].get(name, 0), r['lines'].get(name, 0)))
        for i, row in enumerate(rows):
            for j, v in enumerate(row):
                tk.Label(top, text=str(v), bg=SURFACE if i else SURFACE2, fg=WHITE if i else ACCENT, font=(FONT, 10, 'bold' if not i else 'normal'),
                         padx=12, pady=5, width=12).grid(row=i, column=j, sticky='nsew', padx=1, pady=1)
        info = f'완료 경기 {r["matches"]}회 · 중단 {r.get("aborted", 0)}회 · 퍼즐 성공 {r["puzzles_solved"]}/{r["puzzles_attempted"]}\n파일: {self.save_path}'
        tk.Label(top, text=info, bg=BG, fg=MUTED, font=(FONT, 9), justify='left').grid(row=len(rows), column=0, columnspan=5, sticky='w', padx=8, pady=8)
        tk.Button(top, text='닫기', command=top.destroy, bg=SURFACE2, fg=WHITE, bd=0, padx=14, pady=5).grid(row=len(rows) + 1, column=4, pady=(0, 10))
        self.records_window = top
        return top


def main():
    root = tk.Tk()
    GameApp(root)
    root.mainloop()


if __name__ == '__main__':
    main()
