"""AI search-time benchmark.  Usage:
    python verification/bench_ai.py <project_dir> <boards.json> <out.json> [--make-boards]
The same fixed boards are used for every code version, so before/after numbers are comparable.
Boards are produced once by playing seeded games with the *normal* AI and sampling every 3rd state.
"""
import json, sys, time, statistics, platform
from pathlib import Path

project, boards_path, out_path = Path(sys.argv[1]).resolve(), Path(sys.argv[2]), Path(sys.argv[3])
sys.path.insert(0, str(project))
from tetris.engine import Player
from tetris import ai

if '--make-boards' in sys.argv:
    states = []
    for seed in (3, 11, 29, 47, 83):
        p = Player('B', seed=seed)
        for i in range(60):
            if p.over: break
            if i % 3 == 0:
                states.append({'board': [[c or '.' for c in row] for row in p.board],
                               'kind': p.active.kind, 'next': p.next[0]})
            c, _ = ai.choose(p.board, p.active.kind, p.next[0], 'normal')
            if not c: break
            p.active = c.piece; p.lock()
    boards_path.write_text(json.dumps(states), encoding='utf-8')
    print('boards', len(states))

states = json.loads(boards_path.read_text(encoding='utf-8'))
def board_of(s): return [[None if c == '.' else c for c in row] for row in s['board']]

def clear_cache():
    for name in ('clear_cache',):
        f = getattr(ai, name, None)
        if f: f()

result = {'project': project.name, 'python': platform.python_version(), 'machine': platform.processor() or platform.machine(),
          'boards': len(states), 'repeats': 3, 'difficulties': {}}
for diff in ('easy', 'normal', 'hard'):
    times = []
    for _ in range(3):
        for s in states:
            clear_cache()                       # measure cold (uncached) search cost
            b = board_of(s)
            t = time.perf_counter(); ai.choose(b, s['kind'], s['next'], diff); times.append((time.perf_counter() - t) * 1000)
    times.sort()
    result['difficulties'][diff] = {'n': len(times), 'mean_ms': round(statistics.mean(times), 2),
        'median_ms': round(statistics.median(times), 2), 'p95_ms': round(times[int(len(times) * .95) - 1], 2),
        'max_ms': round(times[-1], 2)}
    print(diff, result['difficulties'][diff])
out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
