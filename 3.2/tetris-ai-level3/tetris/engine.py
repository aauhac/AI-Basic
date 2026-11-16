"""Pure-Python Tetris rules, SRS kicks, scoring, attacks and independent players.

No GUI dependency: every rule here is exercised directly by the automated tests.

Lock pipeline (Player.lock) -- the order matters and is tested:
  1. fix the active piece into the board (the piece stops being "active")
  2. clear lines, add score
  3. combo / back-to-back / T-Spin bookkeeping
  4. compute outgoing attack
  5. cancel outgoing attack against pending incoming garbage
  6. insert the remaining garbage
  7. top-out check (lock-out, garbage push-out)
  8. spawn the next piece (block-out check)
Win/loss decisions are made by Match.check_end() after the lock.
"""
from __future__ import annotations
from dataclasses import dataclass
from collections import deque
import random

W, H = 10, 20
FULL = (1 << W) - 1
COLORS = {'I': '#39c5ef', 'O': '#f0d04d', 'T': '#ac79e7', 'S': '#61d78b', 'Z': '#f07885',
          'J': '#668df2', 'L': '#eead65', 'G': '#758397'}
# Shapes with SRS rotation centers (3x3 or 4x4 local matrix).
BASE = {
    'T': ['.T.', 'TTT', '...'], 'J': ['J..', 'JJJ', '...'],
    'L': ['..L', 'LLL', '...'], 'S': ['.SS', 'SS.', '...'],
    'Z': ['ZZ.', '.ZZ', '...'], 'O': ['.OO', '.OO', '...'],
    'I': ['....', 'IIII', '....', '....'],
}
KINDS = tuple(BASE)


def _rotated_cells(kind: str, rotation: int):
    matrix = BASE[kind]
    n = len(matrix)
    result = [(x, y) for y, line in enumerate(matrix) for x, v in enumerate(line) if v != '.']
    if kind == 'O':
        # SRS: the O piece occupies the same four cells in all four rotation states.
        # (Rotating the 3x3 matrix would shift the square and let it sink into the floor.)
        return tuple(result)
    for _ in range(rotation % 4):
        result = [(n - 1 - y, x) for x, y in result]
    return tuple(result)


# Pre-computed once: cells() is called on every collision test.
CELLS = {(k, r): _rotated_cells(k, r) for k in BASE for r in range(4)}


def cells(kind: str, rotation: int):
    return CELLS[(kind, rotation % 4)]


# SRS kick offsets, in screen coordinates where y goes down.
_JLSTZ = {
    (0, 1): [(0, 0), (-1, 0), (-1, -1), (0, 2), (-1, 2)],
    (1, 0): [(0, 0), (1, 0), (1, 1), (0, -2), (1, -2)],
    (1, 2): [(0, 0), (1, 0), (1, 1), (0, -2), (1, -2)],
    (2, 1): [(0, 0), (-1, 0), (-1, -1), (0, 2), (-1, 2)],
    (2, 3): [(0, 0), (1, 0), (1, -1), (0, 2), (1, 2)],
    (3, 2): [(0, 0), (-1, 0), (-1, 1), (0, -2), (-1, -2)],
    (3, 0): [(0, 0), (-1, 0), (-1, 1), (0, -2), (-1, -2)],
    (0, 3): [(0, 0), (1, 0), (1, -1), (0, 2), (1, 2)],
}
_I = {
    (0, 1): [(0, 0), (-2, 0), (1, 0), (-2, 1), (1, -2)],
    (1, 0): [(0, 0), (2, 0), (-1, 0), (2, -1), (-1, 2)],
    (1, 2): [(0, 0), (-1, 0), (2, 0), (-1, -2), (2, 1)],
    (2, 1): [(0, 0), (1, 0), (-2, 0), (1, 2), (-2, -1)],
    (2, 3): [(0, 0), (2, 0), (-1, 0), (2, -1), (-1, 2)],
    (3, 2): [(0, 0), (-2, 0), (1, 0), (-2, 1), (1, -2)],
    (3, 0): [(0, 0), (1, 0), (-2, 0), (1, 2), (-2, -1)],
    (0, 3): [(0, 0), (-1, 0), (2, 0), (-1, -2), (2, 1)],
}


@dataclass
class Piece:
    kind: str
    x: int = 3
    y: int = -1
    rot: int = 0
    rotated_last: bool = False
    kick_used: int = 0

    def squares(self):
        x, y = self.x, self.y
        return tuple((x + dx, y + dy) for dx, dy in CELLS[(self.kind, self.rot % 4)])

    def copy(self):
        return Piece(self.kind, self.x, self.y, self.rot, self.rotated_last, self.kick_used)


class Bag:
    """7-bag randomizer: every run of 7 pieces contains each tetromino exactly once."""

    def __init__(self, seed=None):
        self.rng = random.Random(seed)
        self.queue = deque()

    def take(self):
        if not self.queue:
            bag = list(BASE)
            self.rng.shuffle(bag)
            self.queue.extend(bag)
        return self.queue.popleft()


def empty_board():
    return [[None] * W for _ in range(H)]


def valid(board, piece):
    for x, y in piece.squares():
        if not (0 <= x < W and y < H):
            return False
        if y >= 0 and board[y][x] is not None:
            return False
    return True


def try_rotate(board, p: Piece, direction=1):
    """Return the rotated piece (with SRS wall kick) or None. The input piece is never modified."""
    nr = (p.rot + direction) % 4
    if p.kind == 'O':
        q = Piece('O', p.x, p.y, nr, True, 0)   # same cells, only the state index changes
        return q if valid(board, q) else None
    kicks = (_I if p.kind == 'I' else _JLSTZ).get((p.rot, nr), [(0, 0)])
    for i, (dx, dy) in enumerate(kicks):
        q = Piece(p.kind, p.x + dx, p.y + dy, nr, True, i)
        if valid(board, q):
            return q
    return None


def ghost(board, p):
    """Lowest valid position straight below p (rotated_last is copied unchanged)."""
    q = p.copy()
    while True:
        q.y += 1
        if not valid(board, q):
            q.y -= 1
            return q


def drop(board, p):
    """Hard-drop landing. Falling one or more rows means the last action was not a rotation."""
    q = ghost(board, p)
    if q.y != p.y:
        q.rotated_last = False
    return q


def corners_blocked(board, p):
    # 3x3 T's rotation center is local (1,1).
    cx, cy = p.x + 1, p.y + 1
    count = 0
    for dx in (-1, 1):
        for dy in (-1, 1):
            x, y = cx + dx, cy + dy
            if x < 0 or x >= W or y >= H or (y >= 0 and board[y][x] is not None):
                count += 1
    return count


def is_t_spin(board, p):
    """3-corner T-Spin rule: T piece, last successful action was a rotation, >=3 corners blocked.
    (T-Spin Mini is not distinguished; this is documented as a limitation.)"""
    return p.kind == 'T' and p.rotated_last and corners_blocked(board, p) >= 3


def clear_lines(board):
    remain = [row for row in board if any(v is None for v in row)]
    n = H - len(remain)
    return [[None] * W for _ in range(n)] + remain, n


def lock_piece(board, p):
    """Pure function: returns (new_board, lines, t_spin, topped). Raises ValueError for an invalid piece."""
    if not valid(board, p):
        raise ValueError('invalid lock')
    spin = is_t_spin(board, p)  # Inspect the state BEFORE filling the rotated T cells.
    b = [row[:] for row in board]
    topped = False
    for x, y in p.squares():
        if y < 0:
            topped = True
        else:
            b[y][x] = p.kind
    b, n = clear_lines(b)
    return b, n, spin, topped


def stats(board):
    heights = [0] * W
    holes = 0
    for x in range(W):
        top = H
        for y in range(H):
            if board[y][x] is not None:
                top = y
                break
        heights[x] = H - top
        for y in range(top + 1, H):
            if board[y][x] is None:
                holes += 1
    bump = sum(abs(heights[x] - heights[x + 1]) for x in range(W - 1))
    return {'height': max(heights), 'aggregate': sum(heights), 'holes': holes, 'bump': bump}


# Score / attack tables (documented in the report).
LINE_SCORE = {1: 100, 2: 300, 3: 500, 4: 800}
SPIN_SCORE = {0: 400, 1: 800, 2: 1200, 3: 1600}
LINE_ATTACK = {0: 0, 1: 0, 2: 1, 3: 2, 4: 4}
SPIN_ATTACK = {0: 0, 1: 2, 2: 4, 3: 6}
LABELS = {0: '', 1: 'SINGLE', 2: 'DOUBLE', 3: 'TRIPLE', 4: 'TETRIS'}


@dataclass
class LockResult:
    lines: int = 0
    spin: bool = False
    attack: int = 0          # garbage actually sent after cancelling
    points: int = 0          # player's total score after the lock
    label: str = ''
    cancelled: int = 0       # incoming garbage neutralised by this lock
    received: int = 0        # garbage rows inserted into this board by this lock
    gained: int = 0          # score gained by this lock
    combo: int = -1
    b2b: bool = False


class Player:
    def __init__(self, name, seed=None, is_ai=False):
        self.name = name
        self.board = empty_board()
        self.bag = Bag(seed)
        self.active = None
        self.held = None
        self.hold_used = False
        self.next = deque(self.bag.take() for _ in range(5))
        self.score = 0; self.lines = 0; self.level = 1; self.combo = -1; self.b2b = False
        self.pending = 0; self.wins = 0; self.over = False; self.is_ai = is_ai
        self.last_action = ''; self.total_attacks = 0; self.spins = 0
        self.pieces = 0; self.garbage_received = 0; self.cancelled = 0; self.max_combo = 0
        self.piece_id = 0        # increases on every spawn (used to detect stale AI results)
        self.version = 0         # increases on every state change (used by render caches)
        self.rng = random.Random(seed if seed is not None else 0)
        self.spawn()

    # ----- piece lifecycle -------------------------------------------------
    def spawn(self, forced=None):
        kind = forced or self.next.popleft()
        if not forced:
            self.next.append(self.bag.take())
        self.active = Piece(kind)
        self.hold_used = False
        self.piece_id += 1
        self.version += 1
        if not valid(self.board, self.active):
            self.over = True          # block-out

    def move(self, dx, dy):
        if self.over or not self.active:
            return False
        q = self.active.copy(); q.x += dx; q.y += dy; q.rotated_last = False
        if valid(self.board, q):
            self.active = q; self.version += 1
            return True
        return False

    def rotate(self, direction=1):
        if self.over or not self.active:
            return False
        q = try_rotate(self.board, self.active, direction)
        if q:
            self.active = q; self.version += 1
            return True
        return False

    def hold(self):
        return self.swap_hold()

    def swap_hold(self):
        if self.over or self.hold_used or not self.active:
            return False
        old = self.held
        self.held = self.active.kind
        self.spawn(forced=old) if old else self.spawn()
        self.hold_used = True
        return True

    def soft_drop(self):
        if self.move(0, 1):
            self.score += 1
            return True
        return False

    def step(self):
        """Gravity tick: fall one row, or lock when grounded."""
        if self.over or not self.active:
            return None
        if self.move(0, 1):
            return None
        return self.lock()

    def hard_drop(self):
        if self.over or not self.active:
            return None
        landing = drop(self.board, self.active)
        self.score += 2 * (landing.y - self.active.y)
        self.active = landing
        return self.lock()

    # ----- lock pipeline ---------------------------------------------------
    def lock(self):
        if self.over or self.active is None:
            return None
        p = self.active
        if not valid(self.board, p):
            # Defensive: should be unreachable because every mutation validates first.
            self.over = True; self.active = None; self.version += 1
            return LockResult(label='INVALID', points=self.score)
        # 1. fix the piece; it is no longer the active piece
        board, n, spin, topped = lock_piece(self.board, p)
        self.active = None
        self.board = board
        self.pieces += 1
        # 2-3. score, combo, back-to-back, T-Spin
        special = n == 4 or (spin and n > 0)
        b2b_bonus = special and self.b2b
        gained = 0
        if n:
            self.combo += 1
            self.max_combo = max(self.max_combo, self.combo)
            self.lines += n
            base = SPIN_SCORE[min(n, 3)] if spin else LINE_SCORE[n]
            if b2b_bonus:
                base = base * 3 // 2
            gained = base * self.level + max(0, self.combo) * 50 * self.level
            self.b2b = special
        else:
            self.combo = -1
            if spin:
                gained = SPIN_SCORE[0] * self.level
        self.score += gained
        if spin:
            self.spins += 1
        # 4. outgoing attack
        attack = (SPIN_ATTACK.get(n, 6) if spin else LINE_ATTACK.get(n, 4))
        if n:
            attack += min(max(0, self.combo), 4)
        if b2b_bonus:
            attack += 1
        # 5. cancel against garbage waiting for this player
        cancel = min(attack, self.pending)
        attack -= cancel; self.pending -= cancel; self.cancelled += cancel
        # 6. receive what is left
        received = self.pending
        self.pending = 0
        if received:
            self.receive_garbage(received)
        # 7. lock-out (piece fixed above the visible field)
        if topped:
            self.over = True
        self.level = 1 + self.lines // 10
        self.total_attacks += attack
        name = ('T-SPIN ' if spin else '') + LABELS[min(n, 4)]
        if b2b_bonus:
            name = 'B2B ' + name
        if self.combo >= 1:
            name += f' · {self.combo} COMBO'
        self.last_action = name.strip() or 'LOCK'
        self.version += 1
        # 8. next piece (spawn() itself detects block-out)
        if not self.over:
            self.spawn()
        return LockResult(n, spin, attack, self.score, self.last_action, cancel, received,
                          gained, self.combo, b2b_bonus)

    def receive_garbage(self, n):
        """Insert n garbage rows (one shared hole column per attack) at the bottom."""
        if n <= 0:
            return
        n = min(H, n)
        # Cells in the top n rows would be pushed above the field: real top-out.
        if any(v is not None for row in self.board[:n] for v in row):
            self.over = True
        hole = self.rng.randrange(W)
        rows = [[('G' if x != hole else None) for x in range(W)] for _ in range(n)]
        self.board = self.board[n:] + rows
        self.garbage_received += n
        self.version += 1
        if self.active is not None and not valid(self.board, self.active):
            # A falling piece is pushed up together with the stack when possible.
            q = self.active.copy()
            for _ in range(n):
                q.y -= 1
                if valid(self.board, q):
                    break
            if valid(self.board, q):
                self.active = q
            else:
                self.over = True

    def serialize(self):
        return {'score': self.score, 'lines': self.lines, 'level': self.level, 'spins': self.spins,
                'attacks': self.total_attacks}

    def gravity_delay(self):
        """Seconds per gravity row: speeds up every level (10 lines)."""
        return max(.08, .85 * (.83 ** (self.level - 1)))


MODES = ('solo', 'two', 'versus', 'ai')


class Match:
    """Mode rules without any GUI: player creation, attack routing and win/loss decisions."""

    def __init__(self, mode, seed=0, difficulty='normal'):
        if mode not in MODES:
            raise ValueError(mode)
        self.mode = mode; self.seed = seed; self.difficulty = difficulty
        self.players = [Player('P1', seed=seed)]
        if mode in ('two', 'versus'):
            self.players.append(Player('P2', seed=seed))
        elif mode == 'ai':
            self.players.append(Player('AI', seed=seed, is_ai=True))
        self.finished = False; self.winner = None; self.reason = ''
        self.attack_log = []   # (sender, lines)

    @property
    def attacks_enabled(self):
        return self.mode in ('versus', 'ai')

    def after_lock(self, index, result):
        """Route a lock result: queue garbage for the opponent (attack modes only)."""
        if result is None:
            return 0
        sent = 0
        if result.attack and self.attacks_enabled:
            opponent = self.players[1 - index]
            if not opponent.over:
                opponent.pending += result.attack
                sent = result.attack
                self.attack_log.append((self.players[index].name, sent))
        return sent

    def check_end(self):
        """Return True once the match is decided; sets winner (None = no winner / draw) and reason."""
        if self.finished:
            return True
        ps = self.players
        if self.mode == 'solo':
            if ps[0].over:
                self.finished = True; self.winner = None; self.reason = 'GAME OVER'
        elif self.mode == 'two':
            # Simultaneous play: no attacks; both boards play out, higher score wins.
            if all(p.over for p in ps):
                self.finished = True
                self._by_score('두 플레이어 모두 종료 · 점수 비교')
        else:
            losers = [p for p in ps if p.over]
            if len(losers) == 1:
                self.finished = True
                self.winner = next(p.name for p in ps if not p.over)
                self.reason = f'{losers[0].name} 블록 초과(Top-out)'
            elif len(losers) == 2:
                self.finished = True
                self._by_score('동시 Top-out · 점수 비교')
        return self.finished

    def _by_score(self, reason):
        a, b = self.players
        self.winner = a.name if a.score > b.score else b.name if b.score > a.score else None
        self.reason = reason
