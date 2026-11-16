"""Save player statistics as JSON, tolerant of missing or damaged data files.

Writes are atomic (temp file + os.replace) so a crash while saving cannot corrupt records.json.
"""
from pathlib import Path
import copy
import json
import os
import time

DEFAULT = {'matches': 0, 'aborted': 0,
           'wins': {'P1': 0, 'P2': 0, 'AI': 0}, 'losses': {'P1': 0, 'P2': 0, 'AI': 0},
           'best_score': {'P1': 0, 'P2': 0, 'AI': 0}, 'lines': {'P1': 0, 'P2': 0, 'AI': 0},
           'puzzles_solved': 0, 'puzzles_attempted': 0, 'history': []}


def load_stats(path):
    result = copy.deepcopy(DEFAULT)
    try:
        data = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError, TypeError):
        return result
    if not isinstance(data, dict):
        return result
    for k, v in data.items():
        if k not in result or not isinstance(v, type(result[k])):
            continue
        if isinstance(v, dict):
            # keep default player keys, accept extra numeric entries from the file
            result[k].update({n: c for n, c in v.items() if isinstance(c, int)})
        else:
            result[k] = v
    return result


def save_stats(path, stats):
    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix('.tmp')
    tmp.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(tmp, dest)


def finish_match(stats, players, winner=None, mode=None, aborted=False):
    """Record one game. Best score and cleared lines always count; wins/losses only for decided
    multi-player matches; an aborted game is counted separately and never as a win or loss."""
    if aborted:
        stats['aborted'] = stats.get('aborted', 0) + 1
    else:
        stats['matches'] += 1
    for p in players:
        name = p.name
        for key in ('best_score', 'lines', 'wins', 'losses'):
            stats[key].setdefault(name, 0)
        stats['best_score'][name] = max(stats['best_score'][name], p.score)
        stats['lines'][name] += p.lines
        if winner and not aborted and len(players) > 1:
            stats['wins' if name == winner else 'losses'][name] += 1
    result = 'aborted' if aborted else (winner or ('draw' if len(players) > 1 else 'game over'))
    stats['history'] = (stats['history'] + [{
        'time': time.strftime('%Y-%m-%d %H:%M:%S'), 'mode': mode, 'winner': winner, 'result': result,
        'mode_players': [p.name for p in players], 'scores': {p.name: p.score for p in players},
        'lines': {p.name: p.lines for p in players}}])[-50:]
