"""AI: correctness of the optimised search against a straightforward reference implementation,
difficulty differences, caching, background worker and stale-result protection."""
import threading
import time
import pytest
from tetris.engine import W, H, Piece, Player, valid, ghost, lock_piece, stats, cells, try_rotate
from tetris import ai
from tetris.ai import choose, preview_at, plan_actions, AIWorker, WEIGHTS


# ---- reference implementation (the original, unoptimised algorithm, kept here as an oracle) ----
def ref_tslot(board):
    found = 0
    for y in range(11, 19):
        for x in range(0, W - 2):
            for r in range(4):
                sq = [(x + dx, y + dy) for dx, dy in cells('T', r)]
                if any(px < 0 or px >= W or py >= H or board[py][px] is not None for px, py in sq):
                    continue
                cx, cy = x + 1, y + 1
                occ = sum((cx + dx < 0 or cx + dx >= W or cy + dy >= H or (cy + dy >= 0 and board[cy + dy][cx + dx] is not None))
                          for dx in (-1, 1) for dy in (-1, 1))
                if occ >= 3:
                    found += 1; break
    return found


def ref_eval(before, after, n, spin):
    o, nw = stats(before), stats(after)
    return sum([WEIGHTS['lines'] * n * n, WEIGHTS['spin'] * (1 + max(0, n - 1)) if spin else 0.0,
                WEIGHTS['height'] * (nw['height'] - o['height']), WEIGHTS['holes'] * (nw['holes'] - o['holes']),
                WEIGHTS['bump'] * (nw['bump'] - o['bump']), WEIGHTS['aggregate'] * (nw['aggregate'] - o['aggregate']),
                14.0 * (ref_tslot(after) - ref_tslot(before))])


def ref_landings(board, kind):
    out = {}
    for r in range(4 if kind != 'O' else 1):
        for x in range(-3, W + 2):
            p = Piece(kind, x, -3, r)
            if not valid(board, p):
                continue
            p = ghost(board, p)
            if p.y < -2:
                continue
            b, n, spin, topped = lock_piece(board, p)
            if topped:
                continue
            out.setdefault(tuple(sorted(p.squares())), (p, b, n, spin))
    return list(out.values())


def ref_choose_squares(board, kind, nxt, diff):
    scored = []
    for p, b, n, spin in ref_landings(board, kind):
        if diff == 'easy':
            o, nw = stats(board), stats(b)
            s = WEIGHTS['lines'] * n * n + WEIGHTS['height'] * (nw['height'] - o['height']) + WEIGHTS['holes'] * (nw['holes'] - o['holes']) * .35
        else:
            s = ref_eval(board, b, n, spin)
            if diff == 'hard':
                fut = [ref_eval(b, fb, fn, fs) for _, fb, fn, fs in ref_landings(b, nxt)]
                if fut:
                    s += .65 * max(fut)
        scored.append((s, tuple(sorted(p.squares()))))
    scored.sort(key=lambda t: t[0], reverse=True)
    return scored


def sample_boards(count=8):
    out = []
    p = Player('B', 21)
    for i in range(count * 3):
        if i % 3 == 0:
            out.append(([r[:] for r in p.board], p.active.kind, p.next[0]))
        best, _ = choose(p.board, p.active.kind, p.next[0], 'normal')
        p.active = best.piece.copy(); p.hard_drop()
    return out


@pytest.mark.parametrize('diff', ['easy', 'normal', 'hard'])
def test_optimised_search_equals_reference(diff):
    for board, kind, nxt in sample_boards(6):
        ai.clear_cache()
        best, allc = choose(board, kind, nxt, diff)
        ref = ref_choose_squares(board, kind, nxt, diff)
        assert len(allc) == len(ref)
        assert tuple(sorted(best.piece.squares())) == ref[0][1]
        assert abs(best.score - ref[0][0]) < 1e-6


def test_tslot_bitmask_equals_reference():
    for board, _, _ in sample_boards(8):
        assert ai.t_slot_potential(board) == ref_tslot(board)


def test_difficulties_make_different_decisions():
    boards = sample_boards(12)
    diff_en = sum(choose(b, k, n, 'easy')[0].piece.squares() != choose(b, k, n, 'normal')[0].piece.squares() for b, k, n in boards)
    diff_nh = sum(choose(b, k, n, 'normal')[0].piece.squares() != choose(b, k, n, 'hard')[0].piece.squares() for b, k, n in boards)
    assert diff_en >= 1 and diff_nh >= 1


def test_hard_uses_next_piece_lookahead():
    board, kind, nxt = sample_boards(3)[-1]
    h, _ = choose(board, kind, nxt, 'hard')
    n, _ = choose(board, kind, nxt, 'normal')
    assert '다음 블록 전망' in h.parts and '다음 블록 전망' not in n.parts


def test_easy_plays_worse_than_normal_on_fixed_seed():
    res = {}
    for diff in ('easy', 'normal'):
        p = Player('AI', seed=101, is_ai=True)
        while not p.over and p.pieces < 300:
            best, _ = choose(p.board, p.active.kind, p.next[0], diff)
            p.active = best.piece.copy(); p.hard_drop()
        res[diff] = (p.lines, p.over)
    assert res['normal'][0] > res['easy'][0] and not res['normal'][1]


def test_all_difficulties_return_valid_placements_and_board_stays_consistent():
    for diff in ('easy', 'normal', 'hard'):
        p = Player('AI', seed=8, is_ai=True)
        for _ in range(45):
            if p.over:
                break
            before = sum(v is not None for r in p.board for v in r)
            best, cands = choose(p.board, p.active.kind, p.next[0], diff)
            assert valid(p.board, best.piece) and cands[0].score >= cands[-1].score
            p.active = best.piece.copy(); res = p.hard_drop()
            after = sum(v is not None for r in p.board for v in r)
            assert after == before + 4 - W * res.lines
            assert all(any(v is None for v in row) for row in p.board)
        assert p.pieces >= 40


def test_search_result_is_cached():
    ai.clear_cache()
    p = Player('P', 3)
    s0, h0 = ai.COUNTERS['searches'], ai.COUNTERS['cache_hits']
    a, _ = choose(p.board, p.active.kind, p.next[0], 'hard')
    b, _ = choose(p.board, p.active.kind, p.next[0], 'hard')
    assert ai.COUNTERS['searches'] == s0 + 1 and ai.COUNTERS['cache_hits'] == h0 + 1 and a is b


def test_coach_preview_matches_evaluation_function():
    p = Player('P', 5)
    best, _ = choose(p.board, p.active.kind, p.next[0], 'normal')
    p.active = Piece(best.piece.kind, best.piece.x, 0, best.piece.rot)
    pv = preview_at(p.board, p.active)
    assert abs(pv.score - best.score) < 1e-9 and pv.parts == best.parts


def test_plan_actions_reach_target_with_real_moves():
    p = Player('P', 12)
    for _ in range(20):
        best, _ = choose(p.board, p.active.kind, p.next[0], 'hard')
        for a in plan_actions(p.board, p.active, best.piece):
            if a == 'hard':
                landed = ghost(p.board, p.active)
                assert sorted(landed.squares()) == sorted(best.piece.squares())
                p.hard_drop()
            elif a in ('cw', 'ccw'):
                assert p.rotate(1 if a == 'cw' else -1)
            else:
                assert p.move(-1 if a == 'left' else 1, 0)


def test_worker_returns_result_with_token():
    w = AIWorker()
    try:
        p = Player('P', 1)
        w.submit(('ai', 1, 1, p.piece_id), p.board, p.active.kind, p.next[0], 'hard')
        deadline = time.time() + 5; got = []
        while not got and time.time() < deadline:
            got = w.poll(); time.sleep(0.01)
        assert got and got[0][0] == ('ai', 1, 1, p.piece_id) and got[0][1] is not None
    finally:
        w.close()


def test_worker_skips_jobs_queued_before_invalidate(monkeypatch):
    gate = threading.Event(); started = threading.Event()
    real = ai.choose

    def slow_choose(*a, **k):
        started.set(); gate.wait(5)
        return real(*a, **k)
    monkeypatch.setattr(ai, 'choose', slow_choose)
    w = AIWorker()
    try:
        p = Player('P', 1)
        w.submit(('ai', 1, 0, 1), p.board, 'T', 'O', 'normal')      # running when invalidated
        assert started.wait(5)
        w.submit(('ai', 1, 0, 2), p.board, 'T', 'O', 'normal')      # queued -> must be skipped
        w.invalidate()
        w.submit(('ai', 2, 0, 1), p.board, 'T', 'O', 'normal')      # new game
        gate.set()
        deadline = time.time() + 5; tokens = []
        while len(tokens) < 2 and time.time() < deadline:
            tokens += [t for t, _, _ in w.poll()]; time.sleep(0.01)
        assert tokens == [('ai', 1, 0, 1), ('ai', 2, 0, 1)]
    finally:
        w.close()


def test_worker_never_mutates_caller_board():
    w = AIWorker()
    try:
        p = Player('P', 1); snapshot = [r[:] for r in p.board]
        w.submit(('ai', 1, 0, 1), p.board, p.active.kind, p.next[0], 'hard')
        p.board[19][0] = 'G'          # GUI thread keeps mutating its own board meanwhile
        deadline = time.time() + 5; got = []
        while not got and time.time() < deadline:
            got = w.poll(); time.sleep(0.01)
        assert got and got[0][1].source == snapshot
    finally:
        w.close()
