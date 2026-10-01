# MAZE-13 시연 순서

3~5분 분량. 촬영 전에 `data/records.json`과 `saves/*.json`을 지우면 처음부터 보여 줄 수 있습니다.

```
python app.py
```

---

## 1. 메인 메뉴 (약 15초)

`PLAY / RANDOM MAZE / MAP EDITOR / CONTINUE / RECORDS / EXIT` 여섯 항목을 보여 줍니다.

---

## 2. CLASSIC 2D — 과제 기본 모드 (약 60초)

`PLAY` → 목록에서 `maze01.txt` 선택.

오른쪽 패널에 타일 구성, `VALIDATION: PASS`, BFS/DFS/A*의 moves·visited가 표시됩니다.

1. `CLASSIC 2D` 클릭.
2. **W / A / S / D**로 몇 칸 이동 — 현재 위치가 **P**로, 지나온 칸이 파란 사각형으로 표시됩니다.
   화면 상단 안내에 `W = UP  A = LEFT  S = DOWN  D = RIGHT`가 적혀 있습니다.
3. `SHOW BFS` 클릭 — 최단 경로가 표시됩니다. **P는 움직이지 않습니다** (시각화 전용).
4. `CLEAR` 후 `AUTO SOLVE BFS` 클릭 — P가 경로를 따라 한 칸씩 자동 이동합니다.
   중간에 열쇠를 줍고(`KEY 1`), 함정을 밟아 이동 횟수가 +5 되고, 문을 통과해 출구에 도달합니다.
5. 클리어 팝업에 `MOVES / TIME / BEST MOVES / BEST TIME / PLAYS`가 나옵니다.

> 여기까지가 과제 기본 요구사항입니다.

---

## 3. RANDOM MAZE (약 30초)

`RANDOM MAZE` → `width 21`, `height 15`, `loop ratio 0.10`, `special tiles` 체크 → `GENERATE`.

- 생성된 미로가 `maps/random_00N.txt`로 **저장**됩니다.
- 메모리의 미로를 그대로 쓰지 않고 **방금 저장한 파일을 다시 읽어 검증**한 결과를 보여 줍니다.
- "생성한 미로를 플레이하시겠습니까?"에서 `아니오`를 눌러 다음 단계로 넘어갑니다.

---

## 4. MAP EDITOR (약 45초)

`MAP EDITOR`.

1. 팔레트에서 `S`, `E`를 찍고, 통로를 조금 그립니다.
2. **일부러 벽으로 둘러싸인 방을 하나 만듭니다.**
3. `VALIDATE` — 실패 메시지가 나옵니다.
   ```
   VALIDATION: FAIL
     - Start에서 접근할 수 없는 이동 가능 공간이 N칸 존재합니다.
     - 예시 위치: (5, 1), (5, 2), ...
   ```
   해당 칸들이 캔버스에 **붉은 테두리**로 표시됩니다.
4. 벽 한 칸을 지워 통로를 이어 줍니다 → `VALIDATE` → `PASS`.
5. `SAVE TXT`로 저장 → "지금 플레이하시겠습니까?"

---

## 5. 3D HORROR (약 90초)

`PLAY` → `maze01.txt` → `3D HORROR`.

1. **W/S**로 전진·후진 — 뒤로 물러날 때 **시선이 그대로인 것**을 보여 줍니다.
2. **A/D**로 제자리 90도 회전 — 벽을 보고 있어도 돌아갑니다. 화면이 부드럽게 돌고
   **이동 횟수는 올라가지 않습니다.** 갈림길에서 A → W 로 옆길에 들어갑니다.
3. **TAB** — 지나온 영역만 표시되는 지도. 전체 정답 지도가 아닙니다.
4. 복도 끝의 **열쇠 스프라이트**를 찾아가서 획득 → HUD가 `KEY 1`로 바뀌고 열쇠가 사라집니다.
   **이 순간 Creature가 깨어납니다.**
5. **F3** — Creature 디버그 표시를 켭니다.
   ```
   STATE     patrol
   ACTIVE    True
   POSITION  (3, 9)   FACING w
   VISION    lost   obs=None
   LAST SEEN None   memory 0.0s
   TARGET    (9, 6)   path 7
   ```
6. Creature가 보이지 않아도 가까워지면 **화면 가장자리가 붉게** 물듭니다(사각지대 경고).
   모퉁이를 돌면 **붉은 후광에 감싸인 형체**가 나타나고, 나를 포착하면 **눈이 켜집니다**.
7. Creature를 마주칩니다 → `STATE chase`, `VISION VISIBLE`, `LAST SEEN`이 갱신됩니다.
7. **코너를 돌아 시야를 끊습니다** → `STATE search`, `VISION lost`,
   그런데 `LAST SEEN`은 남아 있고 Creature가 **그 위치로 찾아옵니다**.
   → 이것이 "실제 좌표를 모르고 기억으로 쫓는다"는 것을 보여 주는 핵심 장면입니다.
8. 다시 마주치면 `chase`로 복귀합니다.
9. Creature가 외길을 막으면 `EMERGENCY ROUTE OPENED`가 뜨고 벽 한 칸이 열립니다.
   F3의 `SAFE ROUTE` / `OPENED WALLS` / `CURRENT GOAL` 줄로 확인할 수 있습니다.
10. 잡히면 **붉은** `ENTITY CONTACT / YOU WERE CAUGHT`,
    도망쳐 출구에 도달하면 **녹색** `MAZE CLEARED`. 출구 칸에 Creature가 있으면
    들어가도 탈출이 아니라 접촉입니다.
11. **ESC**로 메인 메뉴 복귀.

> 함정에 올라서면 `TRAP - +5 MOVES`, 열쇠 없이 문에 닿으면 `LOCKED - KEY REQUIRED`가
> 화면 중앙에 뜹니다. 시간이 남으면 같이 보여 주면 좋습니다.

---

## 6. RECORDS (약 20초)

`RECORDS` — 미로별 `BEST MOVES / BEST TIME / PLAYS`와 최근 플레이 목록.
`mode` 열에서 `classic`과 `horror` 기록이 구분됩니다.

---

## 보조 자료 (촬영 대신 화면 캡처로 대체 가능)

```
python app.py --info maps/maze03.txt   검증 + BFS/DFS/A* 비교
python experiments.py                  results/ 에 CSV 4개 + 시나리오 로그
python -m unittest discover -s tests   319 tests
```
