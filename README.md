# MAZE-13

TXT 파일에 정의된 2D 미로 하나를 두 가지 방식으로 플레이하는 미로 탈출 게임입니다.

- **CLASSIC 2D** — 과제 기본 모드. 위에서 내려다보는 격자 화면.
- **3D HORROR** — 확장 모드. 직접 구현한 DDA Raycasting으로 같은 미로를 1인칭 3D로 보여주고,
  시각과 기억으로만 플레이어를 쫓는 Creature가 등장합니다.

두 모드는 같은 `Game` 규칙(이동·Key·Door·Trap·시간·기록)을 공유합니다.
논리 세계는 끝까지 2D 격자이고, 3D는 그 격자를 화면에 비추기만 합니다.

## 실행 환경

- Python 3.13
- pygame 2.6.1 (유일한 외부 의존성)
- Tkinter (CPython 표준 배포에 포함)
- 그 외 Python 표준 라이브러리

## 설치

```
python -m pip install -r requirements.txt
```

## 실행

```
python app.py
```

개발 / 분석용:

```
python app.py --info maps/maze01.txt      검증 결과 + BFS/DFS/A* 요약
python app.py --bench 300                 렌더링 프레임 시간 측정
python experiments.py                     보고서용 실험 전체 (results/ 에 저장)
python -m unittest discover -s tests -v   테스트
```

모든 명령은 `maze13/` 폴더 안에서 실행합니다.

## 게임 모드

### CLASSIC 2D

과제 기본 모드입니다. Creature는 없습니다.

| 조작 | 동작 |
|---|---|
| W / A / S / D | 위 / 왼쪽 / 아래 / 오른쪽 (화면 기준 절대 방향) |
| 방향키 | 위와 동일 |

- 현재 위치를 **P**로 표시하고, 지나온 경로를 함께 그립니다.
- `SHOW BFS / DFS / ASTAR` — 계산된 경로를 화면에 표시만 합니다.
- `AUTO SOLVE BFS / DFS / ASTAR` — 계산된 경로를 따라 실제로 한 칸씩 이동합니다.
  이때도 모든 이동은 사람이 조작할 때와 똑같이 `Game.move()`를 통과하므로
  Key·Door·Trap·이동 횟수가 동일하게 적용됩니다.
- Key / Door / Trap, Time Attack, Save / Continue 지원.

### 3D HORROR

| 조작 | 동작 |
|---|---|
| W / S | 보고 있는 방향으로 전진 / 후진 |
| A / D 또는 ← / → | 제자리에서 좌 / 우 90도 회전 |
| TAB | 지나온 영역 지도 |
| F3 | Creature AI + 안전 경로 디버그 표시 |
| F5 | 저장 |
| ESC | 메인 메뉴로 |

1인칭이라 W가 "북쪽"이 아니라 "앞"입니다. 이 변환은 렌더러 입력 계층에서만 일어나고,
`Game.move()`에는 언제나 절대 방향이 전달됩니다.

**이동과 시점을 분리했습니다.** W/S만 실제로 움직이고, A/D는 제자리에서 90도 돌기만 합니다.
통로가 1칸 폭이라 옆으로 가는 입력은 대부분 벽에 막혀 아무 일도 하지 않았기 때문입니다.
회전으로 두면 벽 앞에서도 항상 반응하고, 키 하나가 언제나 한 가지 일만 합니다.
회전은 게임 규칙을 거치지 않으므로 **이동 횟수에 반영되지 않습니다.**
논리 방향은 즉시 90도 바뀌고 화면만 약 0.2초에 걸쳐 부드럽게 따라 돕니다.

맵에 `G`가 있으면 Creature가 배치되고, **플레이어가 Key를 획득하는 순간 깨어납니다.**
그 전까지는 움직이지도, 화면에 보이지도 않습니다.

## Creature AI

```
Player 위치
   │   (perception 만 접근 가능)
   ▼
Visual Perception ──▶ Observation(visible, position)
                              │
                              ▼
                           Memory  (마지막 관측 위치 + 남은 기억 시간)
                              │
                              ▼
                            FSM
                              │
                              ▼
                      A* Navigation
```

`Creature.update(observation, maze, opened_doors, seconds)` — **Player 객체도 Player 좌표도
인자로 받지 않습니다.** 받는 것은 "지금 보이는가 / 보인다면 어디인가" 하나뿐이라,
실제 위치를 몰래 참조하는 추적이 구조적으로 불가능합니다. 이 점은 테스트로 고정돼 있습니다.

시야 판정은 **거리(7칸) → 시야각(90°) → 시선(LOS)** 순서로, 셋을 모두 통과해야 보입니다.
LOS는 3D 벽 렌더링과 같은 DDA 함수를 재사용하므로 화면에 보이는 것과 판정이 일치합니다.
닫힌 문은 시선을 막고, 플레이어가 연 문은 통과시킵니다.

FSM 상태 4개:

| 상태 | 의미 |
|---|---|
| `DORMANT` | Key 획득 전. 움직이지도 보이지도 않음 |
| `PATROL` | 플레이어를 모름. 멀리 떨어진 칸 하나를 골라 배회 |
| `CHASE` | 지금 보임. 관측 위치로 A* 추적 |
| `SEARCH` | 방금 놓침. 마지막 관측 위치로 간 뒤 주변을 둘러봄 |

기억이 만료되거나 탐색에 실패하면 `PATROL`로 돌아갑니다.
순찰 목적지는 평범한 통로 칸만 고릅니다 — 이유 없이 출구를 지키러 가지는 않습니다.
다만 플레이어를 보고 쫓는 중이라면 출구까지 따라갑니다.

Creature는 **붉은 후광에 감싸인 뒤엉킨 형체**로 보입니다. 몸은 거의 검어서 어둠에 묻히고
후광과 핏줄, 붉은 눈으로 식별합니다. 눈은 **Creature가 나를 보고 있을 때만** 켜집니다.

벽 뒤나 등 뒤처럼 보이지 않는 곳에 있을 때는 **화면 가장자리가 붉게 맥동**합니다
(보행 거리 6칸 이내, 가까울수록 진하게). 위치는 알려 주지 않고 "근처에 있다"만 알려 주므로
숨바꼭질은 그대로 유지됩니다.

Creature와 플레이어가 같은 칸이 되면 `ENTITY CONTACT` — 게임 오버입니다.
**출구 칸이라도 접촉이 먼저입니다.** 몬스터를 뚫고 탈출할 수는 없습니다.

## Adaptive Escape Route

Trap과 Creature를 "지나가고 싶지 않은 칸"으로 보고, 현재 목표(아직 열지 않은 Door,
열었다면 Exit)까지 안전한 길이 남아 있는지 검사합니다. 외길이 막혔을 때만
**내부 벽을 최소 개수(최대 2개)만 열어** 우회로를 만들고 `EMERGENCY ROUTE OPENED`를
표시합니다. 이미 안전하면 아무 일도 하지 않습니다.

- 검사 시점은 플레이어가 실제로 이동했을 때와 Creature가 칸을 옮겼을 때뿐입니다(매 프레임 아님).
- 외곽 벽은 절대 열지 않고, Door를 우회하게 만드는 벽도 후보에서 제외합니다.
- 열린 벽은 `opened_walls`에만 기록되고 **원본 TXT는 바뀌지 않습니다.**
  이동·Creature 경로·Raycasting·시야가 모두 같은 집합을 봅니다.

생성 단계에서도 같은 원리로, 모든 Trap을 피해 클리어할 수 있는 경로가 없으면
내부 벽을 최소 개수만 통로로 바꿔 미로를 만듭니다. 그래서 함정은 강제 통행료가 아니라
"질러갈지 돌아갈지"의 선택이 됩니다.

## TXT Map Format

| 기호 | 의미 |
|---|---|
| `#` | 벽 |
| `.` | 이동 가능한 통로 |
| `S` | 시작 지점 (정확히 1개) |
| `E` | 출구 (정확히 1개) |
| `K` | 열쇠 |
| `D` | 잠긴 문 (열쇠가 있어야 통과) |
| `T` | 함정 (밟을 때마다 이동 횟수 +5) |
| `G` | Creature 생성 위치 (0개 또는 1개) |

`P`는 화면에 현재 위치를 표시하기 위한 runtime 기호이며 **TXT 파일에 저장하지 않습니다.**

검증 규칙: 10×10 이상, 모든 행 길이 동일, 허용 문자만 사용, 외곽은 전부 벽,
그리고 **벽이 아닌 모든 칸이 실제 게임 규칙상 시작점에서 도달 가능**해야 합니다.
마지막 항목은 단순 연결성이 아니라 `(row, col, has_key)` 상태공간 탐색으로 검사하므로,
"열쇠를 먹은 뒤에 열리는 영역"은 정상으로 보고 영영 닿을 수 없는 영역만 걸러냅니다.

## 폴더 구조

```
maze13/
├─ app.py               진입점 (GUI / --info / --bench)
├─ experiments.py       보고서용 측정 스크립트
├─ maze/
│  ├─ model.py          불변 2D 격자와 타일 규칙
│  ├─ loader.py         TXT ↔ Maze
│  ├─ validator.py      형식 + 클리어 가능성 + 전체 연결성 검사
│  └─ generator.py      Randomized DFS + Braiding + 특수 타일 배치
├─ game/
│  ├─ engine.py         게임 규칙 전부 (이동/Key/Door/Trap/시간/잡힘)
│  ├─ player.py         플레이어 상태
│  ├─ records.py        최고기록 + 플레이 history (JSON)
│  └─ save_manager.py   저장 / 이어하기
├─ ai/
│  ├─ pathfinding.py    BFS / DFS / A* (+ Creature 용 격자 탐색)
│  ├─ route_guard.py    Adaptive Escape Route (Trap 보정 / 동적 벽 개방)
│  ├─ perception.py     Creature 시각 — Player 위치를 아는 유일한 곳
│  └─ creature.py       Memory + FSM
├─ renderer/
│  ├─ raycaster.py      DDA Raycasting (pygame 비의존 순수 계산)
│  ├─ sprites.py        코드로 그리는 투명 배경 스프라이트
│  └─ game_view.py      3D 화면 / 입력 / HUD
├─ ui/
│  ├─ main_window.py    메인 메뉴 / 맵 선택 / 랜덤 생성 / CLASSIC 2D
│  ├─ editor.py         미로 편집기
│  └─ preview.py        2D 캔버스 그리기
├─ maps/                기본 미로 3개
├─ tests/               unittest
├─ data/                records.json (실행 시 생성)
├─ saves/               저장 파일 (실행 시 생성)
└─ results/             experiments.py 출력
```

## 테스트

```
python -m unittest discover -s tests -v
Ran 319 tests — OK
```

pygame 창이나 Tkinter 위젯을 억지로 테스트하지 않습니다. 대신 레이 계산, 입력 변환,
스프라이트 투영, 기록 표 생성처럼 화면과 분리 가능한 부분을 순수 함수로 두고 검증합니다.

## 주의

- Creature는 **1마리**만 지원합니다. Validator가 `G`를 0개 또는 1개로 제한합니다.
- 3D HORROR의 Creature는 **Key를 획득해야** 활성화됩니다. 그전에는 아무 일도 일어나지 않습니다.
- 랜덤 생성은 11×11(최소 크기)에서 Trap 우회로를 만들지 못해 거부되는 경우가 있습니다
  (측정 약 11%). 21×15 이상에서는 거의 발생하지 않습니다. 실패하면 이유를 알려 주므로
  seed를 바꾸거나 크기를 키우면 됩니다.
- 랜덤 생성의 `loop_ratio`는 **0.0 ~ 0.10**을 권장합니다. 그보다 크면 우회로가 많아져
  통로를 실제로 막는 Door 자리를 찾지 못하고 생성이 거부될 수 있습니다
  (장식용 Door를 만들지 않기 위한 의도된 동작이며, 이유를 메시지로 알려 줍니다).
