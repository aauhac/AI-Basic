"""runtime 상태 저장 / 이어하기.

원본 map TXT 는 저장하지 않고 파일명만 기록한다. 이어하기는 그 TXT 를 다시 읽으므로
원본은 어떤 경우에도 수정되지 않는다. Creature 상태는 다음 Phase 에서 추가한다.
"""

import json
from pathlib import Path

from ai.creature import Creature
from game.engine import CLASSIC, Game
from maze.loader import load_maze

DEFAULT_DIR = Path("saves")
MAPS_DIR = Path("maps")


def save_game(game: Game, path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    state = {
        "map": Path(game.map_name).name,
        "position": list(game.player.position),
        "has_key": game.player.has_key,
        "move_count": game.player.move_count,
        "opened_doors": [list(pos) for pos in sorted(game.opened_doors)],
        "opened_walls": [list(pos) for pos in sorted(game.opened_walls)],
        "visited_path": [list(pos) for pos in game.visited_path],
        "elapsed": round(game.elapsed, 3),
        "mode": game.mode,            # 시간 제한 모드 (예전 파일과 같은 이름)
        "timer_mode": game.mode,
        "play_mode": game.play_mode,  # classic / horror
        "time_limit": game.time_limit,
        "cleared": game.cleared,
        "caught": game.caught,
        "creature": _creature_state(game.creature),
    }
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    return path


def load_game(path, maps_dir=MAPS_DIR) -> Game:
    state = json.loads(Path(path).read_text(encoding="utf-8"))
    map_path = Path(maps_dir) / state["map"]
    game = Game(load_maze(map_path), time_limit=state.get("time_limit"),
                elapsed=state.get("elapsed", 0.0), map_name=state["map"],
                play_mode=state.get("play_mode", CLASSIC))
    game.player.position = tuple(state["position"])
    game.player.has_key = state["has_key"]
    game.player.move_count = state["move_count"]
    game.opened_doors = {tuple(pos) for pos in state["opened_doors"]}
    # 예전 저장 파일에는 없는 필드다. 없으면 빈 집합으로 시작한다.
    game.opened_walls = {tuple(pos) for pos in state.get("opened_walls", [])}
    game.visited_path = [tuple(pos) for pos in state["visited_path"]]
    game.cleared = state.get("cleared", False)
    game.caught = state.get("caught", False)
    game.creature = _restore_creature(state.get("creature"))
    return game


def _creature_state(creature) -> dict | None:
    """current_path 는 저장하지 않는다. 불러온 뒤 A* 가 바로 다시 만든다."""
    if creature is None:
        return None
    return {
        "position": list(creature.position),
        "facing": creature.facing,
        "state": creature.state,
        "active": creature.active,
        "last_seen_position": (list(creature.last_seen_position)
                               if creature.last_seen_position else None),
        "memory_remaining": round(creature.memory_remaining, 3),
        "target": list(creature.target) if creature.target else None,
        "searches_left": creature.searches_left,
        "move_timer": round(creature.move_timer, 3),
    }


def _restore_creature(state) -> Creature | None:
    """Creature 필드가 없는 예전 저장 파일도 그대로 읽힌다 (None 이면 Creature 없음)."""
    if not state:
        return None
    last_seen = state.get("last_seen_position")
    target = state.get("target")
    return Creature(
        position=tuple(state["position"]),
        facing=state.get("facing", "s"),
        state=state.get("state", "dormant"),
        active=state.get("active", False),
        last_seen_position=tuple(last_seen) if last_seen else None,
        memory_remaining=state.get("memory_remaining", 0.0),
        target=tuple(target) if target else None,
        searches_left=state.get("searches_left", 0),
        move_timer=state.get("move_timer", 0.0),
    )


def next_numbered_path(directory, prefix: str, suffix: str) -> Path:
    """<prefix>_001.<suffix> 처럼 비어 있는 다음 번호의 경로. 저장 파일과 생성 미로가 같이 쓴다."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    number = 1
    while (path := directory / f"{prefix}_{number:03d}{suffix}").exists():
        number += 1
    return path


def next_save_path(directory=DEFAULT_DIR) -> Path:
    return next_numbered_path(directory, "save", ".json")


def latest_save(directory=DEFAULT_DIR) -> Path | None:
    saves = sorted(Path(directory).glob("*.json"), key=lambda p: p.stat().st_mtime)
    return saves[-1] if saves else None
