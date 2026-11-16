"""Run identical bug scenarios against a project directory (original or fixed) using only the API
that both versions share.  Usage: python verification/reproduce_bugs.py <project_dir> <out.json>"""
import json, sys, time, traceback
from pathlib import Path
root = Path(sys.argv[1]).resolve(); sys.path.insert(0, str(root))
from tetris.engine import Player, Piece, ghost, empty_board, W, H, valid, lock_piece
out = {'project': root.name}

def run(name, fn):
    try:
        out[name] = fn()
    except Exception as exc:
        out[name] = {'exception': f'{type(exc).__name__}: {exc}'}
    print(name, out[name])

def o_rotation():
    p = Player('P', 0); p.active = Piece('O')
    p.active = ghost(p.board, p.active)
    before = sorted(p.active.squares())
    p.rotate(1)
    after = sorted(p.active.squares())
    res = {'cells_before': before, 'cells_after_rotate': after, 'valid_after_rotate': valid(p.board, p.active)}
    p.hard_drop()
    res['hard_drop'] = 'ok'
    return res

def garbage_one_line():
    p = Player('P', 3); p.pending = 1
    p.hard_drop()
    return {'game_over_after_receiving_1_line': p.over}

def garbage_in_versus():
    a, b = Player('P1', 4), Player('P2', 4)
    for y in range(H - 4, H):
        a.board[y] = ['G'] * W; a.board[y][4] = None
    a.active = Piece('I', 2, 0, 1)
    r = a.hard_drop(); b.pending += r.attack
    b.hard_drop()
    return {'attack_sent': r.attack, 'receiver_game_over': b.over}

def air_spin():
    x = 3; b = empty_board()
    for j in range(W):
        if j != x: b[H - 1][j] = 'G'
        if j not in (x, x + 1, x + 2): b[H - 2][j] = 'G'
    b[H - 3][x - 1] = 'G'
    p = Player('P', 0); p.board = b
    p.active = Piece('T', x - 1, 0, 1, rotated_last=True)   # rotated at the top, then dropped 17 rows
    r = p.hard_drop()
    return {'lines': r.lines, 'counted_as_t_spin': r.spin}

def puzzle_spin_stat():
    import tkinter as tk
    from tetris.gui import GameApp
    from tetris.puzzles import solve_spin_actions
    tmp = Path(__file__).resolve().parent / '_repro_records.json'
    rootw = tk.Tk(); app = GameApp(rootw)
    app.save_path = tmp
    app.mode.set('puzzle'); app.difficulty.set('easy'); app.start()
    route = solve_spin_actions(app.players[0].board)
    for a in route:
        app.handle_action(0, {'down': 'soft'}.get(a, a))
    app.handle_action(0, 'hard')
    rootw.update()
    msg = getattr(app, 'message', None) or (app.message_var.get() if hasattr(app, 'message_var') else '')
    res = {'success_message': '성공' in msg, 'player_spins_counter': app.players[0].spins}
    try: app.close()
    except Exception: rootw.destroy()
    tmp.unlink(missing_ok=True)
    return res

for n, f in [('o_rotation_on_floor', o_rotation), ('receive_1_garbage_line', garbage_one_line),
             ('versus_tetris_attack', garbage_in_versus), ('rotate_in_air_then_hard_drop', air_spin),
             ('puzzle_success_spin_counter', puzzle_spin_stat)]:
    run(n, f)
Path(sys.argv[2]).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
