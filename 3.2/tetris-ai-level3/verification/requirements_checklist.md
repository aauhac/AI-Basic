# 과제 요구사항 점검표 (PDF 3.2 인간-AI 대전 테트리스, 인쇄 5쪽 "제한요소 및 요구사항")

판정 기준: 담당 코드 확인 + 자동 테스트 통과 + 실제 GUI 실행(시연 영상 또는 GUI 테스트)로 확인.
검증일 2026-11-16 · 테스트 100개 모두 통과 (`verification/test_results.md`).

| # | PDF 요구사항 | 담당 코드 | 자동 검증 | 실제 실행 확인 | 판정 |
|---|---|---|---|---|---|
| 1 | 7종 테트로미노, 자동 낙하, 좌우 이동, 회전, 빠른 낙하, 충돌 판정 | `engine.BASE/CELLS/valid/try_rotate/Player.move/step/soft_drop/hard_drop`, `gui.loop`(중력) | `test_all_pieces_have_four_cells`, `test_wall_and_floor_collision`, `test_srs_rotation_kicks_near_wall`, O 회전 8개, `test_solo_keyboard_controls`, `test_das_auto_repeat_while_key_held` | 영상 ① | 충족 |
| 2 | 1인용·2인 동시·2인 대전·인간-AI 대전 + 모드별 진행·승패 판정 | `engine.Match`(모드별 플레이어 구성, `check_end`), `gui.start/check_end` | `test_win_rules_per_mode`, `test_two_players_independent_simultaneous_input`, `test_game_over_decides_winner_and_saves_records` | 영상 ①②③④ | 충족 |
| 3 | 줄 수·연속 제거에 따른 차등 점수, 줄 수에 따른 낙하 속도 증가 | `Player.lock`(LINE_SCORE, Combo, B2B), `Player.gravity_delay`(10줄마다 레벨 +1, 간격 ×0.83) | `test_line_clear_scores_one_to_four`, `test_combo_adds_score_and_attack`, `test_back_to_back_tetris_bonus`, `test_level_increases_gravity` | 화면의 SCORE/LEVEL/낙하 간격 | 충족 |
| 4 | 2인 대전·인간-AI 대전에서 여러 줄 제거 시 방해 블록 공격 | `Player.lock`(공격·상쇄·삽입), `Match.after_lock`(versus/ai만 전송) | `test_versus_and_ai_modes_route_attacks_both_ways`, `test_two_player_simultaneous_mode_sends_no_attack`, `test_simultaneous_attacks_partially_cancel`, 방해 줄 회귀 테스트 | 영상 ③, GUI `test_versus_attack_*` | 충족 (방해 줄 즉시 게임오버 버그 수정) |
| 5 | 현재+다음 블록 고려, 가능한 배치 탐색, 평가 점수 최대 위치 선택 | `ai.choose/_search/_best_future`(모든 회전×위치, 어려움은 다음 블록 2단계) | `test_optimised_search_equals_reference`, `test_hard_uses_next_piece_lookahead`, `test_plan_actions_reach_target_with_real_moves` | 영상 ④⑤ (AI 패널에 근거 표시) | 충족 |
| 6 | 최소 3단계 난이도, 난이도별 플레이 성능 차이 | `ai._search`(쉬움: 단순 평가, 보통: 7항목, 어려움: +다음 블록), `gui.AI_TIMING` | `test_difficulties_make_different_decisions`, `test_easy_plays_worse_than_normal_on_fixed_seed` | 벤치마크: 1인 500블록 쉬움 5/5 Top-out·보통/어려움 0, 대전 보통 7:3 쉬움, 어려움 8:2 보통 | 충족 |
| 7 | 다음 블록 표시, Hold(보관·교체) | `Player.next`(5개 큐, 화면에 3개), `Player.swap_hold`(블록당 1회) | `test_hold_is_once_per_piece`, `test_solo_keyboard_controls`(C 키) | 영상 ① | 충족 |
| 8 | 시작·일시정지·재개·종료·재시작, 플레이어별 점수·상태 독립 관리 | `gui.start/toggle_pause/stop`, 키 R/P/Esc, 플레이어별 `Player` 객체·낙하 시계 | `test_pause_freezes_everything_and_resume_continues`, `test_restart_and_mode_change_ignore_stale_ai_results`, `test_stop_during_ai_computation`, `test_players_are_independent` | 영상 전체 | 충족 |
| 9 | 보드·다음 블록·보유 블록·점수·레벨·AI 난이도 GUI | `gui.draw_player/draw_side/draw_dynamic`(상태 표시줄·AI 플레이어 이름에 난이도) | `test_layout_fits_after_resize`, `test_records_window_and_reload` | `docs/screens/*.png` | 충족 |
| 10 | 인간·AI 독립 처리, 낙하·입력·AI 연산 비간섭, 공유 데이터 동기화 | `ai.AIWorker`(보드 깊은 복사, `queue.Queue`, 세대 번호, 캐시 `threading.Lock`), `gui._apply_worker_results`(토큰 일치 시만 적용), Tk 위젯은 메인 스레드만 | `test_worker_skips_jobs_queued_before_invalidate`, `test_worker_never_mutates_caller_board`, `test_ai_mode_plays_in_background_without_blocking`, `test_redraw_does_not_rerun_ai_search` | GUI 응답성 측정(어려움 최대 정지 6,852 → 108 ms) | 충족 |
| 11 | 플레이어별 최고 점수·승패·제거 줄 수 파일 저장, 재실행 시 확인 | `storage.load_stats/save_stats/finish_match`(`save/records.json`, 원자적 저장, 손상 파일 복구), 시작 화면·오른쪽 패널·기록 창 표시 | `test_records_win_loss_lines_and_reload`, `test_aborted_and_solo_games_never_count_as_wins`, `test_partial_record_file_is_merged`, `test_corrupted_records_fallback` | 영상 ⑩ | 충족 |

## 확장 기능 (PDF: "개별적으로 추가 기능을 정의한다")

| 확장 | 검증 | 판정 |
|---|---|---|
| SRS 회전 + Wall Kick | `test_srs_rotation_kicks_near_wall`, 퍼즐 경로가 실제 킥을 사용(`test_tspin_route_uses_rotation_and_kicks`) | 동작 |
| T-Spin 판정(3코너 규칙, 마지막 동작=회전) + 공격 보너스 | `test_real_spin_path_is_t_spin`, `test_rotation_in_the_air_then_hard_drop_is_not_t_spin`, 영상 ⑦ | 동작 (T-Spin Mini 구분은 구현하지 않음 — 명시) |
| Combo / Back-to-Back / 공격 상쇄 | `test_combo_adds_score_and_attack`, `test_back_to_back_tetris_bonus`, `test_attack_tetris_sends_four_and_cancel_rules` | 동작 |
| 설명 가능한 AI 도우미(7개 항목 기여 점수, 실제 T-Spin 판정, 추천 위치) | `test_coach_preview_matches_evaluation_function`, `test_coach_panel_shows_real_evaluation_and_recommendation`, 영상 ⑥ | 동작 |
| AI T-Spin 퍼즐 생성·검증(BFS 키 경로, 준비 블록 필요성, 3단계 힌트) | `test_puzzles_extra.py` 15개, GUI 퍼즐 테스트 2개, 영상 ⑧⑨ | 동작 |

## 검증하지 못한 항목 (정직한 표기)

- macOS/Linux 실제 실행: 이번 검증은 Windows 11에서만 수행. Linux 실행 스크립트(`start_linux.sh`)는 제공하지만 실행 확인은 하지 않음.
- 실제 한글 IME 상태에서 사람이 직접 누르는 키 입력: 변환 로직만 테스트로 확인.
- DOCX/PPTX의 Microsoft Office 화면 렌더링: 작업 PC에 Office/LibreOffice가 없어 python-docx/python-pptx로 다시 열어 구조만 확인하고, 슬라이드는 같은 배치 데이터로 그린 미리보기 이미지로 확인함.
- 사람이 직접 장시간(수십 분) 플레이한 안정성: AI 자동 플레이 최대 500블록과 대전 시뮬레이션으로 대신함.
