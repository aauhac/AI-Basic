"""Check that the optimised AI makes exactly the same decisions as the original implementation.
Usage: python verification/check_ai_equivalence.py <original_project_dir> <new_project_dir> <boards.json>"""
import sys, json, importlib.util, types
from pathlib import Path

def load(root, alias):
    root = Path(root).resolve()
    pkg = types.ModuleType(alias); pkg.__path__ = [str(root / 'tetris')]; sys.modules[alias] = pkg
    mods = {}
    for name in ('engine', 'ai'):
        spec = importlib.util.spec_from_file_location(f'{alias}.{name}', root / 'tetris' / f'{name}.py')
        m = importlib.util.module_from_spec(spec); sys.modules[f'{alias}.{name}'] = m; spec.loader.exec_module(m); mods[name] = m
    return mods

old, new = load(sys.argv[1], 'old_tetris'), load(sys.argv[2], 'new_tetris')
states = json.loads(Path(sys.argv[3]).read_text(encoding='utf-8'))
same = total = 0; max_diff = 0.0
for s in states:
    b = [[None if c == '.' else c for c in row] for row in s['board']]
    for d in ('easy', 'normal', 'hard'):
        a, alla = old['ai'].choose(b, s['kind'], s['next'], d)
        c, allc = new['ai'].choose(b, s['kind'], s['next'], d)
        total += 1
        ok = sorted(a.piece.squares()) == sorted(c.piece.squares()) and len(alla) == len(allc)
        diffs = [abs(x.score - y.score) for x, y in zip(alla, allc)]
        max_diff = max(max_diff, max(diffs))
        same += ok and all(sorted(x.piece.squares()) == sorted(y.piece.squares()) for x, y in zip(alla, allc))
print(f'identical ranking: {same}/{total}  max |score diff| = {max_diff:.2e}')
sys.exit(0 if same == total and max_diff < 1e-6 else 1)
