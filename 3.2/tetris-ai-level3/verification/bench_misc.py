"""Puzzle generation time and record save/load time.  Usage: python verification/bench_misc.py <out.json>"""
import json, sys, time, statistics, tempfile, platform
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tetris.puzzles import generate, validate_puzzle
from tetris.storage import load_stats, save_stats, finish_match
from tetris.engine import Player

def summ(v):
    v = sorted(v)
    return {'n': len(v), 'mean_ms': round(statistics.mean(v), 2), 'p95_ms': round(v[int(len(v) * .95) - 1], 2), 'max_ms': round(v[-1], 2)}

res = {'python': platform.python_version(), 'puzzle_generation': {}}
for d in ('easy', 'normal', 'hard'):
    ts, att, ok = [], [], 0
    for seed in range(50):
        t = time.perf_counter(); p = generate(seed, d); ts.append((time.perf_counter() - t) * 1000)
        att.append(p.attempts); ok += validate_puzzle(p)
    res['puzzle_generation'][d] = dict(summ(ts), seeds=50, validated=ok, max_attempts=max(att))
    print(d, res['puzzle_generation'][d], flush=True)
path = Path(tempfile.mkdtemp()) / 'records.json'
st = load_stats(path); a, b = Player('P1', 1), Player('AI', 1)
for i in range(60):
    finish_match(st, [a, b], 'P1', 'ai')
sv, ld = [], []
for _ in range(200):
    t = time.perf_counter(); save_stats(path, st); sv.append((time.perf_counter() - t) * 1000)
    t = time.perf_counter(); load_stats(path); ld.append((time.perf_counter() - t) * 1000)
res['records'] = {'file_bytes': path.stat().st_size, 'history_entries': len(st['history']), 'save': summ(sv), 'load': summ(ld)}
print(res['records'])
Path(sys.argv[1]).write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding='utf-8')
