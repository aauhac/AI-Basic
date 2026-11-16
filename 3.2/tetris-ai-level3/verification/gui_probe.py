"""Measure GUI responsiveness of a project version under identical load.
Usage: python verification/gui_probe.py <project_dir> <out.json> [seconds] [difficulty]
Load: 'Human vs AI' mode, AI difficulty as given (default hard), AI coach on, synthetic human key
presses every 150 ms (Left/Right/Up) and a hard drop every 1.2 s, all through Tk's event queue.
Metrics:
  * event-loop stall: a 10 ms after() probe records the real gap between its runs
    (a long gap = the Tk thread was blocked: no input, no drawing during that time)
  * key latency: time from event_generate(..., when='tail') to the moment the binding chain
    (the app's own handler first, then ours) has finished processing the key."""
import json, sys, time, statistics, tempfile, os
from pathlib import Path
root_dir = Path(sys.argv[1]).resolve(); sys.path.insert(0, str(root_dir))
out = Path(sys.argv[2]); SECONDS = float(sys.argv[3]) if len(sys.argv) > 3 else 20; DIFF = sys.argv[4] if len(sys.argv) > 4 else 'hard'
import tkinter as tk
from tetris.gui import GameApp

root = tk.Tk()
app = GameApp(root)
app.save_path = Path(tempfile.mkdtemp()) / 'probe_records.json'
root.geometry('1460x870+0+0'); root.update(); root.focus_force(); root.update()
app.mode.set('ai'); app.difficulty.set(DIFF); app.coach.set(True)
app.mode_changed(); app.start(); root.update()

gaps, lat, pending = [], [], []
last = [time.perf_counter()]
def probe():
    now = time.perf_counter(); gaps.append((now - last[0]) * 1000); last[0] = now
    root.after(10, probe)
def on_key(e):
    if pending:
        lat.append((time.perf_counter() - pending.pop(0)) * 1000)
root.bind_all('<KeyPress>', on_key, add='+')
seq = ['Left', 'Right', 'Up', 'Left', 'Up', 'Right', 'Left', 'space']
k = [0]
def send():
    ks = seq[k[0] % len(seq)]; k[0] += 1
    pending.append(time.perf_counter())
    root.event_generate('<KeyPress>', keysym=ks, when='tail')
    root.event_generate('<KeyRelease>', keysym=ks, when='tail')
    root.after(150, send)
t0 = time.perf_counter()
root.after(10, probe); root.after(200, send)
root.after(int(SECONDS * 1000), root.quit)
root.mainloop()
elapsed = time.perf_counter() - t0
def summ(v):
    v = sorted(v)
    return {'n': len(v), 'mean_ms': round(statistics.mean(v), 1), 'p95_ms': round(v[int(len(v) * .95) - 1], 1),
            'p99_ms': round(v[int(len(v) * .99) - 1], 1), 'max_ms': round(v[-1], 1)}
res = {'project': root_dir.name, 'seconds': round(elapsed, 1), 'difficulty': DIFF,
       'loop_gap': summ(gaps[3:]), 'key_latency': summ(lat),
       'stalls_over_100ms': sum(g > 100 for g in gaps[3:]), 'stalls_over_250ms': sum(g > 250 for g in gaps[3:]),
       'ai_pieces': app.players[1].pieces if hasattr(app.players[1], 'pieces') else None,
       'ai_lines': app.players[1].lines, 'human_lines': app.players[0].lines,
       'game_over': [p.over for p in app.players]}
if not hasattr(app.players[1], 'pieces'):
    res['ai_pieces'] = sum(v is not None for r in app.players[1].board for v in r) // 4 + app.players[1].lines * 10 // 4
    res['ai_pieces_note'] = 'original Player has no piece counter; estimated from board cells'
print(json.dumps(res, ensure_ascii=False), flush=True)
out.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding='utf-8')
try: root.destroy()
except Exception: pass
os._exit(0)
