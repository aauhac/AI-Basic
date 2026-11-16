"""Read the game state from captured window pixels only (what a human player sees on screen).

The automated player never reads the game's memory: board cells, the current piece and the puzzle
hint squares are recovered from the screenshot colours drawn by tetris/gui.py.
"""
import numpy as np

BOARD_BG = (17, 26, 42)          # '#111a2a'
GRID = (27, 37, 56)              # '#1b2538'
SURFACE2 = (33, 45, 67)          # '#212d43'  normal button
SELECTED = (46, 99, 95)          # '#2e635f'  selected radio button
ACCENT = (74, 214, 200)          # '#4ad6c8'  start button
GOLD = (239, 194, 111)           # '#efc26f'  puzzle hint outline
PIECE_RGB = {'I': '#39c5ef', 'O': '#f0d04d', 'T': '#ac79e7', 'S': '#61d78b', 'Z': '#f07885',
             'J': '#668df2', 'L': '#eead65', 'G': '#758397'}
PIECE_RGB = {k: tuple(int(v[i:i + 2], 16) for i in (1, 3, 5)) for k, v in PIECE_RGB.items()}


def _near(px, rgb, tol=10):
    return all(abs(int(a) - b) <= tol for a, b in zip(px, rgb))


def _runs(mask):
    """[(start, end_inclusive)] of True runs in a 1-D bool array."""
    d = np.diff(np.concatenate(([0], mask.astype(np.int8), [0])))
    return list(zip(np.where(d == 1)[0], np.where(d == -1)[0] - 1))


def color_mask(img, rgb, tol=6):
    return np.all(np.abs(img.astype(np.int16) - np.array(rgb, np.int16)) <= tol, axis=2)


# ----------------------------------------------------------------------------- buttons
def find_buttons(img):
    """Locate the toolbar widgets by colour. Returns {'modes': [5 centres], 'tools': [...], ...}
    with (x, y) frame coordinates."""
    top = img[:160]
    btn = color_mask(top, SURFACE2) | color_mask(top, SELECTED) | color_mask(top, ACCENT)
    rows = []
    for y in range(top.shape[0]):
        runs = [(a, b) for a, b in _runs(btn[y]) if 30 <= b - a <= 200]
        rows.append(runs)
    # mode row: first row with exactly 5 runs; tool row: first row (below) with >= 8 runs
    mode_y = next(y for y, r in enumerate(rows) if len(r) == 5)
    tool_y = next(y for y, r in enumerate(rows) if y > mode_y + 25 and len(r) >= 8)
    modes = [((a + b) // 2, mode_y + 8) for a, b in rows[mode_y]]
    tr = rows[tool_y]
    tools = [((a + b) // 2, tool_y + 10) for a, b in tr]
    return {'modes': dict(zip(('solo', 'two', 'versus', 'ai', 'puzzle'), modes)),
            'start': tools[0], 'pause': tools[1], 'stop': tools[2], 'hint': tools[3], 'records': tools[4],
            'diff': dict(zip(('easy', 'normal', 'hard'), tools[5:8])),
            'coach': (tr[7][1] + 55, tool_y + 10)}


# ----------------------------------------------------------------------------- boards
class BoardGeom:
    def __init__(self, x0, y0, cell):
        self.x0, self.y0, self.cell = x0, y0, cell

    def center(self, x, y):
        return self.x0 + x * self.cell + self.cell // 2, self.y0 + y * self.cell + self.cell // 2

    def __repr__(self):
        return f'BoardGeom(x0={self.x0}, y0={self.y0}, cell={self.cell})'


def find_boards(img):
    """Board rectangles = large areas of the board background colour (call when boards are mostly empty)."""
    m = color_mask(img, BOARD_BG, 2) | color_mask(img, GRID, 2)
    cols = m.sum(axis=0)
    boards = []
    for a, b in _runs(cols > 120):
        if b - a < 100:
            continue
        rows = m[:, a:b + 1].sum(axis=1)
        ys = np.where(rows > (b - a) * 0.3)[0]
        cell = round((b - a + 1) / 10)
        boards.append(BoardGeom(int(a), int(ys[0]), int(cell)))
    return boards


def classify(px):
    if _near(px, BOARD_BG, 14) or _near(px, GRID, 8):
        return None
    best, bd = None, 1e9
    for k, rgb in PIECE_RGB.items():
        d = sum((int(a) - b) ** 2 for a, b in zip(px, rgb))
        if d < bd:
            best, bd = k, d
    return best if bd < 40 ** 2 * 3 else '?'


def read_grid(img, g, rows=20):
    """20x10 list of kinds / None from cell centres."""
    out = []
    for y in range(rows):
        row = []
        for x in range(10):
            cx, cy = g.center(x, y)
            patch = img[cy - 2:cy + 3, cx - 2:cx + 3].reshape(-1, 3)
            row.append(classify(np.median(patch, axis=0)))
        out.append(row)
    return out


def read_hint_cells(img, g):
    """Cells outlined by the gold puzzle-hint rectangle (drawn by the game for hint level >= 2)."""
    out = set()
    c = g.cell
    for y in range(20):
        for x in range(10):
            x0 = g.x0 + x * c; y0 = g.y0 + y * c
            pts = [(x0 + 3, y0 + c // 2), (x0 + c - 3, y0 + c // 2), (x0 + c // 2, y0 + 3), (x0 + c // 2, y0 + c - 3)]
            if sum(_near(img[py, px], GOLD, 30) for px, py in pts) >= 3:
                out.add((x, y))
    return frozenset(out)


def grid_text(grid):
    return '\n'.join(''.join(k if k else '.' for k in row) for row in grid)
