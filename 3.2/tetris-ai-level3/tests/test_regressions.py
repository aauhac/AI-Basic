"""Regression tests for the bugs fixed in the final version (each test fails on the original code)."""
import pytest
from conftest import tetris_ready
from tetris.engine import (W, H, Piece, Player, Match, cells, empty_board, valid, ghost, try_rotate,
                           lock_piece, is_t_spin, BASE)
from tetris.puzzles import legal_spin_locks, solve_spin_actions


# --------------------------------------------------------------------------- 2.1 O rotation
def test_o_piece_cells_identical_in_all_rotations():
    for r in range(4):
        assert cells('O', r) == cells('O', 0)


def test_other_pieces_keep_matrix_rotation():
    for kind in 'IJLSTZ':
        n = len(BASE[kind])
        ref = [(x, y) for y, line in enumerate(BASE[kind]) for x, v in enumerate(line) if v != '.']
        for r in range(4):
            assert cells(kind, r) == tuple(ref)
            ref = [(n - 1 - y, x) for x, y in ref]


def test_o_rotation_on_empty_board_does_not_move_cells():
    b = empty_board(); p = Piece('O', 4, 5)
    for d in (1, 1, -1, 1, 1, 1, -1, -1):
        q = try_rotate(b, p, d)
        assert q is not None and valid(b, q)
        assert sorted(q.squares()) == sorted(p.squares())
        p = q


def test_o_rotation_on_floor_then_lock_never_raises():
    b = empty_board(); p = ghost(b, Piece('O'))
    before = sorted(p.squares())
    for _ in range(10):
        p = try_rotate(b, p, 1)
        assert sorted(p.squares()) == before and valid(b, p)
    nb, n, spin, topped = lock_piece(b, p)          # original code: ValueError('invalid lock')
    assert sum(v == 'O' for row in nb for v in row) == 4 and not topped


@pytest.mark.parametrize('x', [-1, W - 3])
def test_o_rotation_against_walls(x):
    b = empty_board(); p = Piece('O', x, 10)
    assert valid(b, p)
    for d in (1, -1, 1, 1):
        p = try_rotate(b, p, d)
        assert p is not None and valid(b, p)


def test_o_rotation_next_to_obstacles():
    b = empty_board()
    for y in range(12, H):
        b[y][2] = 'G'; b[y][5] = 'G'
    p = ghost(b, Piece('O', 2, 0))                 # cells in columns 3,4 between two walls
    assert valid(b, p)
    for d in (1, 1, 1, 1, -1):
        q = try_rotate(b, p, d)
        assert q is not None and sorted(q.squares()) == sorted(p.squares())
        p = q


def test_o_rotation_in_narrow_well_keeps_cells():
    pl = Player('P', 1)
    pl.active = Piece('O', 3, 18)                     # resting on the floor
    snapshot = pl.active.copy()
    pl.board = [[('G' if (y < 18 and x not in (4, 5)) else None) for x in range(W)] for y in range(H)]
    assert valid(pl.board, pl.active)
    pl.rotate(1)
    assert sorted(pl.active.squares()) == sorted(snapshot.squares())


def test_o_repeated_rotation_then_hard_drop_player():
    pl = Player('P', 0)
    pl.active = Piece('O')
    for i in range(12):
        pl.rotate(1 if i % 3 else -1)
    res = pl.hard_drop()
    assert res is not None and not pl.over
    assert sum(v == 'O' for row in pl.board for v in row) == 4
    assert all(v == 'O' for v in (pl.board[H - 1][4], pl.board[H - 1][5], pl.board[H - 2][4], pl.board[H - 2][5]))


# --------------------------------------------------------------------------- 2.2 garbage / lock order
def test_receiving_one_garbage_line_does_not_end_game():
    pl = Player('P', 3); pl.pending = 1
    res = pl.hard_drop()
    assert not pl.over and res.received == 1 and pl.active is not None   # original code: game over
    assert sum(v is None for v in pl.board[-1]) == 1


@pytest.mark.parametrize('n', [2, 3, 4])
def test_receiving_several_lines_keeps_playing(n):
    pl = Player('P', 5); pl.pending = n
    kind = pl.active.kind
    res = pl.hard_drop()
    assert not pl.over and res.received == n and pl.garbage_received == n
    holes = [row.index(None) for row in pl.board[H - n:]]
    assert len(set(holes)) == 1                      # one hole column per attack
    assert all(sum(v is None for v in row) == 1 for row in pl.board[H - n:])
    assert sum(v == kind for row in pl.board for v in row) == 4
    assert pl.active is not None and valid(pl.board, pl.active)


def test_garbage_pushes_locked_blocks_up():
    pl = Player('P', 1)
    pl.active = Piece('O', 3, 18)
    pl.lock()
    assert pl.board[H - 1][4] == 'O'
    pl.pending = 3
    pl.active = Piece('I', 0, 5)                     # a horizontal I far from the O
    pl.hard_drop()
    # the O was at rows 18-19; after 3 garbage rows it is at rows 15-16
    assert pl.board[H - 4][4] == 'O' and pl.board[H - 5][4] == 'O'
    assert not pl.over


def test_real_top_out_from_garbage():
    pl = Player('P', 2)
    for y in range(2, H):
        pl.board[y] = ['G'] * W
        pl.board[y][y % W] = None
    pl.active = Piece('O', 7, 0)                     # locks inside the field (rows 0-1)
    pl.pending = 5
    pl.lock()
    assert pl.over


def test_attack_tetris_sends_four_and_cancel_rules():
    pl = tetris_ready(Player('P', 1)); pl.pending = 6
    res = pl.hard_drop()
    assert res.lines == 4 and res.cancelled == 4 and res.attack == 0 and res.received == 2
    pl2 = tetris_ready(Player('Q', 1)); pl2.pending = 0
    res2 = pl2.hard_drop()
    assert res2.attack == 4 and res2.received == 0


def test_play_continues_after_garbage():
    from tetris.ai import choose
    pl = Player('P', 9)
    pl.pending = 3; pl.hard_drop()
    for _ in range(30):
        best, _ = choose(pl.board, pl.active.kind, pl.next[0], 'normal')
        pl.active = best.piece.copy(); pl.hard_drop()
        assert not pl.over
    assert pl.pieces == 31


# --------------------------------------------------------------------------- T-Spin flag after drops
def _tss_board(x=3):
    b = empty_board()
    for j in range(W):
        if j != x:
            b[H - 1][j] = 'G'
        if j not in (x, x + 1, x + 2):
            b[H - 2][j] = 'G'
    b[H - 3][x - 1] = 'G'
    return b


def test_rotation_in_the_air_then_hard_drop_is_not_t_spin():
    b = _tss_board()
    t, n = legal_spin_locks(b)[0]
    pl = Player('P', 0); pl.board = [r[:] for r in b]
    pl.active = Piece('T', t.x, 0, t.rot, rotated_last=True)   # rotated high above the slot
    assert valid(pl.board, pl.active)
    res = pl.hard_drop()                                       # original code counted a T-Spin here
    assert res.lines >= 1 and not res.spin and pl.spins == 0


def test_real_spin_path_is_t_spin():
    b = _tss_board()
    pl = Player('P', 0); pl.board = [r[:] for r in b]; pl.active = Piece('T')
    for a in solve_spin_actions(b):
        assert {'left': lambda: pl.move(-1, 0), 'right': lambda: pl.move(1, 0), 'down': lambda: pl.move(0, 1),
                'cw': lambda: pl.rotate(1), 'ccw': lambda: pl.rotate(-1)}[a]()
    res = pl.hard_drop()
    assert res.spin and res.lines >= 1 and pl.spins == 1 and 'T-SPIN' in res.label


def test_soft_drop_after_rotation_clears_rotation_flag():
    pl = Player('P', 0); pl.active = Piece('T', 3, 5)
    pl.rotate(1); assert pl.active.rotated_last
    pl.soft_drop(); assert not pl.active.rotated_last
