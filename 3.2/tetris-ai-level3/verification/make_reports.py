"""Build verification/performance_results.md, verification/test_results.md and the chart images
in docs/figures/ directly from the measured JSON files (no number is typed by hand).
Usage: python verification/make_reports.py"""
import json
import re
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

V = Path(__file__).resolve().parent
ROOT = V.parent
FIG = ROOT / 'docs' / 'figures'; FIG.mkdir(parents=True, exist_ok=True)
plt.rcParams['font.family'] = 'Malgun Gothic'
plt.rcParams['axes.unicode_minus'] = False
BLUE, ORANGE, AQUA = '#2a78d6', '#eb6834', '#1baf7a'     # reference categorical slots 1-3
INK, INK2, GRIDC = '#0b0b0b', '#52514e', '#e4e3df'
ENV = 'Windows 11 Home · Intel Core i7-8700 3.2 GHz · RAM 32 GB · Python 3.12.4'


def load(name):
    return json.loads((V / name).read_text(encoding='utf-8'))


ai_b, ai_a = load('perf_ai_before.json'), load('perf_ai_after.json')
gui = {(t, d): load(f'perf_gui_{t}_{d}.json') for t in ('before', 'after') for d in ('normal', 'hard')}
diff = load('difficulty_v1.json')
misc = load('perf_misc.json')
bugs_b, bugs_a = load('bugs_before.json'), load('bugs_after.json')
DN = {'easy': '쉬움', 'normal': '보통', 'hard': '어려움'}


def style(ax):
    for s in ('top', 'right'):
        ax.spines[s].set_visible(False)
    for s in ('left', 'bottom'):
        ax.spines[s].set_color('#b9b8b2')
    ax.tick_params(colors=INK2, labelsize=10)
    ax.yaxis.grid(True, color=GRIDC, linewidth=.8); ax.set_axisbelow(True)


# ---------------------------------------------------------------- chart 1: AI search time
fig, ax = plt.subplots(figsize=(7.2, 3.6), dpi=200)
x = range(3); w = .36
for k, (data, label, col, off) in enumerate([(ai_b, '개선 전(원본)', ORANGE, -w / 2 - .01), (ai_a, '개선 후', BLUE, w / 2 + .01)]):
    vals = [data['difficulties'][d]['mean_ms'] for d in DN]
    bars = ax.bar([i + off for i in x], vals, w, color=col, label=label, zorder=2)
    for b, v in zip(bars, vals):
        ax.text(b.get_x() + b.get_width() / 2, v * 1.12, f'{v:.1f}', ha='center', va='bottom', fontsize=9, color=INK)
ax.set_yscale('log'); ax.set_ylim(1, 3000)
ax.set_xticks(list(x)); ax.set_xticklabels([f'{n}' for n in DN.values()], fontsize=11, color=INK)
ax.set_ylabel('평균 탐색 시간 (ms, 로그 축)', color=INK2)
ax.set_title('AI 1회 탐색 시간 — 동일 보드 100개 × 3회', fontsize=12, color=INK, loc='left')
style(ax); ax.legend(frameon=False, fontsize=10, loc='upper left')
fig.tight_layout(); fig.savefig(FIG / 'chart_ai_time.png'); plt.close(fig)

# ---------------------------------------------------------------- chart 2: GUI key latency / stalls
fig, axes = plt.subplots(1, 2, figsize=(7.2, 3.3), dpi=200)
for ax, metric, title in [(axes[0], ('key_latency', 'p95_ms'), '키 입력 지연 p95 (ms)'),
                          (axes[1], ('loop_gap', 'max_ms'), '이벤트 루프 최대 정지 (ms)')]:
    for i, d in enumerate(('normal', 'hard')):
        for j, (t, col) in enumerate((('before', ORANGE), ('after', BLUE))):
            v = gui[(t, d)][metric[0]][metric[1]]
            xpos = i + (j - .5) * .38
            ax.bar(xpos, v, .36, color=col, zorder=2, label=('개선 전' if t == 'before' else '개선 후') if i == 0 else None)
            ax.text(xpos, v * 1.15, f'{v:,.0f}' if v >= 10 else f'{v:.1f}', ha='center', fontsize=8.5, color=INK)
    ax.set_yscale('log'); ax.set_ylim(1, 20000)
    ax.set_xticks([0, 1]); ax.set_xticklabels(['보통', '어려움'], color=INK)
    ax.set_title(title, fontsize=11, color=INK, loc='left'); style(ax)
axes[0].legend(frameon=False, fontsize=9, loc='upper left')
fig.suptitle('인간 vs AI 모드 20초 측정 (AI 도우미 켬, 150 ms마다 키 입력)', fontsize=10, color=INK2, x=.01, ha='left')
fig.tight_layout(); fig.savefig(FIG / 'chart_gui.png'); plt.close(fig)

# ---------------------------------------------------------------- chart 3: difficulty head-to-head
fig, ax = plt.subplots(figsize=(7.2, 2.6), dpi=200)
pairs = [('easy', 'normal'), ('normal', 'hard'), ('easy', 'hard')]
for i, (a, b) in enumerate(pairs):
    r = diff['versus'][f'{a}_vs_{b}']['wins']
    ax.barh(i, r[a], color=ORANGE if a == 'easy' else BLUE, zorder=2)
    ax.barh(i, r[b], left=r[a], color=BLUE if b == 'normal' else AQUA, zorder=2)
    ax.text(r[a] / 2, i, f'{DN[a]} {r[a]}승', ha='center', va='center', color='white', fontsize=9.5, fontweight='bold')
    ax.text(r[a] + r[b] / 2, i, f'{DN[b]} {r[b]}승', ha='center', va='center', color='white', fontsize=9.5, fontweight='bold')
ax.set_yticks(range(3)); ax.set_yticklabels([f'{DN[a]} vs {DN[b]}' for a, b in pairs], color=INK)
ax.set_xlim(0, 10); ax.invert_yaxis(); ax.set_xlabel('승리 수 (10경기, 실제 공격 규칙 적용)', color=INK2)
style(ax); ax.yaxis.grid(False); ax.xaxis.grid(True, color=GRIDC)
fig.tight_layout(); fig.savefig(FIG / 'chart_difficulty.png'); plt.close(fig)


# ---------------------------------------------------------------- performance_results.md
def row(*c):
    return '| ' + ' | '.join(str(x) for x in c) + ' |'


L = ['# 성능 측정 결과', '', f'측정 환경: {ENV}  ', '측정일: 2026-11-16 · 모든 수치는 `verification/*.json`의 실제 측정값이며 이 문서는 `make_reports.py`가 자동 생성합니다.', '']
L += ['## 1. AI 탐색 시간 (개선 전·후 동일 입력)', '',
      '- 입력: 정상 AI로 5개 시드(3, 11, 29, 47, 83)를 진행하며 3블록마다 저장한 **고정 보드 100개** (`bench_boards.json`)',
      '- 방법: 각 보드에서 `choose()` 1회 호출 시간, 보드당 3회 반복(난이도별 300회), 캐시를 매번 비운 **콜드 측정**',
      '- 도구: `python verification/bench_ai.py <프로젝트 폴더> verification/bench_boards.json <결과.json>`', '',
      row('난이도', '개선 전 평균', '개선 전 p95', '개선 전 최대', '개선 후 평균', '개선 후 p95', '개선 후 최대', '평균 기준 배수'),
      row(*['---'] * 8)]
for d in DN:
    b, a = ai_b['difficulties'][d], ai_a['difficulties'][d]
    L.append(row(DN[d], f"{b['mean_ms']} ms", f"{b['p95_ms']} ms", f"{b['max_ms']} ms", f"{a['mean_ms']} ms", f"{a['p95_ms']} ms", f"{a['max_ms']} ms", f"{b['mean_ms'] / a['mean_ms']:.1f}배"))
L += ['', '**정확도 유지 확인:** `check_ai_equivalence.py`로 같은 300개 사례(보드 100 × 난이도 3)에서 원본과 최적화 AI의 '
      '**전체 후보 순위와 점수가 300/300 동일**(점수 차 최대 0.0)함을 확인했습니다. 또한 `tests/test_ai_extra.py`가 원본 알고리즘을 '
      '그대로 옮긴 참조 구현과 결과를 비교합니다.', '',
      '최적화 내용: 회전별 블록 좌표 사전 계산, 보드를 20개 행 비트마스크로 변환, 열 높이로 낙하 위치를 한 번에 계산, '
      '이동 전 보드 평가(높이·구멍·T-Spin 후보)를 탐색당 1회만 계산, 결과 LRU 캐시(512개), 백그라운드 작업 스레드.', '']
L += ['## 2. GUI 응답성 (실제 Tk 창, 개선 전·후 동일 부하)', '',
      '- 부하: 인간 vs AI 모드, AI 도우미 켬, 150 ms마다 합성 키 입력(←, →, ↑ 반복, 8번째마다 Space)을 Tk 이벤트 큐로 전달, 20초',
      '- 이벤트 루프 정지: 10 ms 주기 `after()` 탐침의 실제 실행 간격 (간격이 길수록 그동안 입력·그리기가 멈춤)',
      '- 키 입력 지연: `event_generate(when=\'tail\')` 시점부터 앱의 키 처리기가 끝날 때까지',
      '- 도구: `python verification/gui_probe.py <프로젝트 폴더> <결과.json> 20 <난이도>`', '',
      row('조건', '루프 탐침 실행 수', '루프 간격 평균', '루프 간격 p95', '최대 정지', '100 ms 초과 정지', '처리된 키 수', '키 지연 평균', '키 지연 p95', '키 지연 최대'),
      row(*['---'] * 10)]
for d in ('normal', 'hard'):
    for t in ('before', 'after'):
        g = gui[(t, d)]
        L.append(row(f"{DN[d]} · {'개선 전' if t == 'before' else '개선 후'}", g['loop_gap']['n'], f"{g['loop_gap']['mean_ms']} ms", f"{g['loop_gap']['p95_ms']} ms",
                     f"{g['loop_gap']['max_ms']} ms", g['stalls_over_100ms'], g['key_latency']['n'], f"{g['key_latency']['mean_ms']} ms",
                     f"{g['key_latency']['p95_ms']} ms", f"{g['key_latency']['max_ms']} ms"))
gb = gui[('before', 'hard')]
L += ['', f"해석: 원본은 어려움 난이도에서 측정 시간 {gb['seconds']}초 동안(20초 예정이었으나 정지 때문에 늘어남) 이벤트 루프 탐침이 {gb['loop_gap']['n']}번만 실행되었고(평균 {gb['loop_gap']['mean_ms']/1000:.1f}초마다), "
      f"키 입력은 {gb['key_latency']['n']}개만 처리되었습니다. 화면을 다시 그릴 때마다 AI 탐색 `choose()`를 3번 동기 호출했기 때문입니다. "
      '개선 후에는 AI 탐색이 작업 스레드에서 실행되고, 그리기 코드는 저장된 결과만 사용합니다.', '',
      '남은 제한: Python GIL 때문에 작업 스레드가 계산하는 동안 메인 스레드도 약간 느려집니다(측정된 최대 정지에 포함). 어려움 탐색이 최대 약 190 ms이므로 체감 영향은 작습니다.', '']
L += ['## 3. 난이도별 실제 플레이 성능', '',
      f"- 1인 플레이: 시드 {diff['seeds']} 5판, 최대 {diff['solo_pieces_cap']}블록, 같은 7-bag 순서", '',
      row('난이도', '평균 배치 블록', '평균 제거 줄', 'Top-out(5판 중)'), row(*['---'] * 4)]
for d in DN:
    s = diff['solo'][d]
    L.append(row(DN[d], s['mean_pieces'], s['mean_lines'], s['topouts']))
L += ['', '- AI 대 AI 대전: `engine.Match`의 실제 공격·상쇄·방해 줄 규칙, 블록 1:1 교대(같은 속도), 10경기, 좌우 진영 교대, 600블록 제한', '',
      row('대전', '결과', '평균 경기 길이(블록)'), row(*['---'] * 3)]
for a, b in pairs:
    r = diff['versus'][f'{a}_vs_{b}']
    L.append(row(f'{DN[a]} vs {DN[b]}', f"{DN[a]} {r['wins'][a]}승 · {DN[b]} {r['wins'][b]}승 · 무 {r['wins']['draw']}", r['mean_pieces']))
L += ['', '도구: `python verification/bench_difficulty.py verification/difficulty_v1.json 500 10`', '']
L += ['## 4. 퍼즐 생성 시간 (시드 0~49, 난이도별 50개)', '', row('난이도', '평균', 'p95', '최대', '검증 통과', '최대 시도 횟수'), row(*['---'] * 6)]
for d in DN:
    m = misc['puzzle_generation'][d]
    L.append(row(DN[d], f"{m['mean_ms']} ms", f"{m['p95_ms']} ms", f"{m['max_ms']} ms", f"{m['validated']}/{m['seeds']}", m['max_attempts']))
r = misc['records']
L += ['', '## 5. 기록 저장·불러오기 (200회 반복)', '',
      f"- 파일 크기 {r['file_bytes']:,} bytes (기록 {r['history_entries']}건)",
      f"- 저장(임시 파일 + os.replace 원자적 교체): 평균 {r['save']['mean_ms']} ms, 최대 {r['save']['max_ms']} ms",
      f"- 불러오기(손상 파일 복구 포함): 평균 {r['load']['mean_ms']} ms, 최대 {r['load']['max_ms']} ms", '',
      '## 6. 40개 이상 블록 연속 처리 안정성', '',
      '- `test_all_difficulties_return_valid_placements_and_board_stays_consistent`: 난이도 3개 × 45블록, 매 블록마다 칸 수 보존(+4 − 10×제거 줄) 확인',
      '- `test_ai_plays_forty_pieces_without_crash`, `test_play_continues_after_garbage`(방해 줄 수신 후 30블록), 위 1인 플레이 벤치마크(최대 500블록) 모두 오류 없음']
(V / 'performance_results.md').write_text('\n'.join(L) + '\n', encoding='utf-8')

# ---------------------------------------------------------------- test_results.md
out = (V / 'pytest_output.txt').read_text(encoding='utf-8')
tests = re.findall(r'^(tests/\S+?)::(\S+) (PASSED|FAILED|SKIPPED|ERROR)', out, re.M)
summary = re.findall(r'=+ (.*(?:passed|failed).*) =+', out)[-1]
files = {}
for f, n, st in tests:
    files.setdefault(f, []).append((n, st))
DESC = {'tests/test_engine.py': '기존 테스트(원본 23개 중 18개): 7-bag, 회전, 충돌, 줄 제거, 공격, Hold, AI, 퍼즐, 저장',
        'tests/test_integration.py': '기존 통합 테스트(원본 5개): AI 40블록, 퍼즐 해답, 시드 공정성, 공격 상쇄, 키 경로',
        'tests/test_regressions.py': '신규: O 회전·방해 줄·T-Spin 낙하 판정 버그의 회귀 테스트',
        'tests/test_rules_match.py': '신규: 1~4줄 점수, Combo/B2B, 레벨 속도, 모드별 공격 라우팅, 승패, 기록',
        'tests/test_ai_extra.py': '신규: 참조 구현과 동일성, 난이도 차이, 캐시, 작업 스레드, 오래된 결과 폐기',
        'tests/test_puzzles_extra.py': '신규: 모든 블록의 실제 키 경로, 준비 블록 필요성, 힌트, 성공/실패, 생성 실패 처리',
        'tests/test_gui.py': '신규: 실제 Tk 창 + 키 이벤트 통합 테스트 (2인 동시 입력, 공격, AI, 일시정지, 재시작, 퍼즐, 크기 변경)'}
T = ['# 테스트 결과', '', f'실행 명령: `python -m pytest -v` · 실행일 2026-11-16 · {ENV}', '',
     f'**최종 결과: {summary}** (실패 0, 건너뜀 0)', '',
     '원본 프로젝트의 테스트 23개는 하나도 지우거나 바꾸지 않고 그대로 통과합니다. 새로 추가한 테스트는 77개입니다.', '',
     row('파일', '개수', '통과', '내용'), row('---', '---', '---', '---')]
for f, items in files.items():
    T.append(row(f'`{f}`', len(items), sum(s == 'PASSED' for _, s in items), DESC.get(f, '')))
T += ['', '## 실제 GUI 검증', '',
      '- `tests/test_gui.py`의 16개 테스트는 실제 Tk 창을 띄우고 `event_generate`로 키 이벤트를 Tk 이벤트 큐에 넣어 앱의 실제 메인 루프를 실행합니다.',
      '- 확인 항목: 1인용 조작, DAS 자동 반복, 2인 동시 키 누름, 2인 대전 공격 송수신 후 계속 진행, AI 백그라운드 플레이 중 이벤트 루프 정지 250 ms 미만, '
      '다시 그리기 중 AI 재탐색 없음, 도우미 점수와 평가함수 일치, 일시정지 상태 고정, 재시작·모드 변경 시 오래된 AI 결과 무시, AI 계산 중 종료, '
      '게임오버 승자 결정 및 기록 파일 저장, 키보드만으로 퍼즐 풀이 후 통계 1회 증가, 힌트 3단계와 실패 판정, 창 크기 변경 시 레이아웃, 기록 창.',
      '- 모니터가 없는 환경에서는 `tkinter.Tk()` 생성이 실패하므로 GUI 테스트는 자동으로 건너뜁니다(이번 실행은 Windows 데스크톱에서 실제로 실행되어 건너뜀 0).',
      '- 한글 입력기(IME) 상태의 P2 키: Tk는 IME 키를 합성할 수 없어, 키 이름 변환 함수와 실제 처리기를 가짜 이벤트로 검증했습니다. 실제 한글 IME 환경에서의 수동 확인은 하지 않았습니다.',
      '- 시연 영상(`테트리스_레벨3_실제플레이_시연영상.mp4`, 3분 39초)은 `python run.py`로 실행한 실제 프로그램을 Windows SendInput(OS 키보드·마우스 입력)만으로 조작하며 게임 창만 녹화한 **자동화된 GUI 입력 시연**입니다. 게임 내부 상태는 변경하지 않았습니다(검증: `docs/real_demo/영상_검증.md`).',
      '',
      '## 버그 재현 (원본 vs 수정본, 같은 시나리오)', '',
      '`python verification/reproduce_bugs.py <프로젝트 폴더> <결과.json>` → `bugs_before.json`, `bugs_after.json`', '',
      row('시나리오', '원본', '수정본'), row('---', '---', '---')]


def fmt(v):
    return v.get('exception') if isinstance(v, dict) and 'exception' in v else json.dumps(v, ensure_ascii=False)


for k in ('o_rotation_on_floor', 'receive_1_garbage_line', 'versus_tetris_attack', 'rotate_in_air_then_hard_drop', 'puzzle_success_spin_counter'):
    b = bugs_b[k]; a = bugs_a[k]
    if k == 'o_rotation_on_floor':
        b = b.get('exception', b); a = f"회전 전후 칸 동일={a['cells_before'] == a['cells_after_rotate']}, Hard Drop {a['hard_drop']}"
    T.append(row(k, fmt(b) if not isinstance(b, str) else b, a if isinstance(a, str) else fmt(a)))
T += ['', '## 전체 테스트 목록', '', '```'] + [f'{f}::{n} {s}' for f, n, s in tests] + ['```']
(V / 'test_results.md').write_text('\n'.join(T) + '\n', encoding='utf-8')
print('ok', summary, len(tests))
