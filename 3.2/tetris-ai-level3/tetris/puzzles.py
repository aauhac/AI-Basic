"""T-Spin puzzle generation with exact, keyboard-level verification and staged hints.

Search model
  A state is (x, y, rotation, last_action_was_rotation).  Edges are the five inputs a player has:
  left, right, soft-drop (down), rotate cw, rotate ccw -- rotations go through engine.try_rotate,
  so SRS wall kicks are included.  Breadth-first search (BFS) over this graph therefore finds every
  position a human can really reach, and the shortest key sequence to it.

Generation (constructive + verify, "generate-and-test")
  1. build a T-Spin Double slot (random column, random side, 0-2 random garbage rows below);
  2. difficulty decides what is *removed* from the finished structure:
        easy   : nothing                       sequence T          (1 piece)
        normal : the overhang roof (an I)      sequence I -> T     (2 pieces)
        hard   : roof (I) and a 2x2 gap (O)    sequence I -> O -> T (3 pieces)
  3. every preparation piece of the witness solution must be reachable by BFS and must not clear
     lines; then the final T-Spin must be reachable (legal_spin_locks);
  4. necessity check: the T-Spin is NOT available on the initial board, and for hard it is not
     available after only the I or only the O -- so preparation pieces really matter;
  5. bounded attempts: PuzzleGenerationError instead of an infinite loop.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from collections import deque
import random
from .engine import W, H, Piece, valid, try_rotate, lock_piece, empty_board, drop, Player, CELLS

MAX_ATTEMPTS = 60
ACTIONS = (('left', -1, 0), ('right', 1, 0), ('down', 0, 1))
KEY_LABEL = {'left': '←', 'right': '→', 'down': '↓', 'cw': '↻(↑/X)', 'ccw': '↺(Z)', 'hard': 'Space'}


class PuzzleGenerationError(RuntimeError):
    pass


@dataclass
class Puzzle:
    board: list
    sequence: list
    target_lines: int
    solution: list                     # [(x, y, rot)] for every piece, in order
    note: str
    difficulty: str
    routes: list = field(default_factory=list)   # key sequence for every piece (witness)
    seed: object = None
    attempts: int = 0


# --------------------------------------------------------------------------- BFS core
def _key(p):
    return (p.x, p.y, p.rot, p.rotated_last)


def explore(board, kind, start=None, node_limit=None):
    """BFS over player inputs. Returns (parents, order) where parents[state] = (prev_state, action)."""
    start = start.copy() if start else Piece(kind)
    if not valid(board, start):
        return {}, []
    parents = {_key(start): (None, None)}
    pieces = {_key(start): start}
    order = [start]
    q = deque([start])
    while q:
        if node_limit and len(order) >= node_limit:
            break
        p = q.popleft()
        nxts = []
        for name, dx, dy in ACTIONS:
            z = p.copy(); z.x += dx; z.y += dy; z.rotated_last = False
            if valid(board, z):
                nxts.append((name, z))
        for name, d in (('cw', 1), ('ccw', -1)):
            z = try_rotate(board, p, d)
            if z:
                nxts.append((name, z))
        for name, z in nxts:
            k = _key(z)
            if k not in parents:
                parents[k] = (_key(p), name)
                pieces[k] = z
                order.append(z)
                q.append(z)
    return parents, order


def _path(parents, state):
    actions = []
    k = state
    while parents[k][0] is not None:
        k, a = parents[k][0], parents[k][1]
        actions.append(a)
    return list(reversed(actions))


def _grounded(board, p):
    d = p.copy(); d.y += 1
    return not valid(board, d)


def reachable_placements(board, kind, start=None):
    """Every grounded lock position a player can reach -> {frozenset(squares): (piece, actions)}."""
    parents, order = explore(board, kind, start)
    out = {}
    for p in order:
        if _grounded(board, p):
            sq = frozenset(p.squares())
            if sq not in out:
                out[sq] = (p, _path(parents, _key(p)) + ['hard'])
    return out


def legal_spin_locks(board, kind='T', node_limit=None, start=None):
    """All reachable grounded T positions whose lock is a real T-Spin clearing >=1 line.
    Returns [(piece, lines)] unique by (x, y, rot)."""
    parents, order = explore(board, kind, start, node_limit)
    unique = {}
    for p in order:
        if p.rotated_last and _grounded(board, p):
            b, n, spin, topped = lock_piece(board, p)
            if spin and n > 0 and not topped:
                unique.setdefault((p.x, p.y, p.rot), (p, n))
    return list(unique.values())


def solve_spin_actions(board, node_limit=None, start=None, min_lines=1):
    """Shortest legal key sequence (left/right/down/cw/ccw) to a real T-Spin lock that clears
    >= min_lines lines, or None. Rotation paths include SRS kicks -- no teleporting."""
    parents, order = explore(board, 'T', start, node_limit)
    for p in order:                         # BFS order = shortest sequence first
        if p.rotated_last and _grounded(board, p):
            b, n, spin, topped = lock_piece(board, p)
            if spin and n >= min_lines and not topped:
                return _path(parents, _key(p))
    return None


# --------------------------------------------------------------------------- construction helpers
def piece_for_squares(kind, squares):
    """Find (x, y, rot) of `kind` covering exactly `squares` (used to mirror witness pieces)."""
    squares = frozenset(squares)
    for r in range(4):
        cl = CELLS[(kind, r)]
        ax, ay = min(squares)
        for dx, dy in cl:
            x, y = ax - dx, ay - dy
            if frozenset((x + cx, y + cy) for cx, cy in cl) == squares:
                return Piece(kind, x, y, r)
    return None


def _template(rng, difficulty):
    """Right-hand T-Spin Double; returns (initial_board, [(kind, squares)] preparation witness)."""
    g = rng.randrange(0, 3)                    # extra garbage rows below the slot
    r1 = H - 1 - g; r2 = r1 - 1; r3 = r2 - 1   # stem row, slot row, roof row
    lo = 2 if difficulty == 'hard' else 0
    x = rng.randrange(lo, 5)                   # slot occupies columns x..x+2, roof I x+2..x+5
    b = empty_board()
    for gy in range(H - g, H):
        hole = rng.choice([c for c in range(W) if c != x + 1])
        for c in range(W):
            if c != hole:
                b[gy][c] = 'G'
    for c in range(W):
        if c != x + 1:
            b[r1][c] = 'G'
        if c not in (x, x + 1, x + 2):
            b[r2][c] = 'G'
    roof = [(c, r3) for c in range(x + 2, x + 6)]
    # cosmetic terrain right of the roof (same row) so the board does not look synthetic
    for c in range(x + 6, W):
        if rng.random() < .6:
            b[r3][c] = 'G'
    prep = []
    if difficulty == 'easy':
        for c, y in roof:
            b[y][c] = 'G'
    else:
        prep.append(('I', roof))
    if difficulty == 'hard':
        c = rng.randrange(0, x - 1)            # 2-wide gap left of the slot, under open sky
        gap = [(c, r2), (c + 1, r2), (c, r1), (c + 1, r1)]
        for gx, gy in gap:
            b[gy][gx] = None
        prep.append(('O', gap))
    if rng.random() < .5:                      # mirror: left-hand slot
        b = [list(reversed(row)) for row in b]
        prep = [(k, [(W - 1 - sx, sy) for sx, sy in sq]) for k, sq in prep]
    return b, prep


def _no_spin(board, target):
    return not any(n >= target for _, n in legal_spin_locks(board))


def generate(seed=None, difficulty='easy'):
    rng = random.Random(seed)
    difficulty = difficulty if difficulty in ('easy', 'normal', 'hard') else 'easy'
    for attempt in range(1, MAX_ATTEMPTS + 1):
        board, prep = _template(rng, difficulty)
        current = [r[:] for r in board]
        solution, routes = [], []
        ok = True
        prep_boards = []
        for kind, squares in prep:
            reach = reachable_placements(current, kind)
            hit = reach.get(frozenset(squares))
            if not hit:
                ok = False; break
            p, route = hit
            nb, n, spin, topped = lock_piece(current, p)
            if n or topped:
                ok = False; break
            prep_boards.append((kind, p))
            current = nb
            solution.append((p.x, p.y, p.rot)); routes.append(route)
        if not ok:
            continue
        sols = legal_spin_locks(current)
        if not sols:
            continue
        p, n = sorted(sols, key=lambda v: (-v[1], v[0].x, v[0].y))[0]
        route = solve_spin_actions(current, min_lines=n)
        if route is None:
            continue
        # necessity: preparation pieces must matter
        if prep and not _no_spin(board, n):
            continue
        if len(prep) == 2 and not all(_no_spin(lock_piece(board, piece)[0], n) for _, piece in prep_boards):
            continue
        solution.append((p.x, p.y, p.rot)); routes.append(route + ['hard'])
        seq = [k for k, _ in prep] + ['T']
        name = {1: 'Single', 2: 'Double', 3: 'Triple'}.get(n, str(n))
        note = f'T-Spin {name}({n}줄)을 완성하세요.' + ('' if not prep else f' 준비 블록 {len(prep)}개를 먼저 배치해야 합니다.')
        return Puzzle(board, seq, n, solution, note, difficulty, routes, seed, attempt)
    raise PuzzleGenerationError(f'{MAX_ATTEMPTS}회 시도 안에 검증 가능한 {difficulty} 퍼즐을 만들지 못했습니다.')


def validate_puzzle(puzzle):
    """Replay the witness: every preparation piece reachable by real inputs, no early line clear,
    and a reachable real T-Spin that clears >= target_lines on the final board."""
    board = [r[:] for r in puzzle.board]
    for kind, (x, y, r) in zip(puzzle.sequence[:-1], puzzle.solution[:-1]):
        p = Piece(kind, x, y, r)
        if not valid(board, p):
            return False
        if frozenset(p.squares()) not in reachable_placements(board, kind):
            return False
        board, n, spin, topped = lock_piece(board, p)
        if topped or n:
            return False
    return any(n >= puzzle.target_lines for _, n in legal_spin_locks(board))


def compress_route(actions):
    out = []
    for a in actions:
        if out and out[-1][0] == a:
            out[-1][1] += 1
        else:
            out.append([a, 1])
    return ' '.join(KEY_LABEL[a] + (f'×{c}' if c > 1 else '') for a, c in out)


# --------------------------------------------------------------------------- play session
class PuzzleSession:
    """Puzzle rules on top of a Player (so movement/rotation use the normal game rules).
    Outcome is decided exactly once; later inputs cannot change it."""

    def __init__(self, puzzle, player=None):
        self.puzzle = puzzle
        self.player = player or Player('P1', seed=0)
        pl = self.player
        pl.board = [r[:] for r in puzzle.board]
        pl.held = None; pl.hold_used = True; pl.over = False; pl.pending = 0
        pl.score = 0; pl.lines = 0; pl.spins = 0; pl.combo = -1; pl.b2b = False
        pl.next = deque(puzzle.sequence[1:])
        pl.active = Piece(puzzle.sequence[0])
        pl.piece_id += 1; pl.version += 1
        self.moves = 0
        self.complete = False
        self.failed = False
        self.last = None

    @property
    def done(self):
        return self.complete or self.failed

    @property
    def remaining(self):
        return len(self.puzzle.sequence) - self.moves

    def on_witness_path(self):
        """True while the board equals the witness board after the same number of pieces."""
        b = [r[:] for r in self.puzzle.board]
        for kind, (x, y, r) in list(zip(self.puzzle.sequence, self.puzzle.solution))[:self.moves]:
            b = lock_piece(b, Piece(kind, x, y, r))[0]
        return b == self.player.board

    def lock(self, hard=True):
        """Lock the active piece (hard drop by default). Returns (lines, spin) or None if finished."""
        if self.done or self.player.active is None:
            return None
        pl = self.player
        p = drop(pl.board, pl.active) if hard else pl.active
        b, n, spin, topped = lock_piece(pl.board, p)
        pl.board = b; pl.lines += n; pl.score += n * 100 + (250 if spin else 0)
        if spin:
            pl.spins += 1
        pl.pieces += 1
        self.moves += 1
        self.complete = p.kind == 'T' and spin and n >= self.puzzle.target_lines and not topped
        self.failed = not self.complete and (topped or self.moves >= len(self.puzzle.sequence))
        pl.active = None
        if not self.done:
            pl.active = Piece(self.puzzle.sequence[self.moves])
            pl.next = deque(self.puzzle.sequence[self.moves + 1:])
            pl.piece_id += 1
            if not valid(pl.board, pl.active):
                self.failed = True; pl.active = None
        else:
            pl.next = deque()
        pl.version += 1
        self.last = (n, spin)
        return n, spin

    def hint(self, level):
        """Staged hint for the current piece -> (text, target_squares or None).
        On the witness path the stored solution is used; for the final T the route is always
        recomputed from the actual board, so the hint stays correct even off the witness path."""
        if self.done or self.player.active is None:
            return '퍼즐이 끝났습니다. R 키로 새 문제를 받을 수 있습니다.', None
        i = self.moves
        kind = self.puzzle.sequence[i]
        if kind == 'T':
            route = solve_spin_actions(self.player.board, min_lines=self.puzzle.target_lines)
            if route is None:
                return '현재 보드에서는 목표 T-Spin 경로가 없습니다. R 키로 다시 도전하세요.', None
            p = Piece('T')
            for a in route:
                if a in ('cw', 'ccw'):
                    p = try_rotate(self.player.board, p, 1 if a == 'cw' else -1)
                else:
                    p = p.copy(); p.x += {'left': -1, 'right': 1}.get(a, 0); p.y += 1 if a == 'down' else 0
                    p.rotated_last = False
            x, y, r = p.x, p.y, p.rot
            route = route + ['hard']
        else:
            if not self.on_witness_path():
                return '준비 블록이 정답 경로와 다르게 놓였습니다. 남은 정답은 보장되지 않습니다(R: 새 문제).', None
            x, y, r = self.puzzle.solution[i]
            route = self.puzzle.routes[i]
            p = Piece(kind, x, y, r)
        cols = sorted({sx for sx, _ in p.squares()})
        if level <= 1:
            return f'힌트 1 · {kind} 블록 목표: 가로 {cols[0] + 1}~{cols[-1] + 1}번째 칸 (왼쪽부터)', None
        if level == 2:
            return f'힌트 2 · {kind} 블록 회전 상태 {r} (0:기본, 1:시계 90°, 2:180°, 3:반시계 90°) · 목표 칸 표시', frozenset(p.squares())
        return f'정답 · x={x}, y={y}, 회전={r} · 조작: {compress_route(route)}', frozenset(p.squares())
