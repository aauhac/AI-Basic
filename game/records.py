"""미로별 최고 기록. JSON 파일 하나, 외부 dependency 없음.

moves 와 time 은 서로 독립적인 최고 기록이다 (최단 이동과 최단 시간이 다른 플레이일 수 있다).
"""

import json
from pathlib import Path

DEFAULT_PATH = Path("data/records.json")
HISTORY_LIMIT = 50   # 파일이 무한히 커지지 않게 최근 것만 남긴다


def load(path=DEFAULT_PATH) -> dict:
    """기록을 읽는다. 파일이 없거나 깨져 있으면 빈 기록으로 시작한다."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, UnicodeDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def save(records: dict, path=DEFAULT_PATH) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def update(map_name: str, moves: int, seconds: float, path=DEFAULT_PATH,
           mode: str = "classic") -> dict:
    """클리어한 게임의 기록을 반영하고 해당 미로의 기록을 돌려준다.

    best_moves / best_time 은 서로 독립이고, 모든 클리어는 history 에도 남는다.
    history 가 없던 예전 기록 파일도 그대로 읽어서 이어 쓴다.
    """
    records = load(path)
    entry = records.setdefault(str(map_name), {})
    entry["best_moves"] = _better(entry.get("best_moves"), moves)
    entry["best_time"] = _better(entry.get("best_time"), round(seconds, 2))

    history = entry.get("history")
    if not isinstance(history, list):
        history = []
    history.append({"moves": moves, "time": round(seconds, 2), "mode": mode})
    entry["history"] = history[-HISTORY_LIMIT:]
    save(records, path)
    return entry


def history_of(entry) -> list[dict]:
    """history 가 없는 예전 기록에서도 안전하게 목록을 꺼낸다."""
    history = (entry or {}).get("history")
    return history if isinstance(history, list) else []


def _better(old, new):
    return new if old is None or new < old else old
