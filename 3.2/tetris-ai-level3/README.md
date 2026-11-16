# AI 기초프로젝트 레벨 3 — 인간·AI 대전 테트리스 (최종본)

과제 3.2 "인간-AI 대전 테트리스" 구현입니다. **Python 3 + Tkinter(표준 라이브러리)만으로 실행**되며
Pygame, 이미지 파일, 학습된 모델, 네트워크가 필요 없습니다.

## 실행

```bash
python run.py              # Windows: start_windows.bat 더블클릭 / Linux: sh start_linux.sh
```

- Python 3.10 이상(검증: 3.12.4, Windows 11). Linux는 `python3-tk` 패키지가 필요할 수 있습니다.
- 기록은 첫 게임 이후 `save/records.json`에 자동 저장되고, 다시 실행하면 시작 화면과 [☰ 기록] 창에 표시됩니다.

## 게임 모드

| 모드 | 내용 | 승패 |
|---|---|---|
| 1인용 | 혼자 점수·줄 제거 기록 | GAME OVER 시 최고 점수·줄 수 저장 |
| 2인 동시 플레이 | 각자 보드에서 독립 플레이, 공격 없음 | 두 사람 모두 끝나면 점수 비교 |
| 2인 대전 | 줄을 지우면 상대에게 방해 줄 공격 | 먼저 블록이 넘친 쪽이 패배 |
| 인간 vs AI | 탐색형 AI와 대전(공격 포함), 난이도 3단계 | 먼저 블록이 넘친 쪽이 패배 |
| AI T-Spin 퍼즐 | AI가 생성하고 실제 키 경로로 검증한 퍼즐(쉬움 1·보통 2·어려움 3블록) | 목표 T-Spin 성공/실패 |

## 조작

| 기능 | 플레이어 1 | 플레이어 2 |
|---|---|---|
| 좌/우 이동 (길게 누르면 자동 반복) | ← / → | A / D |
| 시계 방향 회전 | ↑ 또는 X | W |
| 반시계 방향 회전 | Z | E |
| 빠르게 내리기 | ↓ | S |
| 즉시 낙하 | Space | F |
| Hold | C | Q |
| 일시정지/재개 · 재시작 · 종료 | P · R · Esc | (공통) |
| 퍼즐 힌트(3단계) | H | — |

두 사람이 동시에 키를 누르고 있어도 각자 자동 반복됩니다(DAS 170 ms / ARR 50 ms). 한글 입력기가 켜져 있어도 P2 키가 동작합니다(Windows).
퍼즐 모드에서는 바닥에 닿아도 자동 고정되지 않으므로 회전으로 끼워 넣은 뒤 Space로 고정합니다.

## AI (머신러닝이 아닌 탐색 + 직접 설계한 평가함수)

| 난이도 | 결정 방식 |
|---|---|
| 쉬움 | 현재 블록의 모든 회전·위치를 줄 제거 + 최대 높이 + 0.35×구멍 변화만으로 평가 |
| 보통 | 현재 블록의 모든 회전·위치를 7개 항목(줄 제거, T-Spin, 최대 높이, 구멍, 평탄도, 전체 높이, T-Spin 후보)으로 평가 |
| 어려움 | 보통 + 각 후보 뒤에 **다음 블록의 최선 배치 점수 × 0.65**를 더하는 2단계 탐색 |

- AI는 작업 스레드(`ai.AIWorker`)에서 계산하고, 결과에는 (게임 번호, 플레이어, 블록 번호) 토큰이 붙어 재시작·모드 변경 뒤의 오래된 결과는 버려집니다.
- AI는 선택한 위치까지 실제 회전·이동 키 동작을 한 단계씩 수행한 뒤 Hard Drop합니다(순간 이동 없음).
- 측정(같은 보드 100개): 어려움 탐색 평균 859 ms → 49.5 ms, 결과는 원본과 300/300 동일. 자세한 수치: `verification/performance_results.md`.

## 확장 기능

1. **SRS 회전 + Wall Kick**, O 블록은 회전해도 칸이 변하지 않음.
2. **T-Spin**: T 블록 + 마지막 동작이 회전 + 중심 4모서리 중 3곳 이상 막힘. 공중에서 돌린 뒤 떨어뜨리면 인정하지 않음. T-Spin Mini는 구분하지 않습니다.
3. **Combo / Back-to-Back / 공격 상쇄**: 보낼 공격으로 받을 방해 줄을 먼저 상쇄하고 남은 줄을 보냅니다.
4. **설명 가능한 AI 도우미**: 현재 위치의 평가 점수와 7개 항목별 기여, 실제 T-Spin 판정, AI 추천 위치(청록 점선)를 실시간 표시. 게임 점수와는 별개입니다.
5. **AI T-Spin 퍼즐**: 완성된 T-Spin Double 구조에서 지붕(I)·빈칸(O)을 제거해 출제하고, 모든 블록의 실제 키 입력 경로(BFS, SRS 킥 포함)와 "준비 블록이 꼭 필요함"을 검증한 문제만 냅니다.

## 테스트

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q          # 2026-11-16: 100 passed (원본 23 + 신규 77)
```

GUI 테스트(16개)는 실제 Tk 창을 띄웁니다. 모니터가 없는 환경에서는 자동으로 건너뜁니다.

## 폴더 구조

```
run.py · start_windows.bat · start_linux.sh   실행
tetris/engine.py     블록·SRS·충돌·점수·공격(8단계 고정 순서)·Player·Match(모드별 승패)
tetris/ai.py         배치 탐색·평가함수·결과 캐시·AIWorker(작업 스레드)
tetris/puzzles.py    BFS 키 경로 탐색·퍼즐 생성/검증·PuzzleSession·힌트
tetris/gui.py        Tkinter 화면, 키 입력(DAS), AI 결과 적용, 그리기
tetris/storage.py    records.json 저장/불러오기(원자적 저장, 손상 파일 복구)
tests/               자동 테스트 100개 (GUI 통합 16개 포함)
verification/        요구사항 점검표·테스트 결과·성능 결과·버그 수정 요약 + 측정 스크립트와 원자료(JSON)
docs/                화면 캡처·그림·보고서/발표자료 생성 스크립트
docs/real_demo/       실제 플레이 영상 녹화(OS 입력)·편집 스크립트, 입력 로그, 영상 검증 문서
tools/wincapture.py  시연 녹화용 창 캡처(Windows, 프로그램 창만 캡처)
```

## 시연 영상

- `테트리스_레벨3_실제플레이_시연영상.mp4` (3분 39초, 1920×1080, H.264). `python run.py`로 실행한 실제 프로그램을 Windows SendInput(OS 키보드·마우스 입력)만으로 조작하며 게임 창만 녹화한 **자동화된 GUI 입력 시연**입니다. 게임 내부 상태는 변경하지 않았습니다. 장면별 캡처: `docs/screens_real/`, 검증: `docs/real_demo/영상_검증.md`.

## 문서·영상 다시 만들기 (선택)

```bash
python -m pip install -r docs/requirements-docs.txt
python docs/real_demo/record_real_demo.py <원본폴더>   # 제출 영상 녹화: 실제 run.py + OS 키·마우스 입력 (Windows, 약 4분간 PC 사용 금지)
python docs/real_demo/compose_video.py <원본폴더> 테트리스_레벨3_실제플레이_시연영상.mp4 docs/real_demo/caption_fixes.json
python verification/make_reports.py       # 성능·테스트 결과 문서와 그래프
python docs/make_submission_docs.py       # 보고서(docx) + 발표자료(pptx)
```

## 알려진 한계

- AI는 위에서 곧바로 떨어뜨리는 배치만 후보로 삼습니다(블록 밑으로 밀어 넣기·T-Spin을 노리는 전략은 없음). T-Spin 경로 탐색은 퍼즐 검증기에서만 사용합니다.
- 도우미의 "T-Spin 후보"는 보드 모양으로 계산한 근사값이며, 실제 T-Spin 여부는 회전·모서리 조건으로 따로 판정합니다.
- 네트워크 대전은 없습니다. 검증은 Windows 11에서만 했습니다.
