"""Puzzle generation: real keyboard reachability of every piece, necessity of preparation pieces,
determinism, hints, success/failure bookkeeping and bounded generation."""
import pytest
from tetris.engine import Piece, Player, valid, lock_piece
from tetris import puzzles
from tetris.puzzles import (generate, validate_puzzle, legal_spin_locks, reachable_placements, PuzzleSession,
                            PuzzleGenerationError, solve_spin_actions)

SEEDS = [0, 5, 13, 77, 2024]
LEVELS = [('easy', ['T']), ('normal', ['I', 'T']), ('hard', ['I', 'O', 'T'])]


def press(pl, action):
    return {'left': lambda: pl.move(-1, 0), 'right': lambda: pl.move(1, 0), 'down': lambda: pl.move(0, 1),
            'cw': lambda: pl.rotate(1), 'ccw': lambda: pl.rotate(-1)}[action]()


@pytest.mark.parametrize('level,seq', LEVELS)
def test_generated_puzzles_valid_and_deterministic(level, seq):
    for seed in SEEDS:
        a, b = generate(seed, level), generate(seed, level)
        assert a.sequence == seq and len(a.solution) == len(seq) == len(a.routes)
        assert validate_puzzle(a)
        assert a.board == b.board and a.solution == b.solution and a.routes == b.routes


@pytest.mark.parametrize('level,seq', LEVELS)
def test_every_piece_solved_by_its_recorded_key_route(level, seq):
    """Play every piece -- preparation pieces included -- by pressing its recorded keys."""
    for seed in SEEDS:
        pz = generate(seed, level)
        ses = PuzzleSession(pz)
        pl = ses.player
        for i, route in enumerate(pz.routes):
            assert pl.active.kind == pz.sequence[i]
            for a in route[:-1]:
                assert press(pl, a), (level, seed, i, a)
            x, y, r = pz.solution[i]
            assert sorted(pl.active.squares()) == sorted(Piece(pz.sequence[i], x, y, r).squares())
            assert route[-1] == 'hard'
            ses.lock(hard=True)
        assert ses.complete and not ses.failed
        assert pl.spins == 1 and pl.lines >= pz.target_lines


@pytest.mark.parametrize('level', ['normal', 'hard'])
def test_preparation_pieces_are_necessary(level):
    for seed in SEEDS:
        pz = generate(seed, level)
        assert not any(n >= pz.target_lines for _, n in legal_spin_locks(pz.board))
        if level == 'hard':
            for kind, (x, y, r) in zip(pz.sequence[:2], pz.solution[:2]):
                only = lock_piece(pz.board, Piece(kind, x, y, r))[0]
                assert not any(n >= pz.target_lines for _, n in legal_spin_locks(only))


def test_prep_placements_are_reachable_by_bfs():
    pz = generate(3, 'hard')
    board = [r[:] for r in pz.board]
    for kind, (x, y, r) in zip(pz.sequence[:-1], pz.solution[:-1]):
        p = Piece(kind, x, y, r)
        assert frozenset(p.squares()) in reachable_placements(board, kind)
        board = lock_piece(board, p)[0]


def test_tspin_route_uses_rotation_and_kicks():
    for seed in SEEDS:
        route = generate(seed, 'easy').routes[-1]
        assert route[-2] in ('cw', 'ccw')           # last move before locking is a rotation


def test_hint_matches_solution():
    pz = generate(11, 'hard')
    ses = PuzzleSession(pz)
    for i, kind in enumerate(pz.sequence):
        text1, sq1 = ses.hint(1)
        text3, sq3 = ses.hint(3)
        assert sq1 is None and kind in text1
        if kind != 'T':
            x, y, r = pz.solution[i]
            assert sq3 == frozenset(Piece(kind, x, y, r).squares()) and f'x={x}' in text3
            for a in pz.routes[i][:-1]:
                press(ses.player, a)
        else:
            # T hint is recomputed on the real board and must be a genuine spin lock
            targets = {frozenset(p.squares()) for p, n in legal_spin_locks(ses.player.board) if n >= pz.target_lines}
            assert sq3 in targets
            route = solve_spin_actions(ses.player.board, min_lines=pz.target_lines)
            for a in route:
                press(ses.player, a)
        ses.lock()
    assert ses.complete


def test_hint_detects_off_witness_path():
    pz = generate(11, 'normal')
    ses = PuzzleSession(pz)
    ses.player.move(-1, 0); ses.player.move(-1, 0); ses.player.move(-1, 0)
    ses.lock()                       # I placed somewhere else
    text, sq = ses.hint(3)
    assert sq is not None or '경로' in text


def test_failure_when_dropping_t_without_spin_and_outcome_is_final():
    pz = generate(5, 'easy')
    ses = PuzzleSession(pz)
    res = ses.lock()                  # straight hard drop of the spawn T
    assert res is not None and not ses.complete and ses.failed and ses.player.spins == 0
    assert ses.lock() is None and ses.failed and ses.moves == 1


def test_success_updates_spin_statistics_once():
    pz = generate(5, 'easy')
    ses = PuzzleSession(pz)
    for a in pz.routes[0][:-1]:
        press(ses.player, a)
    n, spin = ses.lock()
    assert spin and n == pz.target_lines and ses.complete
    assert ses.player.spins == 1 and ses.player.lines == n and ses.player.score == n * 100 + 250
    assert ses.lock() is None and ses.player.spins == 1          # no duplicate success


def test_generation_failure_is_bounded(monkeypatch):
    calls = []

    def impossible(rng, difficulty):
        calls.append(1)
        from tetris.engine import empty_board
        return empty_board(), []
    monkeypatch.setattr(puzzles, '_template', impossible)
    with pytest.raises(PuzzleGenerationError):
        generate(1, 'easy')
    assert len(calls) == puzzles.MAX_ATTEMPTS
