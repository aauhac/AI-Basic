"""TXT <-> Maze 변환. 내용이 유효한지는 validator 가 판단한다."""

from pathlib import Path

from maze.model import Maze


def parse_maze(text: str) -> Maze:
    """줄바꿈만 제거하고 나머지 문자는 그대로 둔다.

    행 끝 공백까지 지우면 '행 길이 불일치' 를 validator 가 잡을 수 없으므로
    여기서는 정리하지 않는다.
    """
    lines = [line.rstrip("\r\n") for line in text.splitlines()]
    while lines and not lines[-1].strip():
        lines.pop()
    if not lines:
        raise ValueError("미로 내용이 비어 있습니다.")
    return Maze(tuple(lines))


def load_maze(path) -> Maze:
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise FileNotFoundError(f"미로 파일을 찾을 수 없습니다: {path}") from None
    except UnicodeDecodeError:
        raise ValueError(f"미로 파일을 UTF-8 로 읽을 수 없습니다: {path}") from None
    return parse_maze(text)


def save_maze(maze: Maze, path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(maze.as_text(), encoding="utf-8")
    return path
