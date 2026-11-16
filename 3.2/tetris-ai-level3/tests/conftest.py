import sys
from pathlib import Path

# Make `import tetris` work no matter how pytest is launched (pytest / python -m pytest / IDE).
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tetris.engine import W, H, Piece  # noqa: E402


def tetris_ready(player, column=4):
    """Bottom 4 rows full except `column`, active piece = vertical I above the well."""
    for y in range(H - 4, H):
        player.board[y] = ['G'] * W
        player.board[y][column] = None
    player.active = Piece('I', column - 2, 0, 1)   # I rotation 1 occupies local column 2
    return player
