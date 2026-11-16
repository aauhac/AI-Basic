"""Does difficulty change playing strength?  Usage: python verification/bench_difficulty.py <out.json> [solo_pieces] [matches]
  (a) solo: each difficulty plays the same seeds (7-bag) for up to N pieces;
  (b) head-to-head: AI vs AI through engine.Match with the real attack/garbage rules,
      pieces are alternated one-for-one (equal speed), match capped at 600 pieces each
      (cap reached -> higher score wins)."""
import json, sys, time, statistics
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tetris.engine import Player, Match
from tetris.ai import choose, clear_cache

out = Path(sys.argv[1]); SOLO = int(sys.argv[2]) if len(sys.argv) > 2 else 500; MATCHES = int(sys.argv[3]) if len(sys.argv) > 3 else 10
SEEDS = [101, 202, 303, 404, 505]

def play_piece(p, diff):
    best, _ = choose(p.board, p.active.kind, p.next[0] if p.next else None, diff)
    if best is None:
        p.over = True; return None
    p.active = best.piece.copy()
    return p.hard_drop()

res = {'solo_pieces_cap': SOLO, 'seeds': SEEDS, 'solo': {}, 'versus': {}}
for diff in ('easy', 'normal', 'hard'):
    rows = []
    for seed in SEEDS:
        p = Player('AI', seed=seed, is_ai=True); holes_max = 0
        while not p.over and p.pieces < SOLO:
            play_piece(p, diff)
        rows.append({'seed': seed, 'pieces': p.pieces, 'lines': p.lines, 'score': p.score, 'topped_out': p.over})
    res['solo'][diff] = {'games': rows, 'mean_lines': statistics.mean(r['lines'] for r in rows),
                         'mean_pieces': statistics.mean(r['pieces'] for r in rows),
                         'topouts': sum(r['topped_out'] for r in rows)}
    print('solo', diff, res['solo'][diff]['mean_pieces'], res['solo'][diff]['mean_lines'], 'topouts', res['solo'][diff]['topouts'], flush=True)

for a, b in (('easy', 'normal'), ('normal', 'hard'), ('easy', 'hard')):
    wins = {a: 0, b: 0, 'draw': 0}; lengths = []
    for i in range(MATCHES):
        m = Match('versus', seed=1000 + i)
        diffs = (a, b) if i % 2 == 0 else (b, a)        # alternate sides
        while not m.check_end() and min(p.pieces for p in m.players) < 600:
            for idx, p in enumerate(m.players):
                if not p.over:
                    m.after_lock(idx, play_piece(p, diffs[idx]))
            m.check_end()
        if not m.finished:
            m._by_score('600 pieces cap'); m.finished = True
        w = m.winner
        wins[diffs[0] if w == 'P1' else diffs[1] if w == 'P2' else 'draw'] += 1
        lengths.append(min(p.pieces for p in m.players))
    res['versus'][f'{a}_vs_{b}'] = {'wins': wins, 'matches': MATCHES, 'mean_pieces': statistics.mean(lengths)}
    print('versus', a, b, wins, flush=True)
out.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding='utf-8')
