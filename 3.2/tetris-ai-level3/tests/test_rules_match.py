"""Scoring, combo/B2B, level speed, attack routing per mode, win/loss decisions and records."""
import json
from conftest import tetris_ready
from tetris.engine import W, H, Piece, Player, Match, LINE_SCORE
from tetris.storage import load_stats, save_stats, finish_match


def _clear_ready(pl, lines, column=0):
    """`lines` bottom rows full except `column`, vertical I above it."""
    pl.board = [[None] * W for _ in range(H)]
    for y in range(H - lines, H):
        pl.board[y] = ['G'] * W; pl.board[y][column] = None
    pl.active = Piece('I', column - 2, 0, 1)
    return pl


def test_line_clear_scores_one_to_four():
    for n in (1, 2, 3, 4):
        pl = _clear_ready(Player('P', 1), n)
        res = pl.hard_drop()
        assert res.lines == n
        drop_points = 2 * 16        # vertical I falls from y=0 to y=16 (cells end on the floor)
        assert res.gained == LINE_SCORE[n] and pl.score == LINE_SCORE[n] + drop_points


def test_combo_adds_score_and_attack():
    pl = _clear_ready(Player('P', 1), 1)
    r1 = pl.hard_drop()
    pl.board = [[None] * W for _ in range(H)]
    pl.board[H - 1] = ['G'] * W; pl.board[H - 1][5] = None
    pl.active = Piece('I', 3, 0, 1)                                  # vertical I in column 5
    r2 = pl.hard_drop()
    assert r1.combo == 0 and r2.combo == 1
    assert r2.gained == LINE_SCORE[1] + 50 and r2.attack == 1        # single(0) + combo 1


def test_back_to_back_tetris_bonus():
    pl = tetris_ready(Player('P', 1))
    r1 = pl.hard_drop()
    tetris_ready(pl)
    r2 = pl.hard_drop()
    assert r1.attack == 4 and not r1.b2b
    assert r2.b2b and r2.attack == 4 + 1 + 1 and r2.gained == 1200 + 50 and 'B2B' in r2.label


def test_level_increases_gravity():
    pl = Player('P', 1)
    d1 = pl.gravity_delay()
    pl.lines = 10
    _clear_ready(pl, 1); pl.hard_drop()
    assert pl.level == 2 and pl.gravity_delay() < d1


def test_two_player_simultaneous_mode_sends_no_attack():
    m = Match('two', seed=4)
    tetris_ready(m.players[0])
    res = m.players[0].hard_drop()
    assert res.attack == 4 and m.after_lock(0, res) == 0 and m.players[1].pending == 0


def test_versus_and_ai_modes_route_attacks_both_ways():
    for mode in ('versus', 'ai'):
        m = Match(mode, seed=4)
        a, b = m.players
        tetris_ready(a); m.after_lock(0, a.hard_drop())
        assert b.pending == 4
        tetris_ready(b); res = b.hard_drop(); m.after_lock(1, res)
        assert res.cancelled == 4 and res.attack == 0 and a.pending == 0 and b.pending == 0
        assert not a.over and not b.over


def test_simultaneous_attacks_partially_cancel():
    m = Match('versus', seed=1)
    a, b = m.players
    a.pending = 2                       # b attacked first
    tetris_ready(a); res = a.hard_drop(); m.after_lock(0, res)
    assert res.cancelled == 2 and res.attack == 2 and b.pending == 2


def test_players_are_independent():
    m = Match('versus', seed=8)
    a, b = m.players
    assert a.board is not b.board and a.next is not b.next and a.bag is not b.bag
    assert a.active.kind == b.active.kind and list(a.next) == list(b.next)   # same seed -> fair
    a.move(-1, 0); a.hard_drop()
    assert all(v is None for row in b.board for v in row) and b.pieces == 0


def test_win_rules_per_mode():
    m = Match('solo'); m.players[0].over = True
    assert m.check_end() and m.winner is None
    m = Match('versus'); m.players[1].over = True
    assert m.check_end() and m.winner == 'P1'
    m = Match('ai'); m.players[0].over = True
    assert m.check_end() and m.winner == 'AI'
    m = Match('two'); m.players[0].over = True
    assert not m.check_end()                       # the other player keeps playing
    m.players[1].score = 50; m.players[1].over = True
    assert m.check_end() and m.winner == 'P2'
    m = Match('versus'); m.players[0].over = m.players[1].over = True
    assert m.check_end() and m.winner is None      # equal score -> draw


def test_records_win_loss_lines_and_reload(tmp_path):
    path = tmp_path / 'records.json'
    st = load_stats(path)
    m = Match('ai', seed=1)
    m.players[0].score = 1234; m.players[0].lines = 7; m.players[1].over = True; m.check_end()
    finish_match(st, m.players, m.winner, 'ai'); save_stats(path, st)
    again = load_stats(path)
    assert again['matches'] == 1 and again['wins']['P1'] == 1 and again['losses']['AI'] == 1
    assert again['best_score']['P1'] == 1234 and again['lines']['P1'] == 7
    assert again['history'][-1]['mode'] == 'ai' and again['history'][-1]['winner'] == 'P1'


def test_aborted_and_solo_games_never_count_as_wins(tmp_path):
    st = load_stats(tmp_path / 'x.json')
    p = Player('P1', 1); p.score = 99
    finish_match(st, [p], None, 'solo')
    finish_match(st, [p, Player('P2', 1)], None, 'versus', aborted=True)
    assert st['matches'] == 1 and st['aborted'] == 1 and st['wins']['P1'] == 0 and st['losses']['P1'] == 0
    assert st['best_score']['P1'] == 99


def test_partial_record_file_is_merged(tmp_path):
    path = tmp_path / 'old.json'
    path.write_text(json.dumps({'matches': 3, 'wins': {'P1': 2}, 'unknown': 1}), encoding='utf-8')
    st = load_stats(path)
    assert st['matches'] == 3 and st['wins']['P1'] == 2 and st['wins']['AI'] == 0 and 'unknown' not in st
