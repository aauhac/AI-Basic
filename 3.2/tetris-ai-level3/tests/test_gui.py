"""Integration tests with a real Tk window: keyboard events go through Tk's event queue
(event_generate) and the real GameApp main loop is pumped. Skipped when no display exists."""
import gc
import json
import sys
import time
import pytest
from conftest import tetris_ready

tk = pytest.importorskip('tkinter')
pytestmark = pytest.mark.gui

from tetris.engine import Piece, W, H, valid      # noqa: E402
from tetris import ai                              # noqa: E402
from tetris.gui import GameApp                     # noqa: E402

KEYS = {'left': 'Left', 'right': 'Right', 'down': 'Down', 'cw': 'Up', 'ccw': 'z', 'hard': 'space'}


@pytest.fixture
def app(tmp_path):
    # Tk interpreters left in reference cycles by earlier tests must be freed on THIS (the Tcl)
    # thread; if a worker thread's allocation triggered that collection, Tcl would abort.
    gc.collect()
    root = None
    for attempt in range(3):          # Tk init on Windows occasionally fails transiently when
        try:                          # many interpreters are created in one process
            root = tk.Tk(); break
        except tk.TclError as exc:
            err = exc; time.sleep(0.3)
    if root is None:
        pytest.skip(f'no display: {err}')
    errors = []
    root.report_callback_exception = lambda *a: errors.append(a)
    a = GameApp(root, save_path=tmp_path / 'records.json')
    a.errors = errors
    pump(a, 0.1)
    root.focus_force()      # Tk delivers key events only to the focused application window
    pump(a, 0.05)
    yield a
    assert not errors, errors
    if root.winfo_exists():
        a.close()
    a.worker.thread.join(2)


def pump(app, sec):
    end = time.monotonic() + sec
    while time.monotonic() < end:
        app.root.update(); time.sleep(0.004)


def key(app, keysym, hold=0.0):
    if app.root.focus_get() is None:
        app.root.focus_force(); app.root.update()
    app.root.event_generate('<KeyPress>', keysym=keysym, when='tail')
    pump(app, hold or 0.01)
    app.root.event_generate('<KeyRelease>', keysym=keysym, when='tail')
    pump(app, 0.05)


def start(app, mode, diff='normal'):
    app.mode.set(mode); app.mode_changed(); app.difficulty.set(diff); app.start(); pump(app, 0.05)


def test_solo_keyboard_controls(app):
    start(app, 'solo')
    p = app.players[0]
    x0 = p.active.x
    key(app, 'Left'); assert p.active.x == x0 - 1
    key(app, 'Right'); key(app, 'Right'); assert p.active.x == x0 + 1
    r0 = p.active.rot; key(app, 'Up'); assert p.active.rot == (r0 + 1) % 4 or p.active.kind == 'O'
    y0 = p.active.y; key(app, 'Down'); assert p.active.y == y0 + 1
    kind = p.active.kind; key(app, 'c'); assert p.held == kind
    key(app, 'space'); assert p.pieces == 1 and not p.over


def test_das_auto_repeat_while_key_held(app):
    start(app, 'solo')
    p = app.players[0]
    x0 = p.active.x
    app.root.event_generate('<KeyPress>', keysym='Left', when='tail')
    pump(app, 0.45)
    assert p.active.x <= x0 - 3 or p.active.x == 0 or min(sx for sx, _ in p.active.squares()) == 0
    app.root.event_generate('<KeyRelease>', keysym='Left', when='tail'); pump(app, 0.1)
    x1 = p.active.x; pump(app, 0.3)
    assert p.active.x == x1


def test_two_players_independent_simultaneous_input(app):
    start(app, 'two')
    a, b = app.players
    xa, xb = a.active.x, b.active.x
    app.root.event_generate('<KeyPress>', keysym='Left', when='tail')
    app.root.event_generate('<KeyPress>', keysym='d', when='tail')
    pump(app, 0.3)                                      # both keys held at the same time
    for k in ('Left', 'd'):
        app.root.event_generate('<KeyRelease>', keysym=k, when='tail')
    pump(app, 0.1)
    assert a.active.x < xa and b.active.x > xb
    key(app, 'f')
    assert b.pieces == 1 and a.pieces == 0 and a.board is not b.board


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows virtual-key fallback')
def test_p2_keys_work_with_korean_ime(app):
    """With a Korean IME active, Windows reports a Hangul keysym but the virtual-key code of the
    physical key. Tk cannot synthesise IME keysyms, so the key-name mapping is checked directly
    and then fed through the real handler."""
    from types import SimpleNamespace
    start(app, 'two')
    b = app.players[1]; xb = b.active.x
    ev = SimpleNamespace(keysym='ㅇ', keycode=68)            # 'ㅇ' typed on the D key
    assert app._keyname(ev) == 'd'
    app.key_down(ev); app.key_up(ev); pump(app, 0.06)
    assert b.active.x == xb + 1


def test_versus_attack_is_sent_received_and_game_continues(app):
    start(app, 'versus')
    a, b = app.players
    tetris_ready(a)
    key(app, 'space')
    assert a.lines == 4 and b.pending == 4 and '공격 +4' in app.message_var.get()
    key(app, 'f')                                        # P2 locks -> garbage inserted
    assert b.pending == 0 and b.garbage_received == 4 and not b.over and b.active is not None
    assert all(sum(v is None for v in row) == 1 for row in b.board[H - 4:])
    assert not app.finished


def test_ai_mode_plays_in_background_without_blocking(app):
    start(app, 'ai', 'hard')
    gaps = []; last = [time.perf_counter()]

    def probe():
        now = time.perf_counter(); gaps.append(now - last[0]); last[0] = now
        app.root.after(10, probe)
    app.root.after(10, probe)
    ai_player = app.players[1]
    deadline = time.monotonic() + 12
    while ai_player.pieces < 4 and time.monotonic() < deadline:
        pump(app, 0.2)
    assert ai_player.pieces >= 4 and not ai_player.over
    assert valid(ai_player.board, ai_player.active)
    assert max(gaps[5:]) < 0.25, max(gaps)                  # event loop never blocked for long


def test_redraw_does_not_rerun_ai_search(app):
    start(app, 'ai', 'hard')
    pump(app, 0.6)
    s0 = ai.COUNTERS['searches']
    app.paused = True                                     # freeze state (no new pieces)
    for _ in range(40):
        app.dirty = True; app.redraw()
    assert ai.COUNTERS['searches'] == s0


def test_coach_panel_shows_real_evaluation_and_recommendation(app):
    start(app, 'solo')
    pump(app, 0.3)
    p = app.players[0]
    pv = app.preview(0)
    ref = ai.preview_at(p.board, p.active)
    assert abs(pv.score - ref.score) < 1e-9 and pv.parts == ref.parts
    best = app.coach_best(0)
    exp, _ = ai.choose(p.board, p.active.kind, p.next[0], 'normal')
    assert best is not None and best.piece.squares() == exp.piece.squares()


def test_pause_freezes_everything_and_resume_continues(app):
    start(app, 'ai', 'normal')
    pump(app, 1.0)
    key(app, 'p')
    snap = [(pl.pieces, pl.score, pl.active.x, pl.active.y, pl.active.rot) for pl in app.players]
    key(app, 'Left'); key(app, 'space')
    pump(app, 1.5)
    assert [(pl.pieces, pl.score, pl.active.x, pl.active.y, pl.active.rot) for pl in app.players] == snap
    key(app, 'p'); pump(app, 1.5)
    assert app.players[1].pieces > snap[1][0]


def test_restart_and_mode_change_ignore_stale_ai_results(app):
    start(app, 'ai', 'hard')
    pump(app, 0.5)
    old_gid = app.game_id
    old_player = app.players[1]
    key(app, 'r')
    assert app.game_id == old_gid + 1 and app.players[1] is not old_player
    assert all(pl.pieces == 0 for pl in app.players)
    stale = Piece('I', 0, 18, 0)
    fake = ai.Candidate(stale, 1e9, {}, 0, False)
    app.worker.results.put((('ai', old_gid, 1, app.players[1].piece_id), fake, 1.0))
    pump(app, 0.1)
    plan = app.ai_plan.get(1)
    assert plan is None or plan['best'] is not fake
    app.mode.set('solo'); app.mode_changed()
    app.worker.results.put((('ai', app.game_id - 1, 1, 1), fake, 1.0))
    pump(app, 0.1)
    assert app.players == [] and not app.errors


def test_stop_during_ai_computation(app):
    start(app, 'ai', 'hard')
    app.root.update()
    key(app, 'Escape')
    pieces = [pl.pieces for pl in app.players]
    pump(app, 1.0)
    assert [pl.pieces for pl in app.players] == pieces and app.finished and not app.active
    key(app, 'space')
    assert [pl.pieces for pl in app.players] == pieces


def test_game_over_decides_winner_and_saves_records(app):
    start(app, 'versus')
    a, b = app.players
    for y in range(1, H):
        b.board[y] = ['G'] * W; b.board[y][(y * 3) % W] = None
    b.active = Piece('O', 3, -1)
    key(app, 'f')                                         # locks above the field -> top-out
    pump(app, 0.1)
    assert app.finished and app.match.winner == 'P1'
    rec = json.loads(app.save_path.read_text(encoding='utf-8'))
    assert rec['wins']['P1'] == 1 and rec['losses']['P2'] == 1 and rec['matches'] == 1
    key(app, 'space')                                     # input after game end is ignored
    assert a.pieces == 0


def test_puzzle_solved_by_keyboard_updates_stats_once(app):
    start(app, 'puzzle', 'hard')
    ses = app.session; pz = ses.puzzle
    for i, route in enumerate(pz.routes):
        for a in route:
            app.last_fall[0] = time.monotonic()           # keep gravity from interleaving with the scripted keys
            key(app, KEYS[a])
    assert ses.complete and app.finished
    assert app.players[0].spins == 1
    rec = json.loads(app.save_path.read_text(encoding='utf-8'))
    assert rec['puzzles_solved'] == 1 and rec['puzzles_attempted'] == 1
    key(app, 'space'); key(app, 'Up')
    rec2 = json.loads(app.save_path.read_text(encoding='utf-8'))
    assert rec2['puzzles_solved'] == 1 and app.players[0].spins == 1


def test_puzzle_hint_levels_and_failure(app):
    start(app, 'puzzle', 'easy')
    key(app, 'h'); assert app.hint_level == 1 and '힌트 1' in app.message_var.get()
    key(app, 'h'); key(app, 'h'); assert app.hint_level == 3 and app.hint_cells
    x, y, r = app.session.puzzle.solution[-1]
    assert f'x={x}' in app.message_var.get()
    key(app, 'space')                                     # straight drop: not a T-Spin
    assert app.session.failed and app.finished and '실패' in app.message_var.get()


def test_layout_fits_after_resize(app):
    for mode in ('versus', 'solo'):
        start(app, mode)
        for geo in ('900x620', '1600x950'):
            app.root.geometry(geo); pump(app, 0.4)
            cw, ch = app.canvas.winfo_width(), app.canvas.winfo_height()
            L = app.layout
            right_edge = max(sx + sw for sx, sy, sw in L['sides'])
            if L['right']:
                right_edge = max(right_edge, L['right'][0] + L['right'][2])
            assert right_edge <= cw + 1 and L['top'] + L['bh'] + 30 * app.s <= ch + 1, (mode, geo, cw, ch)


def test_records_window_and_reload(app, tmp_path):
    start(app, 'solo')
    app.players[0].score = 777; app.players[0].over = True
    pump(app, 0.1)
    assert app.finished
    top = app.show_records(); pump(app, 0.1); top.destroy()
    app2_root = tk.Toplevel(app.root)        # a second app instance reads the saved file
    from tetris.storage import load_stats
    assert load_stats(app.save_path)['best_score']['P1'] == 777
    app2_root.destroy()
