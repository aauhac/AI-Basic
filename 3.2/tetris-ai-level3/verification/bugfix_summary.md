# 버그 수정 요약

모든 "수정 전" 결과는 원본 프로젝트(`Tetris_AI_Level3_전체프로젝트.zip`)를 그대로 실행해서 얻었습니다.
재현 스크립트: `python verification/reproduce_bugs.py <프로젝트 폴더> <결과.json>`
(결과: `bugs_before.json` / `bugs_after.json`). 각 버그에는 회귀 테스트가 있습니다.

| # | 버그 | 원인 | 수정 위치 | 수정 전 (실측) | 수정 후 (실측) | 회귀 테스트 |
|---|---|---|---|---|---|---|
| 1 | O 블록 회전 시 위치 이동 및 프로그램 오류 | `cells()`가 O의 3×3 행렬도 회전시켜 회전할 때마다 정사각형이 한 칸씩 이동했고, `try_rotate()`는 O에 대해 충돌 검사를 하지 않았음 | `engine._rotated_cells`(O는 4개 회전 상태 모두 같은 칸), `engine.try_rotate`(O도 `valid` 검사, 실패 시 `None` → 기존 상태 유지) | 바닥에서 회전 후 Hard Drop → `ValueError: invalid lock` | 회전 전후 칸 동일, Hard Drop 정상 | `test_regressions.py`의 O 관련 8개 |
| 2 | 방해 줄을 받으면 즉시 게임오버 | `Player.lock()`이 블록을 보드에 고정한 뒤에도 그 블록을 `active`로 남겨 둔 채 `receive_garbage()`를 호출 → 이미 고정된 블록이 자기 자신과 겹친다고 판단 | `engine.Player.lock()`을 8단계 순서로 재작성(고정 → active 해제 → 줄 제거·점수 → Combo/B2B/T-Spin → 공격 계산 → 상쇄 → 방해 줄 삽입 → Top-out 확인 → 다음 블록 생성), `receive_garbage()`는 실제 Top-out(위 n줄에 블록 존재)만 판정 | 방해 줄 1줄 수신 → 게임오버 `True`, 2인 대전 TETRIS 공격 받은 쪽 → 게임오버 `True` | 둘 다 `False`, 정상 진행 | `test_receiving_*`, `test_garbage_pushes_locked_blocks_up`, `test_real_top_out_from_garbage`, `test_play_continues_after_garbage`, GUI `test_versus_attack_is_sent_received_and_game_continues` |
| 3 | 퍼즐 T-Spin 성공 시 T-Spin 횟수 미증가 | GUI의 `puzzle_lock()`이 점수·줄만 갱신하고 `spins`는 갱신하지 않음 | 퍼즐 규칙을 `puzzles.PuzzleSession.lock()`으로 이동(GUI 없이 테스트 가능), 성공/실패를 한 번만 확정, 이후 입력은 `None` 반환, 기록 저장은 `puzzle_recorded` 플래그로 1회만 | 성공 메시지는 나오지만 `spins = 0` | `spins = 1`, 기록 `puzzles_solved` 1회 증가 | `test_success_updates_spin_statistics_once`, `test_failure_when_dropping_t_without_spin_and_outcome_is_final`, GUI `test_puzzle_solved_by_keyboard_updates_stats_once` |
| 4 | 공중에서 회전 후 떨어뜨려도 T-Spin 인정 | `ghost()`가 `rotated_last`를 그대로 복사 → Hard Drop으로 여러 줄 떨어져도 "마지막 동작 = 회전"으로 남음 | `engine.drop()`: 1칸 이상 떨어지면 `rotated_last=False`; `Player.hard_drop`, `PuzzleSession.lock`, AI 도우미 미리보기에 적용 | 17줄 낙하 후에도 `counted_as_t_spin = True` | `False` (실제 회전 경로는 여전히 T-Spin) | `test_rotation_in_the_air_then_hard_drop_is_not_t_spin`, `test_real_spin_path_is_t_spin` |
| 5 | AI 계산 때문에 GUI 정지 | 화면을 그릴 때마다 `choose()`를 동기 호출(도우미 2회 + AI 패널 1회), AI 이동도 메인 루프에서 동기 탐색. 어려움 탐색 1회 평균 859 ms | `ai.py` 최적화(결과 동일) + `AIWorker` 작업 스레드 + 토큰으로 오래된 결과 폐기 + 다시 그리기는 저장된 결과만 사용 | 어려움: 24.2초 동안 루프 7회 실행, 최대 정지 6,852 ms, 키 지연 p95 2,221 ms | 루프 1,040회, 최대 정지 108 ms, 키 지연 p95 6.7 ms | `test_ai_mode_plays_in_background_without_blocking`, `test_redraw_does_not_rerun_ai_search`, `test_worker_*` |
| 6 | 퍼즐 보통·어려움의 준비 블록이 의미 없음 | 준비 블록(I, O)을 벽 쪽 아무 데나 놓아도 T-Spin 구조가 이미 완성돼 있었음 | 생성기 재설계: 완성 구조에서 지붕(I)·빈칸(O)을 제거한 보드를 출제, 준비 블록 없이는 목표 T-Spin이 불가능함을 BFS로 확인 | 첫 상태에서 바로 T-Spin 가능 | 보통·어려움 모두 초기 보드에서 목표 T-Spin 불가, 어려움은 I만/O만 놓아도 불가 | `test_preparation_pieces_are_necessary`, `test_every_piece_solved_by_its_recorded_key_route` |

## 함께 고친 안정성·사용성 문제

- **2인 동시 입력:** OS 자동 반복은 마지막으로 누른 키에만 적용되어 두 사람이 동시에 키를 누르고 있을 수 없었음 → 키별 누름 상태 + 자체 DAS(170 ms)/ARR(50 ms) 반복 구현.
- **한글 입력기:** 한글 IME가 켜져 있으면 P2 키(A/D/W…)가 한글 keysym으로 들어와 무시됨 → Windows 가상 키 코드로 보정.
- **버튼 포커스:** 버튼이 키보드 포커스를 가져가 Space가 버튼을 누르는 문제 방지(`takefocus=0`).
- **종료 후 입력:** 게임 종료·일시정지 상태에서는 모든 조작 무시(`playable()`), 일시정지 중 AI 결과는 보관만 하고 적용하지 않음.
- **창 크기:** 고정 좌표 → 캔버스 크기 기준 비율 배치. 900×620~1600×950 크기에서 잘림 없음(테스트).
- **기록:** 중단한 경기를 승패로 세지 않고 `aborted`로 따로 저장, 2인 이상 경기만 승패 기록, 모드·결과·시각을 기록 이력에 저장, 일부만 있는 이전 기록 파일 병합.
- **퍼즐 생성 실패:** 정해진 횟수(60회) 안에 실패하면 `PuzzleGenerationError`를 내고, GUI는 메시지만 표시(무한 반복·종료 없음).

## 실제 플레이 영상 녹화 중 발견·수정한 문제

실제 프로그램을 OS 입력으로 조작하며 녹화하는 과정에서 화면으로 확인한 문제입니다. 게임 규칙·엔진은 바꾸지 않았습니다.

- **2인 화면 제목 겹침:** 2인 모드에서 왼쪽 위 모드 제목("2인 동시 플레이")이 "P1 PLAYER" 글자와 겹침 → 2보드 배치의 시작 높이를 내림(`compute_layout`).
- **결과 안내 상자 넘침:** 상자 폭을 `글자 수 × 고정값`으로 계산해 한글 문구("퍼즐 성공! T-Spin 2줄 제거 · 블록 3개 사용")가 상자 밖으로 넘침 → 실제 그려진 글자 폭(`bbox`)으로 상자 크기 계산.
- **종료 후 도우미 문구:** Esc로 게임을 끝낸 뒤에도 "AI 추천 계산 중…"이 계속 표시됨 → 진행 중이 아니면 "AI 추천: 게임 진행 중에만 계산" 표시.
- **GUI 테스트 간헐적 비정상 종료:** 테스트처럼 한 프로세스에서 Tk를 여러 번 만들면, 이전 테스트의 Tk 객체가 AI 작업 스레드에서 가비지 컬렉션될 때 Tcl이 중단될 수 있었음(수정 전 7회 실행 중 2회) → GUI 테스트 fixture가 시작 시 메인 스레드에서 `gc.collect()`, 종료 시 AI 스레드 종료 대기. 테스트 내용은 바꾸지 않음. 수정 후 연속 8회 실행 모두 100개 통과. 실제 게임은 Tk를 한 번만 만들므로 해당되지 않음.

