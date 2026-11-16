"""Search-based Tetris AI (no machine learning): enumerate placements, score them with a
transparent hand-designed heuristic, pick the maximum.

  easy   : current piece only, simplified score (lines, max height, 0.35 x holes)
  normal : current piece only, full 7-term score
  hard   : normal + 0.65 x (best full score of the NEXT piece on the resulting board)  -> 2-ply search

Performance design (results are identical to the straightforward list-of-lists version):
  * boards are converted once to 20 row bit-masks (int); line clears, height, holes,
    bumpiness and the T-slot detector work on these masks;
  * drop height is computed from column tops instead of stepping one row at a time;
  * the evaluation of the board *before* the move is computed once per search, not per candidate;
  * whole search results are memoised (LRU) so that repeated GUI requests cost nothing;
  * AIWorker runs searches on a background thread so the Tk event loop never blocks.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from collections import OrderedDict
import logging
import queue
import threading
import time
from .engine import W, H, FULL, Piece, CELLS, ghost, lock_piece, try_rotate

WEIGHTS = {'lines': 110., 'height': -14., 'aggregate': -3.4, 'holes': -64., 'bump': -6.5, 'spin': 150.}
T_SLOT_WEIGHT = 14.0
LOOKAHEAD = 0.65
DIFFICULTIES = ('easy', 'normal', 'hard')

# Counters used by tests and by the performance report.
COUNTERS = {'searches': 0, 'cache_hits': 0, 'evaluations': 0}
_cache: OrderedDict = OrderedDict()
_cache_lock = threading.Lock()          # choose() is called from the GUI thread and the worker thread
CACHE_SIZE = 512


def clear_cache():
    with _cache_lock:
        _cache.clear()


# --------------------------------------------------------------------------- board helpers
def to_masks(board):
    out = []
    for row in board:
        m = 0
        for x, v in enumerate(row):
            if v is not None:
                m |= 1 << x
        out.append(m)
    return tuple(out)


def mask_stats(masks):
    """Same definition as engine.stats(): max height, aggregate height, holes, bumpiness."""
    heights = [0] * W
    seen = 0
    holes = 0
    for y, row in enumerate(masks):
        new = row & ~seen
        if new:
            h = H - y
            b = new
            while b:
                low = b & -b
                heights[low.bit_length() - 1] = h
                b ^= low
            seen |= row
        holes += bin(seen & ~row).count('1')
    bump = 0
    for x in range(W - 1):
        d = heights[x] - heights[x + 1]
        bump += d if d > 0 else -d
    return max(heights), sum(heights), holes, bump


# T-shape rows per rotation: list of (dy, bits relative to x)
_T_ROWS = []
for _r in range(4):
    rows = {}
    for dx, dy in CELLS[('T', _r)]:
        rows[dy] = rows.get(dy, 0) | (1 << dx)
    _T_ROWS.append(tuple(sorted(rows.items())))


def t_slot_potential(board_or_masks):
    """Approximate count of T-shaped cavities with >=3 blocked corners in rows 11..18.
    This is a heuristic signal only -- NOT a guarantee that a legal T-Spin exists.
    (The puzzle solver separately verifies real rotation paths and the corner rule.)"""
    masks = board_or_masks if isinstance(board_or_masks, tuple) else to_masks(board_or_masks)
    if not any(masks[11:]):
        return 0
    found = 0
    for y in range(11, 19):
        for x in range(0, W - 2):
            for rows in _T_ROWS:
                ok = True
                for dy, bits in rows:
                    yy = y + dy
                    if yy >= H or masks[yy] & (bits << x):
                        ok = False
                        break
                if not ok:
                    continue
                occupied = 0
                for cy in (y, y + 2):
                    if cy >= H:
                        occupied += 2
                    else:
                        m = masks[cy]
                        occupied += ((m >> x) & 1) + ((m >> (x + 2)) & 1)
                if occupied >= 3:
                    found += 1
                    break
    return found


# --------------------------------------------------------------------------- data
@dataclass
class Candidate:
    piece: Piece
    score: float
    parts: dict
    lines: int
    spin: bool
    masks: tuple = field(repr=False, default=())
    _board: list = field(repr=False, default=None)
    source: list = field(repr=False, default=None)

    @property
    def board(self):
        """Resulting board (list of lists, with piece kinds) -- materialised lazily."""
        if self._board is None and self.source is not None:
            self._board = lock_piece(self.source, self.piece)[0]
        return self._board


class _Before:
    """Evaluation terms of the board before the move (computed once per search)."""
    __slots__ = ('height', 'aggregate', 'holes', 'bump', 'tslot')

    def __init__(self, masks):
        self.height, self.aggregate, self.holes, self.bump = mask_stats(masks)
        self.tslot = t_slot_potential(masks)


def _parts(before: _Before, masks, n, spin):
    height, aggregate, holes, bump = mask_stats(masks)
    COUNTERS['evaluations'] += 1
    return {
        '줄 제거': WEIGHTS['lines'] * (n * n),
        'T-Spin': WEIGHTS['spin'] * (1 + max(0, n - 1)) if spin else 0.0,
        '높이 변화': WEIGHTS['height'] * (height - before.height),
        '구멍 변화': WEIGHTS['holes'] * (holes - before.holes),
        '평탄화': WEIGHTS['bump'] * (bump - before.bump),
        '전체 높이': WEIGHTS['aggregate'] * (aggregate - before.aggregate),
        'T-Spin 후보': T_SLOT_WEIGHT * (t_slot_potential(masks) - before.tslot),
    }


def evaluate(before, after, n, spin, level='normal'):
    """Public, list-of-lists API kept for compatibility: (total, parts)."""
    parts = _parts(_Before(to_masks(before)), to_masks(after), n, spin)
    return sum(parts.values()), parts


# --------------------------------------------------------------------------- candidate generation
def _place(masks, kind, r, x, y):
    """Lock a straight-dropped piece on masks -> (new_masks, lines). Caller guarantees validity."""
    rows = list(masks)
    for dx, dy in CELLS[(kind, r)]:
        rows[y + dy] |= 1 << (x + dx)
    kept = [m for m in rows if m != FULL]
    n = H - len(kept)
    if n:
        kept = [0] * n + kept
    return tuple(kept), n


def _landings(masks, kind):
    """All distinct straight-drop placements: [(r, x, y, new_masks, lines)].
    A piece entering from above stops on the top-most filled cell of each column it covers, so
    the landing row is min(top[col] - 1 - dy). Placements that would lock above the field are skipped.
    Straight drops never end with a rotation, so these placements are never T-Spins."""
    top = [H] * W
    for y in range(H - 1, -1, -1):
        m = masks[y]
        if m:
            for x in range(W):
                if m >> x & 1:
                    top[x] = y
    out = {}
    for r in range(4 if kind != 'O' else 1):
        cl = CELLS[(kind, r)]
        min_dx = min(dx for dx, _ in cl); max_dx = max(dx for dx, _ in cl)
        for x in range(-min_dx, W - max_dx):
            y = min(top[x + dx] - 1 - dy for dx, dy in cl)
            if y < -2:
                continue
            if any(y + dy < 0 for _, dy in cl):
                continue                       # would top out
            key = frozenset((x + dx, y + dy) for dx, dy in cl)
            if key in out:
                continue
            new, n = _place(masks, kind, r, x, y)
            out[key] = (r, x, y, new, n)
    return list(out.values())


def landings(board, kind):
    """Compatibility wrapper returning Candidate objects (unscored)."""
    masks = to_masks(board)
    return [Candidate(Piece(kind, x, y, r), 0.0, {}, n, False, new, None, board)
            for r, x, y, new, n in _landings(masks, kind)]


# --------------------------------------------------------------------------- search
def _best_future(masks, next_kind):
    before = _Before(masks)
    best = None
    for r, x, y, new, n in _landings(masks, next_kind):
        s = sum(_parts(before, new, n, False).values())
        if best is None or s > best:
            best = s
    return best


def _search(board, masks, kind, next_kind, difficulty):
    before = _Before(masks)
    opts = []
    for r, x, y, new, n in _landings(masks, kind):
        parts = _parts(before, new, n, False)
        if difficulty == 'easy':
            # No lookahead; looks only at cleared lines, max height and (discounted) holes.
            raw = parts['줄 제거'] + parts['높이 변화'] + parts['구멍 변화'] * .35
        else:
            raw = sum(parts.values())
            if difficulty == 'hard' and next_kind:
                fut = _best_future(new, next_kind)
                if fut is not None:
                    raw += LOOKAHEAD * fut
                    parts['다음 블록 전망'] = LOOKAHEAD * fut
        opts.append(Candidate(Piece(kind, x, y, r), raw, parts, n, False, new, None, board))
    # Stable sort: ties keep generation order (rotation, then x), so results are deterministic.
    opts.sort(key=lambda c: c.score, reverse=True)
    return opts


def choose(board, kind, next_kind=None, difficulty='normal'):
    """Return (best_candidate, all_candidates_sorted). Thread-safe, memoised."""
    masks = to_masks(board)
    key = (masks, kind, next_kind if difficulty == 'hard' else None, difficulty)
    with _cache_lock:
        hit = _cache.get(key)
        if hit is not None:
            _cache.move_to_end(key)
            COUNTERS['cache_hits'] += 1
    if hit is None:
        COUNTERS['searches'] += 1
        snapshot = [row[:] for row in board]
        opts = _search(snapshot, masks, kind, next_kind, difficulty)
        with _cache_lock:
            _cache[key] = opts
            if len(_cache) > CACHE_SIZE:
                _cache.popitem(last=False)
        hit = opts
    if not hit:
        return None, []
    return hit[0], list(hit)


def preview_at(board, p):
    """Score the place where the current piece would land if hard-dropped now (coach panel)."""
    try:
        landed = ghost(board, p)
        if landed.y != p.y:
            landed.rotated_last = False
        new, n, spin, topped = lock_piece(board, landed)
        if topped:
            return None
        masks = to_masks(new)
        parts = _parts(_Before(to_masks(board)), masks, n, spin)
        return Candidate(landed, sum(parts.values()), parts, n, spin, masks, new, board)
    except ValueError:
        return None


def plan_actions(board, start: Piece, target: Piece):
    """Key presses that bring `start` to the target rotation/column, then a hard drop.
    The GUI executes them one by one through the normal Player.rotate/move rules."""
    actions = []
    diff = (target.rot - start.rot) % 4
    actions += ['cw'] if diff == 1 else ['cw', 'cw'] if diff == 2 else ['ccw'] if diff == 3 else []
    probe = start.copy()
    for a in actions:
        q = try_rotate(board, probe, 1 if a == 'cw' else -1)
        if q:
            probe = q
    dx = target.x - probe.x
    actions += (['right'] * dx) if dx > 0 else (['left'] * -dx)
    actions.append('hard')
    return actions


# --------------------------------------------------------------------------- background worker
class AIWorker:
    """One background thread that runs choose() for snapshots of player state.

    Synchronisation design (no shared mutable game state):
      * submit() deep-copies the board on the GUI thread, so the worker never sees a board that
        the GUI is mutating;
      * jobs and results travel through thread-safe queue.Queue objects;
      * each job carries a token (game id, player index, piece id); the GUI applies a result only
        if the token still matches the current piece, so results from a restarted game, a changed
        mode or an already-locked piece are discarded;
      * invalidate() bumps a generation number so queued jobs of an old game are skipped;
      * Tk widgets are only touched by the GUI thread (the worker only fills the result queue).
    """

    def __init__(self):
        self.jobs = queue.Queue()
        self.results = queue.Queue()
        self.generation = 0
        self._gen_lock = threading.Lock()
        self.thread = threading.Thread(target=self._run, name='tetris-ai', daemon=True)
        self.thread.start()

    def invalidate(self):
        with self._gen_lock:
            self.generation += 1

    def submit(self, token, board, kind, next_kind, difficulty):
        with self._gen_lock:
            gen = self.generation
        self.jobs.put((gen, token, [row[:] for row in board], kind, next_kind, difficulty))

    def poll(self):
        out = []
        while True:
            try:
                out.append(self.results.get_nowait())
            except queue.Empty:
                return out

    def close(self):
        self.jobs.put(None)

    def _run(self):
        while True:
            job = self.jobs.get()
            if job is None:
                return
            gen, token, board, kind, next_kind, difficulty = job
            with self._gen_lock:
                stale = gen != self.generation
            if stale:
                continue
            t = time.perf_counter()
            try:
                best, _ = choose(board, kind, next_kind, difficulty)
            except Exception as exc:          # never kill the worker thread
                best = None
                logging.getLogger(__name__).exception('AI worker error: %s', exc)
            self.results.put((token, best, (time.perf_counter() - t) * 1000))
