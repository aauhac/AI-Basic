# 테스트 결과

실행 명령: `python -m pytest -v` · 실행일 2026-11-16 · Windows 11 Home · Intel Core i7-8700 3.2 GHz · RAM 32 GB · Python 3.12.4

**최종 결과: 100 passed in 45.97s** (실패 0, 건너뜀 0)

원본 프로젝트의 테스트 23개는 하나도 지우거나 바꾸지 않고 그대로 통과합니다. 새로 추가한 테스트는 77개입니다.

| 파일 | 개수 | 통과 | 내용 |
| --- | --- | --- | --- |
| `tests/test_ai_extra.py` | 14 | 14 | 신규: 참조 구현과 동일성, 난이도 차이, 캐시, 작업 스레드, 오래된 결과 폐기 |
| `tests/test_engine.py` | 18 | 18 | 기존 테스트(원본 23개 중 18개): 7-bag, 회전, 충돌, 줄 제거, 공격, Hold, AI, 퍼즐, 저장 |
| `tests/test_gui.py` | 16 | 16 | 신규: 실제 Tk 창 + 키 이벤트 통합 테스트 (2인 동시 입력, 공격, AI, 일시정지, 재시작, 퍼즐, 크기 변경) |
| `tests/test_integration.py` | 5 | 5 | 기존 통합 테스트(원본 5개): AI 40블록, 퍼즐 해답, 시드 공정성, 공격 상쇄, 키 경로 |
| `tests/test_puzzles_extra.py` | 15 | 15 | 신규: 모든 블록의 실제 키 경로, 준비 블록 필요성, 힌트, 성공/실패, 생성 실패 처리 |
| `tests/test_regressions.py` | 20 | 20 | 신규: O 회전·방해 줄·T-Spin 낙하 판정 버그의 회귀 테스트 |
| `tests/test_rules_match.py` | 12 | 12 | 신규: 1~4줄 점수, Combo/B2B, 레벨 속도, 모드별 공격 라우팅, 승패, 기록 |

## 실제 GUI 검증

- `tests/test_gui.py`의 16개 테스트는 실제 Tk 창을 띄우고 `event_generate`로 키 이벤트를 Tk 이벤트 큐에 넣어 앱의 실제 메인 루프를 실행합니다.
- 확인 항목: 1인용 조작, DAS 자동 반복, 2인 동시 키 누름, 2인 대전 공격 송수신 후 계속 진행, AI 백그라운드 플레이 중 이벤트 루프 정지 250 ms 미만, 다시 그리기 중 AI 재탐색 없음, 도우미 점수와 평가함수 일치, 일시정지 상태 고정, 재시작·모드 변경 시 오래된 AI 결과 무시, AI 계산 중 종료, 게임오버 승자 결정 및 기록 파일 저장, 키보드만으로 퍼즐 풀이 후 통계 1회 증가, 힌트 3단계와 실패 판정, 창 크기 변경 시 레이아웃, 기록 창.
- 모니터가 없는 환경에서는 `tkinter.Tk()` 생성이 실패하므로 GUI 테스트는 자동으로 건너뜁니다(이번 실행은 Windows 데스크톱에서 실제로 실행되어 건너뜀 0).
- 한글 입력기(IME) 상태의 P2 키: Tk는 IME 키를 합성할 수 없어, 키 이름 변환 함수와 실제 처리기를 가짜 이벤트로 검증했습니다. 실제 한글 IME 환경에서의 수동 확인은 하지 않았습니다.
- 시연 영상(`테트리스_레벨3_실제플레이_시연영상.mp4`, 3분 39초)은 `python run.py`로 실행한 실제 프로그램을 Windows SendInput(OS 키보드·마우스 입력)만으로 조작하며 게임 창만 녹화한 **자동화된 GUI 입력 시연**입니다. 게임 내부 상태는 변경하지 않았습니다(검증: `docs/real_demo/영상_검증.md`).

## 버그 재현 (원본 vs 수정본, 같은 시나리오)

`python verification/reproduce_bugs.py <프로젝트 폴더> <결과.json>` → `bugs_before.json`, `bugs_after.json`

| 시나리오 | 원본 | 수정본 |
| --- | --- | --- |
| o_rotation_on_floor | ValueError: invalid lock | 회전 전후 칸 동일=True, Hard Drop ok |
| receive_1_garbage_line | {"game_over_after_receiving_1_line": true} | {"game_over_after_receiving_1_line": false} |
| versus_tetris_attack | {"attack_sent": 4, "receiver_game_over": true} | {"attack_sent": 4, "receiver_game_over": false} |
| rotate_in_air_then_hard_drop | {"lines": 1, "counted_as_t_spin": true} | {"lines": 1, "counted_as_t_spin": false} |
| puzzle_success_spin_counter | {"success_message": true, "player_spins_counter": 0} | {"success_message": true, "player_spins_counter": 1} |

## 전체 테스트 목록

```
tests/test_ai_extra.py::test_optimised_search_equals_reference[easy] PASSED
tests/test_ai_extra.py::test_optimised_search_equals_reference[normal] PASSED
tests/test_ai_extra.py::test_optimised_search_equals_reference[hard] PASSED
tests/test_ai_extra.py::test_tslot_bitmask_equals_reference PASSED
tests/test_ai_extra.py::test_difficulties_make_different_decisions PASSED
tests/test_ai_extra.py::test_hard_uses_next_piece_lookahead PASSED
tests/test_ai_extra.py::test_easy_plays_worse_than_normal_on_fixed_seed PASSED
tests/test_ai_extra.py::test_all_difficulties_return_valid_placements_and_board_stays_consistent PASSED
tests/test_ai_extra.py::test_search_result_is_cached PASSED
tests/test_ai_extra.py::test_coach_preview_matches_evaluation_function PASSED
tests/test_ai_extra.py::test_plan_actions_reach_target_with_real_moves PASSED
tests/test_ai_extra.py::test_worker_returns_result_with_token PASSED
tests/test_ai_extra.py::test_worker_skips_jobs_queued_before_invalidate PASSED
tests/test_ai_extra.py::test_worker_never_mutates_caller_board PASSED
tests/test_engine.py::test_seven_pieces_are_bags PASSED
tests/test_engine.py::test_bag_seed_reproducible PASSED
tests/test_engine.py::test_all_pieces_have_four_cells PASSED
tests/test_engine.py::test_wall_and_floor_collision PASSED
tests/test_engine.py::test_ghost_is_landing PASSED
tests/test_engine.py::test_line_clear_exact PASSED
tests/test_engine.py::test_srs_rotation_kicks_near_wall PASSED
tests/test_engine.py::test_t_spin_requires_rotation_and_corner_occupancy PASSED
tests/test_engine.py::test_attack_tetris_four_lines PASSED
tests/test_engine.py::test_hold_is_once_per_piece PASSED
tests/test_engine.py::test_garbage_and_cancel PASSED
tests/test_engine.py::test_ai_valid_placements PASSED
tests/test_engine.py::test_ai_evaluation_parts PASSED
tests/test_engine.py::test_puzzle_generation_and_validation PASSED
tests/test_engine.py::test_puzzle_solution_reproducible PASSED
tests/test_engine.py::test_save_load_json PASSED
tests/test_engine.py::test_corrupted_records_fallback PASSED
tests/test_engine.py::test_garbage_topout PASSED
tests/test_gui.py::test_solo_keyboard_controls PASSED
tests/test_gui.py::test_das_auto_repeat_while_key_held PASSED
tests/test_gui.py::test_two_players_independent_simultaneous_input PASSED
tests/test_gui.py::test_p2_keys_work_with_korean_ime PASSED
tests/test_gui.py::test_versus_attack_is_sent_received_and_game_continues PASSED
tests/test_gui.py::test_ai_mode_plays_in_background_without_blocking PASSED
tests/test_gui.py::test_redraw_does_not_rerun_ai_search PASSED
tests/test_gui.py::test_coach_panel_shows_real_evaluation_and_recommendation PASSED
tests/test_gui.py::test_pause_freezes_everything_and_resume_continues PASSED
tests/test_gui.py::test_restart_and_mode_change_ignore_stale_ai_results PASSED
tests/test_gui.py::test_stop_during_ai_computation PASSED
tests/test_gui.py::test_game_over_decides_winner_and_saves_records PASSED
tests/test_gui.py::test_puzzle_solved_by_keyboard_updates_stats_once PASSED
tests/test_gui.py::test_puzzle_hint_levels_and_failure PASSED
tests/test_gui.py::test_layout_fits_after_resize PASSED
tests/test_gui.py::test_records_window_and_reload PASSED
tests/test_integration.py::test_ai_plays_forty_pieces_without_crash PASSED
tests/test_integration.py::test_puzzle_witness_reaches_correct_tspin PASSED
tests/test_integration.py::test_two_player_same_seed_same_piece_sequence PASSED
tests/test_integration.py::test_attack_cancel_incoming PASSED
tests/test_integration.py::test_puzzle_keyboard_path_is_real_and_wins PASSED
tests/test_puzzles_extra.py::test_generated_puzzles_valid_and_deterministic[easy-seq0] PASSED
tests/test_puzzles_extra.py::test_generated_puzzles_valid_and_deterministic[normal-seq1] PASSED
tests/test_puzzles_extra.py::test_generated_puzzles_valid_and_deterministic[hard-seq2] PASSED
tests/test_puzzles_extra.py::test_every_piece_solved_by_its_recorded_key_route[easy-seq0] PASSED
tests/test_puzzles_extra.py::test_every_piece_solved_by_its_recorded_key_route[normal-seq1] PASSED
tests/test_puzzles_extra.py::test_every_piece_solved_by_its_recorded_key_route[hard-seq2] PASSED
tests/test_puzzles_extra.py::test_preparation_pieces_are_necessary[normal] PASSED
tests/test_puzzles_extra.py::test_preparation_pieces_are_necessary[hard] PASSED
tests/test_puzzles_extra.py::test_prep_placements_are_reachable_by_bfs PASSED
tests/test_puzzles_extra.py::test_tspin_route_uses_rotation_and_kicks PASSED
tests/test_puzzles_extra.py::test_hint_matches_solution PASSED
tests/test_puzzles_extra.py::test_hint_detects_off_witness_path PASSED
tests/test_puzzles_extra.py::test_failure_when_dropping_t_without_spin_and_outcome_is_final PASSED
tests/test_puzzles_extra.py::test_success_updates_spin_statistics_once PASSED
tests/test_puzzles_extra.py::test_generation_failure_is_bounded PASSED
tests/test_regressions.py::test_o_piece_cells_identical_in_all_rotations PASSED
tests/test_regressions.py::test_other_pieces_keep_matrix_rotation PASSED
tests/test_regressions.py::test_o_rotation_on_empty_board_does_not_move_cells PASSED
tests/test_regressions.py::test_o_rotation_on_floor_then_lock_never_raises PASSED
tests/test_regressions.py::test_o_rotation_against_walls[-1] PASSED
tests/test_regressions.py::test_o_rotation_against_walls[7] PASSED
tests/test_regressions.py::test_o_rotation_next_to_obstacles PASSED
tests/test_regressions.py::test_o_rotation_in_narrow_well_keeps_cells PASSED
tests/test_regressions.py::test_o_repeated_rotation_then_hard_drop_player PASSED
tests/test_regressions.py::test_receiving_one_garbage_line_does_not_end_game PASSED
tests/test_regressions.py::test_receiving_several_lines_keeps_playing[2] PASSED
tests/test_regressions.py::test_receiving_several_lines_keeps_playing[3] PASSED
tests/test_regressions.py::test_receiving_several_lines_keeps_playing[4] PASSED
tests/test_regressions.py::test_garbage_pushes_locked_blocks_up PASSED
tests/test_regressions.py::test_real_top_out_from_garbage PASSED
tests/test_regressions.py::test_attack_tetris_sends_four_and_cancel_rules PASSED
tests/test_regressions.py::test_play_continues_after_garbage PASSED
tests/test_regressions.py::test_rotation_in_the_air_then_hard_drop_is_not_t_spin PASSED
tests/test_regressions.py::test_real_spin_path_is_t_spin PASSED
tests/test_regressions.py::test_soft_drop_after_rotation_clears_rotation_flag PASSED
tests/test_rules_match.py::test_line_clear_scores_one_to_four PASSED
tests/test_rules_match.py::test_combo_adds_score_and_attack PASSED
tests/test_rules_match.py::test_back_to_back_tetris_bonus PASSED
tests/test_rules_match.py::test_level_increases_gravity PASSED
tests/test_rules_match.py::test_two_player_simultaneous_mode_sends_no_attack PASSED
tests/test_rules_match.py::test_versus_and_ai_modes_route_attacks_both_ways PASSED
tests/test_rules_match.py::test_simultaneous_attacks_partially_cancel PASSED
tests/test_rules_match.py::test_players_are_independent PASSED
tests/test_rules_match.py::test_win_rules_per_mode PASSED
tests/test_rules_match.py::test_records_win_loss_lines_and_reload PASSED
tests/test_rules_match.py::test_aborted_and_solo_games_never_count_as_wins PASSED
tests/test_rules_match.py::test_partial_record_file_is_merged PASSED
```
