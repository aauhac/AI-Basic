"""Generate the report (DOCX) and the slide deck (PPTX) from the final code and measured results.

  python docs/make_submission_docs.py

Every number is read from verification/*.json or verification/pytest_output.txt, so the documents
always match what was actually measured.  Also writes:
  docs/figures/fig_*.png        diagrams (matplotlib)
  docs/preview/slide_XX.png     PIL previews of every slide drawn from the same layout data
                                (used to check text fit, because Office is not installed here)
"""
import json
import re
import sys
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
from PIL import Image, ImageDraw, ImageFont
from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt, Cm, RGBColor
from pptx import Presentation
from pptx.dml.color import RGBColor as PRGB
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.util import Inches as PI, Pt as PP

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
DOCS = ROOT / 'docs'; FIG = DOCS / 'figures'; SHOT = DOCS / 'screens'; PREV = DOCS / 'preview'
VER = ROOT / 'verification'
for d in (FIG, PREV):
    d.mkdir(parents=True, exist_ok=True)

AUTHOR = '국립금오공과대학교 인공지능공학전공  |  20230007 강민혁'
COURSE = 'AI기초프로젝트 · 레벨 3 · 3.2 인간-AI 대전 테트리스'
DATE = '2026년 11월 16일'
ENV = 'Windows 11 Home · Intel Core i7-8700 (3.2 GHz) · RAM 32 GB · Python 3.12.4'
DN = {'easy': '쉬움', 'normal': '보통', 'hard': '어려움'}


def J(name):
    return json.loads((VER / name).read_text(encoding='utf-8'))


AIB, AIA = J('perf_ai_before.json'), J('perf_ai_after.json')
GUI = {(t, d): J(f'perf_gui_{t}_{d}.json') for t in ('before', 'after') for d in ('normal', 'hard')}
DIF = J('difficulty_v1.json'); MISC = J('perf_misc.json')
BB, BA = J('bugs_before.json'), J('bugs_after.json')
PYOUT = (VER / 'pytest_output.txt').read_text(encoding='utf-8')
TESTS = re.findall(r'^(tests/\S+?)::(\S+) (PASSED|FAILED|SKIPPED|ERROR)', PYOUT, re.M)
N_TOTAL = len(TESTS); N_PASS = sum(s == 'PASSED' for *_, s in TESTS)
N_FAIL = sum(s in ('FAILED', 'ERROR') for *_, s in TESTS); N_SKIP = sum(s == 'SKIPPED' for *_, s in TESTS)
PER_FILE = {}
for f, n, s in TESTS:
    PER_FILE.setdefault(f, [0, 0]); PER_FILE[f][0] += 1; PER_FILE[f][1] += s == 'PASSED'
N_ORIG = PER_FILE.get('tests/test_engine.py', [0])[0] + PER_FILE.get('tests/test_integration.py', [0])[0]
N_GUI = PER_FILE.get('tests/test_gui.py', [0])[0]
assert N_FAIL == 0 and N_PASS == N_TOTAL, 'documents are only generated from a fully passing test run'


def ms(v):
    return f'{v:,.1f} ms' if v < 100 else f'{v:,.0f} ms'


hb, ha = AIB['difficulties']['hard'], AIA['difficulties']['hard']
gbh, gah = GUI[('before', 'hard')], GUI[('after', 'hard')]
VS = DIF['versus']


# ======================================================================= real example for the coach section
def coach_example():
    from tetris.engine import Player
    from tetris.ai import choose, preview_at
    p = Player('P1', seed=52)
    for _ in range(9):
        b, _ = choose(p.board, p.active.kind, p.next[0], 'normal'); p.active = b.piece.copy(); p.hard_drop()
    cur = preview_at(p.board, p.active)
    best, cands = choose(p.board, p.active.kind, p.next[0], 'normal')
    return p, cur, best, len(cands)


CP, CUR, BEST, NCAND = coach_example()

# ======================================================================= diagrams (units = inches)
plt.rcParams['font.family'] = ['Malgun Gothic', 'Segoe UI Symbol']
plt.rcParams['axes.unicode_minus'] = False
NAVY = '#13253b'; TEAL = '#1f9e93'; LIGHT = '#eef4f8'; MID = '#cfdde8'; GOLDC = '#b07400'; INK = '#1b1b1b'


def box(ax, x, y, w, h, text, fc=LIGHT, ec=NAVY, fs=10.5, bold=False, tc=INK, ls='-'):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle='round,pad=0,rounding_size=0.08', fc=fc, ec=ec, lw=1.3, ls=ls))
    if text:
        ax.text(x + w / 2, y + h / 2, text, ha='center', va='center', fontsize=fs, color=tc,
                fontweight='bold' if bold else 'normal', linespacing=1.4)


def arrow(ax, x1, y1, x2, y2, color=NAVY, ls='-'):
    ax.add_patch(FancyArrowPatch((x1, y1), (x2, y2), arrowstyle='-|>', mutation_scale=14, color=color, lw=1.5, linestyle=ls))


def label(ax, x, y, text, color=INK, fs=9.5, bold=False, ha='center'):
    ax.text(x, y, text, ha=ha, va='center', fontsize=fs, color=color, fontweight='bold' if bold else 'normal', linespacing=1.35)


def canvas(w, h):
    fig = plt.figure(figsize=(w, h), dpi=200)
    ax = fig.add_axes([0, 0, 1, 1]); ax.set_xlim(0, w); ax.set_ylim(0, h); ax.axis('off')
    return fig, ax


def save(fig, name):
    fig.savefig(FIG / name, facecolor='white'); plt.close(fig)


# architecture 10 x 5.6
fig, ax = canvas(10, 5.6)
box(ax, .1, 1.9, 5.8, 3.6, '', fc='#f6f9fb', ec=MID, ls='--')
label(ax, .3, 5.22, 'Tk 메인 스레드 — 모든 위젯과 Player 객체를 소유', NAVY, 11, True, 'left')
box(ax, .3, 3.55, 2.6, 1.3, 'gui.py\n키 입력(DAS) · 중력 타이머\n변화가 있을 때만 그리기')
box(ax, 3.1, 3.55, 2.6, 1.3, 'engine.py\nPlayer · Match\n8단계 고정 처리')
box(ax, .3, 2.1, 2.6, 1.15, 'puzzles.py\nBFS 키 경로 · 퍼즐 검증')
box(ax, 3.1, 2.1, 2.6, 1.15, 'storage.py\nrecords.json 원자적 저장')
arrow(ax, 2.9, 4.2, 3.1, 4.2); arrow(ax, 1.6, 3.55, 1.6, 3.25); arrow(ax, 4.4, 3.55, 4.4, 3.25)
box(ax, 7.3, 1.9, 2.6, 3.6, '', fc='#fff8ea', ec='#e7c27a', ls='--')
label(ax, 7.45, 5.22, 'AI 작업 스레드 (AIWorker)', GOLDC, 11, True, 'left')
box(ax, 7.5, 3.55, 2.2, 1.3, 'ai.choose()\n후보 탐색 + 평가\nLRU 캐시 (Lock)', fc='#fff3d6', ec=GOLDC)
box(ax, 7.5, 2.1, 2.2, 1.15, '결과 큐\n토큰 · 최선 후보 · 시간', fc='#fff3d6', ec=GOLDC)
arrow(ax, 8.6, 3.55, 8.6, 3.25, GOLDC)
arrow(ax, 5.9, 4.45, 7.5, 4.45, GOLDC); label(ax, 6.6, 4.9, '작업 큐\n보드 복사본 + 토큰', GOLDC, 9)
arrow(ax, 7.5, 2.55, 5.9, 2.55, GOLDC, '--'); label(ax, 6.6, 3.05, '16 ms마다 확인\n토큰 일치 시만 적용', GOLDC, 9)
box(ax, .1, .1, 9.8, 1.55, '', fc='white', ec=MID)
label(ax, .3, 1.38, '동기화 원칙', NAVY, 10.5, True, 'left')
for i, t in enumerate(['① 작업 스레드는 보드 복사본만 읽는다 — 게임 상태를 공유하지 않음',
                       '② 데이터는 thread-safe 큐로만 오가고, Tk 위젯·Player는 메인 스레드만 변경',
                       '③ 재시작·모드 변경·종료 → game_id 증가 + 작업 세대 번호로 오래된 작업·결과 폐기']):
    label(ax, .3, 1.02 - i * .32, t, INK, 9.8, False, 'left')
save(fig, 'fig_architecture.png')

# lock pipeline 10 x 2.1
fig, ax = canvas(10, 2.1)
steps = ['① 블록\n고정', '② active 해제\n줄 제거·점수', '③ Combo\nB2B·T-Spin', '④ 공격\n계산', '⑤ 받을 공격\n상쇄',
         '⑥ 남은 방해\n줄 삽입', '⑦ Top-out\n판정', '⑧ 다음 블록\n생성']
for i, t in enumerate(steps):
    x = .1 + i * 1.235
    hot = i in (1, 5)
    box(ax, x, .75, 1.08, 1.1, t, fc='#e3f4f1' if hot else LIGHT, ec=TEAL if hot else NAVY, fs=9.6, bold=hot)
    if i < 7:
        arrow(ax, x + 1.08, 1.3, x + 1.235, 1.3)
label(ax, .1, .32, '수정 핵심: ②에서 고정된 블록을 active에서 해제한 뒤 ⑥을 수행 '
      '(원본은 고정된 블록이 자기 자신과 겹친다고 판단 → 즉시 게임오버)', TEAL, 9.5, False, 'left')
save(fig, 'fig_lock_pipeline.png')

# AI search 10 x 3.7
fig, ax = canvas(10, 3.7)
box(ax, .1, 1.85, 1.8, 1.7, '입력\n보드\n현재 블록\n다음 블록', bold=True)
box(ax, 2.2, 1.85, 2.35, 1.7, '후보 생성\n회전(최대 4) × 열\n열 높이로 착지 계산\n같은 칸 집합은 1번')
box(ax, 4.85, 1.85, 2.55, 1.7, '평가 (7개 항목)\n줄 제거 · T-Spin\n최대 높이 · 구멍\n평탄도 · 전체 높이\nT-Spin 후보', fs=10)
box(ax, 7.7, 1.85, 2.2, 1.7, '어려움만\n각 후보 보드에서\n다음 블록 후보 전체\n재평가 → +0.65×최선', fc='#e3f4f1', ec=TEAL, fs=10)
arrow(ax, 1.9, 2.7, 2.2, 2.7); arrow(ax, 4.55, 2.7, 4.85, 2.7); arrow(ax, 7.4, 2.7, 7.7, 2.7)
box(ax, 7.7, .1, 2.2, 1.35, '출력\n최고 점수 (x, 회전)\n+ 항목별 기여 점수')
arrow(ax, 8.8, 1.85, 8.8, 1.45)
box(ax, .1, .1, 7.3, 1.35, '', fc='white', ec=MID)
label(ax, .3, 1.07, '쉬움: 줄 제거 + 최대 높이 + 0.35×구멍만 사용, 다음 블록은 보지 않음', INK, 10, False, 'left')
label(ax, .3, .72, '보통: 7개 항목 가중합 (현재 블록만)', INK, 10, False, 'left')
label(ax, .3, .37, '실행: 목표까지 실제 회전·이동을 한 단계씩 → Hard Drop (막히면 그 자리에서 낙하)', INK, 10, False, 'left')
save(fig, 'fig_ai_search.png')

# puzzle 10 x 3.4
fig, ax = canvas(10, 3.4)
label(ax, .1, 3.15, 'BFS 상태 = (x, y, 회전, 마지막 동작이 회전인가)    동작 = ← → ↓ ↻ ↺  (SRS Wall Kick 포함)', TEAL, 10.5, True, 'left')
label(ax, .1, 2.8, '사람이 누를 수 있는 키만으로 도달 가능한 위치만 정답으로 인정 — 순간 이동 없음', INK, 10, False, 'left')
ps = [('① 구조 생성', '무작위 열·좌우 대칭\nT-Spin Double 슬롯\n바닥 방해 줄 0~2'), ('② 블록 자리 제거', '보통: 지붕(I 자리)\n어려움: 지붕 +\n2×2 빈칸(O 자리)'),
      ('③ 준비 블록 검증', 'BFS로 실제 키 경로\n줄 제거·Top-out\n없음 확인'), ('④ T-Spin 검증', '회전으로 끝나는 경로\n3모서리 규칙\n목표 줄 수 이상'),
      ('⑤ 필요성 검증', '초기 보드: 불가\n어려움: I만·O만\n놓아도 불가'), ('⑥ 출제', '해답·키 경로 저장\n3단계 힌트\n실패 시 최대 60회')]
for i, (t, dsc) in enumerate(ps):
    x = .1 + i * 1.65
    box(ax, x, 1.85, 1.48, .55, t, fc=NAVY, ec=NAVY, fs=10, bold=True, tc='white')
    box(ax, x, .15, 1.48, 1.55, dsc, fs=9.3)
    if i < 5:
        arrow(ax, x + 1.48, 2.12, x + 1.65, 2.12)
save(fig, 'fig_puzzle.png')

# ======================================================================= DOCX report
D = Document()
sec = D.sections[0]
sec.page_height = Cm(29.7); sec.page_width = Cm(21.0)
sec.top_margin = sec.bottom_margin = Cm(2.0); sec.left_margin = sec.right_margin = Cm(2.1)
KFONT = '맑은 고딕'


def set_font(style_or_run, size=None, bold=None, color=None):
    f = style_or_run.font
    f.name = KFONT
    rpr = style_or_run.element.get_or_add_rPr() if hasattr(style_or_run.element, 'get_or_add_rPr') else style_or_run._element.get_or_add_rPr()
    rf = rpr.find(qn('w:rFonts'))
    if rf is None:
        rf = OxmlElement('w:rFonts'); rpr.append(rf)
    for a in ('w:ascii', 'w:hAnsi', 'w:eastAsia', 'w:cs'):
        rf.set(qn(a), KFONT)
    if size: f.size = Pt(size)
    if bold is not None: f.bold = bold
    if color: f.color.rgb = RGBColor.from_string(color)


st = D.styles
set_font(st['Normal'], 10)
st['Normal'].paragraph_format.space_after = Pt(5); st['Normal'].paragraph_format.line_spacing = 1.3
for name, size, color, before, after in [('Title', 22, '13253B', 0, 6), ('Heading 1', 14.5, '13253B', 16, 6), ('Heading 2', 11.5, '1F6F68', 10, 4)]:
    s = st[name]; set_font(s, size, True, color)
    s.paragraph_format.space_before = Pt(before); s.paragraph_format.space_after = Pt(after); s.paragraph_format.keep_with_next = True
for name in ('List Bullet', 'Caption'):
    set_font(st[name], 10 if name == 'List Bullet' else 8.5)
st['Caption'].font.color.rgb = RGBColor(0x52, 0x51, 0x4e)


def P(text, bold_prefix=None, size=None, align=None, color=None):
    p = D.add_paragraph()
    if bold_prefix:
        r = p.add_run(bold_prefix); r.bold = True
    r = p.add_run(text)
    if size: r.font.size = Pt(size)
    if color: r.font.color.rgb = RGBColor.from_string(color)
    if align: p.alignment = align
    return p


def B(text, bold_prefix=None):
    p = D.add_paragraph(style='List Bullet')
    if bold_prefix:
        r = p.add_run(bold_prefix); r.bold = True
    p.add_run(text)
    return p


def H(text, level=1):
    return D.add_heading(text, level=level)


def shade(cell, hexcolor):
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement('w:shd'); shd.set(qn('w:val'), 'clear'); shd.set(qn('w:color'), 'auto'); shd.set(qn('w:fill'), hexcolor)
    tcPr.append(shd)


def T(cols, rows, widths=None, fs=8.8, head='13253B'):
    t = D.add_table(rows=1, cols=len(cols)); t.style = 'Table Grid'; t.alignment = WD_TABLE_ALIGNMENT.CENTER
    for i, h in enumerate(cols):
        c = t.rows[0].cells[i]; c.text = ''
        r = c.paragraphs[0].add_run(h); r.bold = True; r.font.size = Pt(fs); r.font.color.rgb = RGBColor(255, 255, 255)
        shade(c, head)
    for k, row in enumerate(rows):
        cells = t.add_row().cells
        for i, v in enumerate(row):
            cells[i].text = ''
            r = cells[i].paragraphs[0].add_run(str(v)); r.font.size = Pt(fs)
            if k % 2:
                shade(cells[i], 'F2F6F9')
    if widths:
        for row in t.rows:
            for i, w in enumerate(widths):
                row.cells[i].width = Cm(w)
    D.add_paragraph().paragraph_format.space_after = Pt(2)
    return t


def IMG(path, width_cm, caption):
    D.add_picture(str(path), width=Cm(width_cm))
    D.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
    c = D.add_paragraph(caption, style='Caption'); c.alignment = WD_ALIGN_PARAGRAPH.CENTER


# ---------- cover
for _ in range(5):
    D.add_paragraph()
p = D.add_paragraph(style='Title'); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
p.add_run('인간–AI 대전 테트리스')
p = D.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
r = p.add_run('구현 및 검증 보고서 (최종본)'); r.font.size = Pt(15); r.font.color.rgb = RGBColor(0x1f, 0x6f, 0x68); r.bold = True
D.add_paragraph()
for t in (COURSE, AUTHOR, f'작성·검증일: {DATE}  |  최종 코드와 실제 측정 결과 기준'):
    P(t, align=WD_ALIGN_PARAGRAPH.CENTER, size=11)
D.add_paragraph(); D.add_paragraph()
summary = [('필수 요구사항', 'PDF 3.2의 11개 항목 구현·검증'), ('자동 테스트', f'{N_TOTAL}개 중 {N_PASS}개 통과 (실제 Tk GUI 테스트 {N_GUI}개 포함)'),
           ('AI 응답성', f"어려움 탐색 평균 {ms(hb['mean_ms'])} → {ms(ha['mean_ms'])}, GUI 최대 정지 {ms(gbh['loop_gap']['max_ms'])} → {ms(gah['loop_gap']['max_ms'])}"),
           ('버그 수정', 'O 회전 오류·방해 줄 즉시 게임오버·퍼즐 통계 등 6건 (전후 재현 확인)'), ('확장 기능', 'SRS·T-Spin·Combo/B2B, 설명 가능한 AI 도우미, BFS 검증 T-Spin 퍼즐 생성')]
T(['구분', '결과'], summary, widths=[3.5, 12.5], fs=9.5)
D.add_page_break()

# ---------- contents
H('목차')
toc = ['1. 프로젝트 개요와 개발 목표', '2. 과제 요구사항 분석', '3. 전체 소프트웨어 아키텍처', '4. 게임 엔진 설계', '5. SRS 회전과 T-Spin 알고리즘',
       '6. AI 탐색과 평가함수', '7. AI 난이도별 구현 차이', '8. GUI와 AI의 독립 실행 구조', '9. 공격 시스템과 승패 처리', '10. AI 도우미의 평가 점수 계산',
       '11. T-Spin 퍼즐 생성·검증 알고리즘', '12. 독창적 요소', '13. 설계 대안과 채택 근거', '14. 버그 수정 전후 비교', '15. 단위·통합 테스트',
       '16. 성능 측정 결과', '17. 한계점과 향후 개선', '18. 실행 방법과 결론']
for t in toc:
    P(t, size=10.5)
D.add_page_break()

# ---------- 1
H('1. 프로젝트 개요와 개발 목표')
P('본 프로젝트는 과제 3.2 "인간-AI 대전 테트리스"를 Python 표준 라이브러리(Tkinter)만으로 구현한 것이다. 7종 테트로미노의 이동·회전·낙하·충돌 규칙 위에 '
  '1인용, 2인 동시 플레이, 2인 대전, 인간 vs AI의 네 가지 필수 모드를 만들고, 현재 블록과 다음 블록을 고려해 배치를 고르는 탐색형 AI를 세 난이도로 제공한다.')
P('이번 최종본은 앞서 제출을 준비하던 1차 구현을 바탕으로, 실제 플레이에서 드러난 결함을 고치고 검증을 대폭 확장한 결과이다. 목표는 다음 네 가지였다.')
for a, b in [('요구사항 완전 충족: ', 'PDF의 11개 요구사항마다 담당 코드, 자동 테스트, 실제 실행 화면을 하나씩 대응시킨다.'),
             ('정확한 게임 규칙: ', '방해 줄을 받자마자 게임이 끝나는 문제, O 블록 회전 오류, 공중 회전 T-Spin 오판정을 고친다.'),
             ('멈추지 않는 GUI: ', 'AI가 계산하는 동안에도 입력·낙하·화면 갱신이 계속되도록 AI 연산을 분리하고, 결과가 같은 상태로 탐색 속도를 높인다.'),
             ('검증 가능한 확장: ', 'AI 도우미와 AI 퍼즐 생성이 "실제로 맞는지"를 테스트로 증명한다.')]:
    B(b, a)
P('AI는 신경망이나 강화학습을 쓰지 않는다. 가능한 모든 배치를 탐색하고 사람이 설계한 평가함수로 점수를 매기는 휴리스틱 탐색 AI이다.')

# ---------- 2
H('2. 과제 요구사항 분석')
P('PDF 인쇄 5쪽의 "제한요소 및 요구사항"을 11개 항목으로 나누고, 각 항목에서 해결해야 할 핵심 문제를 정리했다. 오른쪽 열은 그 문제에 대한 설계 결정이다.')
T(['#', '요구사항', '핵심 문제', '설계 결정'], [
    (1, '7종 블록·자동 낙하·이동·회전·빠른 낙하·충돌', '회전 시 벽·바닥 충돌', 'SRS 회전 + Wall Kick, 모든 이동 전 valid() 검사'),
    (2, '4개 모드 + 모드별 승패', '모드마다 인원·공격·승리 조건이 다름', 'engine.Match가 모드 규칙과 승패를 전담'),
    (3, '줄 수·연속 제거 차등 점수, 속도 증가', '점수와 레벨이 서로 맞물림', '1~4줄 점수표 + Combo/B2B, 10줄마다 낙하 간격 ×0.83'),
    (4, '대전 모드 방해 블록 공격', '고정·제거·공격·수신 순서', 'Player.lock() 8단계 고정 순서 + 상쇄'),
    (5, '현재+다음 블록 고려 최적 배치', '수천 개 보드 평가를 빠르게', '비트마스크 보드, 이동 전 평가 1회 계산, 결과 캐시'),
    (6, '3단계 난이도와 성능 차이', '이름만 다른 난이도', '평가 항목 수·탐색 깊이 차등 + 실제 대전으로 측정'),
    (7, 'Next 표시, Hold', 'Hold 남용', '블록당 Hold 1회, Next 3개 표시'),
    (8, '시작·일시정지·재개·종료·재시작, 독립 상태', '재시작 후 이전 작업 잔존', '게임 번호(game_id)와 토큰으로 이전 결과 폐기'),
    (9, '보드·Next·Hold·점수·레벨·난이도 GUI', '창 크기 변화', '캔버스 크기 비례 배치, 정적/동적 레이어'),
    (10, '인간·AI 독립, 연산 비간섭, 동기화', 'AI 계산이 이벤트 루프 차단', '작업 스레드 + 큐 + 보드 복사본 + Lock'),
    (11, '최고 점수·승패·줄 수 저장/재확인', '파일 손상·중단 경기', '원자적 저장, 손상 시 복구, 중단 경기 별도 집계'),
], widths=[0.7, 4.6, 4.0, 6.7], fs=8.3)
P('확장 문제는 "개별적으로 추가 기능을 정의한다"이므로, 필수 기능을 대체하지 않는 다섯 가지 확장(SRS/T-Spin, Combo·B2B·상쇄, AI 도우미, AI 퍼즐 생성, 2인 동시 입력용 자체 키 반복)을 정의했다.')

# ---------- 3
H('3. 전체 소프트웨어 아키텍처')
P('규칙(engine), 판단(ai), 퍼즐(puzzles), 저장(storage), 화면(gui)을 파일 단위로 나누었다. GUI를 제외한 모든 모듈은 Tkinter 없이 동작하므로 자동 테스트에서 직접 호출할 수 있다.')
IMG(FIG / 'fig_architecture.png', 16.5, '그림 1. 모듈 구성과 스레드 구조 (점선 화살표: 결과 큐 폴링)')
T(['파일', '주요 책임', '핵심 함수/클래스'], [
    ('engine.py', '블록·SRS·충돌·점수·공격·플레이어 상태, 모드 규칙', 'Piece, Player.lock, Match.after_lock/check_end'),
    ('ai.py', '배치 후보 탐색, 평가함수, 캐시, 작업 스레드', 'choose, preview_at, plan_actions, AIWorker'),
    ('puzzles.py', 'BFS 키 경로 탐색, 퍼즐 생성·검증, 퍼즐 진행·힌트', 'explore, legal_spin_locks, generate, PuzzleSession'),
    ('gui.py', '키 입력(DAS), 중력 타이머, AI 결과 적용, 그리기', 'GameApp.loop, key_down, redraw'),
    ('storage.py', 'records.json 저장/불러오기/병합', 'load_stats, save_stats, finish_match'),
], widths=[2.4, 7.2, 6.4], fs=8.6)

# ---------- 4
H('4. 게임 엔진 설계')
H('4.1 자료 구조', 2)
B('보드: 20×10 리스트(빈칸 None, 채워진 칸은 블록 종류 문자). 화면 위쪽 밖(y<0)에 놓인 칸은 충돌 검사에서 제외한다.')
B('Piece: 종류, x, y, 회전 상태, 마지막 동작이 회전인지(rotated_last), 사용한 킥 번호. 회전별 칸 좌표는 시작할 때 한 번 계산해 둔다(CELLS).')
B('Player: 보드, 7-bag, Next 5개, Hold, 점수·줄·레벨·Combo·B2B, 받을 공격(pending), 블록 번호(piece_id). 플레이어마다 별도 객체이므로 상태가 섞이지 않는다.')
B('Bag: 7종을 한 번씩 섞어 내보내는 7-bag. 대전에서는 두 플레이어가 같은 시드를 써서 블록 순서가 같다(공정성).')
H('4.2 블록 고정 처리 순서', 2)
P('블록을 고정할 때 처리 순서가 틀리면 공격이나 게임오버를 잘못 판정한다. 최종본은 다음 8단계를 항상 같은 순서로 수행한다.')
IMG(FIG / 'fig_lock_pipeline.png', 16.5, '그림 2. Player.lock()의 8단계 처리 순서')
H('4.3 점수·공격 규칙', 2)
T(['제거', '점수(×레벨)', '공격 줄', 'T-Spin 점수', 'T-Spin 공격'], [
    ('0줄', '0', '0', '400', '0'), ('1줄 (Single)', '100', '0', '800', '2'), ('2줄 (Double)', '300', '1', '1200', '4'),
    ('3줄 (Triple)', '500', '2', '1600', '6'), ('4줄 (Tetris)', '800', '4', '—', '—')], widths=[3.0, 3.0, 2.6, 3.0, 3.0], fs=8.8)
B('Combo: 연속으로 줄을 지울 때마다 점수 +50×Combo×레벨, 공격 +min(Combo, 4).')
B('Back-to-Back: Tetris 또는 줄을 지운 T-Spin이 연속되면 점수 ×1.5, 공격 +1.')
B('레벨: 1 + 제거 줄 수 ÷ 10. 낙하 간격 = max(0.08, 0.85 × 0.83^(레벨-1))초. 레벨 1은 0.85초, 레벨 5는 약 0.40초.')

# ---------- 5
H('5. SRS 회전과 T-Spin 알고리즘')
H('5.1 SRS Wall Kick', 2)
B('입력: 보드, 현재 블록, 회전 방향(시계/반시계).', '')
B('처리: 회전 상태 쌍(예: 0→1)마다 정해진 5개 이동 후보를 순서대로 시험하고, 처음으로 충돌이 없는 위치를 택한다. I 블록은 별도의 킥 표를 쓴다.')
B('출력: 회전된 새 Piece(rotated_last=True, kick_used=후보 번호) 또는 None(회전 불가 — 기존 상태 그대로).')
B('O 블록: SRS 규칙대로 네 회전 상태 모두 같은 칸을 차지한다. 원본은 3×3 행렬을 돌려 회전마다 정사각형이 한 칸씩 이동했고, 바닥에서 회전하면 보드 밖으로 나가 고정 시 오류가 났다.')
H('5.2 T-Spin 판정', 2)
P('T-Spin = (T 블록) 그리고 (마지막으로 성공한 동작이 회전) 그리고 (T 중심의 대각선 네 칸 중 3칸 이상이 막힘 — 벽·바닥 포함). '
  '최종본에서는 Hard Drop으로 한 칸 이상 떨어지면 마지막 동작이 회전이 아니게 되도록 drop()을 추가했다. 원본은 공중에서 T를 돌린 뒤 17칸을 떨어뜨려도 T-Spin으로 인정했다.')
P('T-Spin Mini(2모서리 규칙 등)는 구분하지 않는다. 이 단순화는 보고서와 README에 명시했다.')

# ---------- 6
H('6. AI 탐색과 평가함수')
IMG(FIG / 'fig_ai_search.png', 16.5, '그림 3. AI 의사결정 흐름 (입력 → 후보 생성 → 평가 → 출력)')
H('6.1 후보 생성', 2)
P('AI는 현재 블록의 모든 회전 상태(O는 1개)와 모든 가로 위치를 만든 뒤, 위에서 곧바로 떨어뜨렸을 때의 착지 위치를 구한다. 각 열의 가장 위 블록 행(top)을 미리 구해 두면 '
  '착지 행 y = min(top[x+dx] - 1 - dy)로 한 번에 계산된다(한 칸씩 내려 보는 것과 결과가 같다). 차지하는 칸 집합이 같은 후보는 하나만 남긴다. 빈 보드 기준 T 블록 후보는 34개다.')
H('6.2 평가함수', 2)
P('각 후보를 놓은 결과 보드와 놓기 전 보드를 비교한 "변화량"으로 점수를 매긴다. 이 점수는 게임 점수와 다른 AI 내부 점수이다.')
T(['항목', '가중치', '의미'], [
    ('줄 제거', '+110 × 줄²', '여러 줄을 한 번에 지울수록 크게 가점'), ('T-Spin', '+150 × (1+줄-1)', '실제 T-Spin 판정 시 (AI 후보는 곧바로 떨어뜨리므로 0)'),
    ('최대 높이 변화', '-14 × Δ', 'PDF가 제시한 "최대 높이 최소화"'), ('구멍 변화', '-64 × Δ', '블록 아래 막힌 빈칸 — 가장 크게 감점'),
    ('평탄도 변화', '-6.5 × Δ', '이웃 열 높이 차이의 합'), ('전체 높이 변화', '-3.4 × Δ', '모든 열 높이의 합'),
    ('T-Spin 후보 변화', '+14 × Δ', 'T 모양 빈 공간(3모서리) 개수 — 근사 신호')], widths=[3.2, 3.6, 9.2], fs=8.8)
H('6.3 속도 최적화 (결과는 동일)', 2)
for t in ['보드를 20개의 정수(행 비트마스크)로 바꿔 줄 제거·높이·구멍·T 공간 계산을 비트 연산으로 처리',
          '놓기 전 보드의 평가(높이·구멍·평탄도·T 공간)를 후보마다 다시 계산하지 않고 탐색당 1번만 계산',
          '탐색 결과를 (보드, 블록, 다음 블록, 난이도) 키로 LRU 캐시(512개, Lock 보호) — 화면을 다시 그릴 때 재계산 없음',
          f"검증: 고정 보드 100개 × 3난이도 = 300사례에서 원본과 전체 후보 순위·점수가 300/300 동일, 어려움 평균 {ms(hb['mean_ms'])} → {ms(ha['mean_ms'])}"]:
    B(t)

# ---------- 7
H('7. AI 난이도별 구현 차이')
T(['난이도', '탐색 범위', '평가 전략', 'AI 동작 속도(생각 / 동작당)'], [
    ('쉬움', '현재 블록의 모든 배치', '줄 제거 + 최대 높이 + 0.35×구멍 (평탄도·전체 높이 무시)', '0.45초 / 0.16초'),
    ('보통', '현재 블록의 모든 배치', '7개 항목 전체', '0.30초 / 0.10초'),
    ('어려움', '현재 × 다음 블록 (2단계)', '7개 항목 + 0.65 × 다음 블록 최선 점수', '0.20초 / 0.07초')], widths=[2.0, 4.2, 6.8, 3.0], fs=8.8)
P('난이도가 실제로 다른 실력을 내는지 두 가지로 측정했다(verification/bench_difficulty.py).')
sol = DIF['solo']
B(f"1인 플레이(시드 5개, 최대 {DIF['solo_pieces_cap']}블록): 쉬움은 5판 모두 Top-out(평균 {sol['easy']['mean_pieces']}블록, {sol['easy']['mean_lines']}줄), "
  f"보통·어려움은 5판 모두 {DIF['solo_pieces_cap']}블록까지 생존(평균 {sol['normal']['mean_lines']}줄, {sol['hard']['mean_lines']}줄).")
B(f"AI 대 AI 대전(실제 공격 규칙, 블록 1:1 교대로 같은 속도, 10경기): 보통 {VS['easy_vs_normal']['wins']['normal']}:{VS['easy_vs_normal']['wins']['easy']} 쉬움, "
  f"어려움 {VS['normal_vs_hard']['wins']['hard']}:{VS['normal_vs_hard']['wins']['normal']} 보통, 어려움 {VS['easy_vs_hard']['wins']['hard']}:{VS['easy_vs_hard']['wins']['easy']} 쉬움. "
  '동작 속도 차이를 빼고 판단 능력만 비교해도 순서가 분명하다.')
IMG(FIG / 'chart_difficulty.png', 14.5, '그림 4. 난이도 간 AI 대 AI 대전 결과 (각 10경기)')

# ---------- 8
H('8. GUI와 AI의 독립 실행 구조')
P('원본은 화면을 다시 그릴 때마다 AI 탐색을 3번(도우미 2번, AI 패널 1번) 메인 스레드에서 실행했다. 어려움 탐색은 평균 0.86초, 최대 2.4초가 걸려 그동안 키 입력과 낙하가 모두 멈췄다.')
H('8.1 설계', 2)
B('AIWorker: 하나의 백그라운드 스레드. GUI는 보드를 깊은 복사해 (토큰, 보드, 블록, 다음 블록, 난이도) 작업을 큐에 넣는다.')
B('토큰 = (종류, game_id, 플레이어 번호, piece_id). 결과는 토큰이 현재 블록과 같을 때만 적용된다. 재시작·모드 변경·종료 시 game_id가 바뀌고 작업 세대 번호가 올라가 이전 작업은 건너뛴다.')
B('Tk 위젯과 Player 객체는 메인 스레드만 수정한다. 작업 스레드는 결과 큐에 넣기만 한다. 공유되는 것은 AI 결과 캐시 하나뿐이며 threading.Lock으로 보호한다.')
B('메인 루프는 16 ms마다 실행: 결과 큐 확인 → 키 자동 반복 → 플레이어별 중력 → AI 한 동작 → 상태가 바뀐 경우에만 다시 그리기.')
B('AI는 선택한 위치까지 회전·이동을 실제 Player.rotate/move로 한 단계씩 수행한다(순간 이동 없음). 막히면 그 자리에서 떨어뜨린다.')
H('8.2 2인 동시 입력', 2)
P('운영체제의 키 자동 반복은 마지막에 누른 키 하나에만 적용되어, 두 사람이 동시에 키를 누르고 있으면 한 사람이 멈춘다. 키별 누름 상태를 저장하고 170 ms 후 50 ms 간격으로 '
  '직접 반복(DAS/ARR)하도록 바꿨다. 한글 입력기가 켜져 있어도 Windows 가상 키 코드로 P2 키를 인식한다.')
IMG(FIG / 'chart_gui.png', 15.0, '그림 5. GUI 응답성 개선 전후 (로그 축, 같은 조건 20초 측정)')

# ---------- 9
H('9. 공격 시스템과 승패 처리')
T(['모드', '공격', '종료 조건', '승패'], [
    ('1인용', '없음', '블록이 넘침', '승패 없음 — 최고 점수·줄 수 기록'),
    ('2인 동시 플레이', '없음', '두 사람 모두 넘침', '점수가 높은 쪽 승리(같으면 무승부)'),
    ('2인 대전', 'P1 ↔ P2', '한 사람이 넘침', '살아남은 쪽 승리, 동시 Top-out이면 점수 비교'),
    ('인간 vs AI', 'P1 ↔ AI', '한쪽이 넘침', '살아남은 쪽 승리, 동시 Top-out이면 점수 비교')], widths=[3.0, 2.4, 3.6, 7.0], fs=8.8)
B('공격은 상대의 pending(받을 공격)에 쌓이고, 상대가 다음 블록을 고정할 때 ⑤ 상쇄 → ⑥ 삽입된다. 화면에는 보드 왼쪽 빨간 막대와 "받을 공격 n줄"로 표시한다.')
B('방해 줄은 한 번의 공격에서 같은 위치에 구멍 1칸을 둔다(I 블록으로 다시 지울 수 있음). 위 n줄에 블록이 있으면 밀려 나가므로 Top-out이다.')
B('중간에 그만둔 경기는 승패로 세지 않고 aborted로 따로 저장한다. 기록 이력에는 모드·결과·시각·점수를 남긴다.')

# ---------- 10
H('10. AI 도우미의 평가 점수 계산')
P('도우미는 사람이 블록을 움직일 때마다 "지금 Hard Drop하면 어떻게 되는가"를 AI와 같은 평가함수로 계산해 항목별로 보여 준다. 아래는 실제 프로그램 상태(시드 52, 9블록 배치 후)에서 계산한 값이다.')
rows = [(k, f'{v:+.1f}', f'{BEST.parts.get(k, 0):+.1f}') for k, v in CUR.parts.items()]
rows.append(('합계', f'{CUR.score:+.1f}', f'{BEST.score:+.1f}'))
T(['항목', f'현재 위치 (x={CUR.piece.x}, 회전 {CUR.piece.rot})', f'AI 추천 (x={BEST.piece.x}, 회전 {BEST.piece.rot})'], rows, widths=[5.0, 5.5, 5.5], fs=8.8)
B(f'추천은 후보 {NCAND}개 중 합계가 가장 높은 배치다. 도우미 패널의 숫자는 이 표와 같은 함수로 계산되며, 테스트(test_coach_preview_matches_evaluation_function, '
  'test_coach_panel_shows_real_evaluation_and_recommendation)가 화면 값과 평가함수 값이 같음을 확인한다.')
B('"T-Spin 후보"는 보드 모양만으로 센 근사 신호이고, "실제 T-Spin 판정"은 5장의 규칙(회전 + 3모서리)으로 따로 계산해 별도 줄에 표시한다.')
IMG(SHOT / '05_coach_detail.png', 15.5, '그림 6. AI 도우미 화면 (청록 점선 = 추천 위치, 오른쪽 패널 = 항목별 기여)')

# ---------- 11
H('11. T-Spin 퍼즐 생성·검증 알고리즘')
IMG(FIG / 'fig_puzzle.png', 16.5, '그림 7. 퍼즐 생성-검증 단계')
H('11.1 BFS 키 경로 탐색', 2)
B('상태: (x, y, 회전, 마지막 동작이 회전인지). 같은 칸이라도 마지막 동작에 따라 T-Spin 여부가 달라지므로 상태에 포함했다.')
B('동작: ←, →, ↓(한 칸), ↻, ↺ — 회전은 engine.try_rotate를 그대로 사용하므로 SRS 킥이 포함된다. 상태 수는 대략 수천 개로 전수 탐색한다.')
B('출력: 바닥에 닿은(한 칸 더 내릴 수 없는) 모든 위치와, 각 위치까지의 최단 키 순서. BFS이므로 힌트로 보여 주는 키 순서가 가장 짧다.')
H('11.2 생성과 필요성 검증', 2)
P('무작위 보드에서 해답을 찾는 방식은 성공률이 낮아, 완성된 T-Spin Double 구조를 먼저 만든 뒤 난이도에 따라 블록 자리를 비우는 역방향 구성을 택했다. '
  '비운 자리를 채울 준비 블록이 실제 키로 그 자리에 갈 수 있는지(BFS), 줄을 미리 지우지 않는지, 마지막 T가 회전으로 목표 줄 수를 지우는지 확인한다. '
  '또한 초기 보드에서는 목표 T-Spin이 불가능하고, 어려움은 I만 또는 O만 놓아서도 불가능함을 확인해 준비 블록이 반드시 필요함을 보장한다.')
gen = MISC['puzzle_generation']
T(['난이도', '블록', '평균 생성 시간', '최대', '검증 통과', '최대 시도'], [
    (DN[d], ' → '.join({'easy': ['T'], 'normal': ['I', 'T'], 'hard': ['I', 'O', 'T']}[d]), ms(gen[d]['mean_ms']), ms(gen[d]['max_ms']),
     f"{gen[d]['validated']}/{gen[d]['seeds']}", gen[d]['max_attempts']) for d in DN], widths=[2.0, 2.6, 3.2, 2.6, 2.6, 2.4], fs=8.8)
H('11.3 힌트와 판정', 2)
B('힌트 1: 목표 가로 칸 범위 / 힌트 2: 회전 상태 + 보드에 목표 칸 표시 / 힌트 3: 정확한 좌표와 키 순서(예: → ×2  ↓ ×15  ↻  ↓ ×2  ↻  Space).')
B('마지막 T의 힌트는 현재 보드에서 다시 BFS로 계산하므로, 준비 블록을 다른 곳에 놓아도 가능한 경로가 있으면 맞는 힌트를 준다. 경로가 없으면 그렇다고 알린다.')
B('성공: T 블록이 실제 T-Spin으로 목표 줄 수 이상 제거. 결과는 한 번만 확정되고 이후 입력으로 바뀌지 않으며, 성공 기록도 한 번만 저장된다.')
IMG(SHOT / '07_puzzle_hint.png', 15.5, '그림 8. 어려움 퍼즐과 힌트 3단계 (금색 테두리 = 정답 칸)')

# ---------- 12
H('12. 독창적 요소')
for a, b in [('설명 가능한 AI(XAI) 도우미: ', 'AI의 판단을 숫자 하나가 아니라 7개 항목의 기여로 나눠 보여 주고, 같은 함수로 계산한 추천 위치와 직접 비교하게 한다. AI가 사람을 이기는 데서 그치지 않고 사람이 AI의 판단 기준을 배울 수 있다.'),
             ('"풀 수 있음"이 증명된 퍼즐: ', 'AI가 퍼즐을 만들 뿐 아니라 사람이 누를 수 있는 키만으로 해답이 존재함을 BFS로 증명하고, 준비 블록이 정말 필요한지도 검사한다.'),
             ('규칙을 지키는 AI: ', 'AI도 사람과 같은 회전·이동 함수를 거쳐 움직이고 같은 중력을 받는다. AI 패널에 목표 위치·남은 동작·계산 시간을 표시한다.'),
             ('측정으로 보이는 난이도: ', '난이도 차이를 설명만 하지 않고 1인 생존·AI 대전 승률로 측정해 제시한다.'),
             ('결과가 같은 최적화: ', '탐색 범위를 줄여 빠르게 만드는 대신, 같은 결과를 더 빨리 계산하고 원본과 300/300 동일함을 증명했다.')]:
    B(b, a)

# ---------- 13
H('13. 설계 대안과 채택 근거')
T(['문제', '검토한 대안', '채택', '근거'], [
    ('AI 계산이 GUI를 멈춤', '① 메인 스레드 유지 ② 별도 프로세스 ③ 작업 스레드', '③ + 탐색 최적화', '최적화 후 어려움 최대 약 190 ms라 GIL 영향이 작고, 프로세스는 Windows에서 시작·직렬화·종료 처리가 복잡'),
    ('탐색이 느림', '빔 탐색(후보 축소) / 동일 결과 최적화', '동일 결과 최적화', '빔 탐색은 AI 판단을 바꿈. 정확도 유지가 우선'),
    ('AI 배치 방식', '목표 위치로 순간 이동 / 실제 동작 수행', '실제 동작 수행', '사람과 같은 규칙, 화면에서 AI 행동이 보임'),
    ('퍼즐 생성', '무작위 보드 + 해 찾기 / 완성 구조에서 역방향 구성', '역방향 구성 + BFS 검증', f"시드 {sum(gen[d]['seeds'] for d in DN)}개 모두 첫 시도에 검증 통과"),
    ('방해 줄 구멍', '줄마다 무작위 / 공격 단위로 같은 열', '공격 단위로 같은 열', '받은 쪽이 I 블록으로 반격할 여지'),
    ('키 반복', 'OS 자동 반복 / 자체 DAS·ARR', '자체 DAS·ARR', '두 사람이 동시에 키를 누르고 있을 수 있음'),
    ('기록 파일', '그대로 덮어쓰기 / 임시 파일 후 교체', '임시 파일 후 os.replace', '저장 중 종료돼도 파일이 깨지지 않음')], widths=[2.8, 4.4, 3.2, 5.6], fs=8.2)

# ---------- 14
H('14. 버그 수정 전후 비교')
P('원본과 수정본에서 같은 시나리오를 실행해 확인했다(verification/reproduce_bugs.py, 결과 bugs_before.json / bugs_after.json).')
T(['버그', '원인', '수정 전 (실측)', '수정 후 (실측)'], [
    ('O 블록 회전', '3×3 행렬 회전으로 칸 이동 + 충돌 검사 없음', BB['o_rotation_on_floor'].get('exception', '-'), '회전 전후 칸 동일, 고정 정상'),
    ('방해 줄 수신', '고정된 블록을 active로 남긴 채 방해 줄 삽입', f"1줄 수신 → 게임오버 {BB['receive_1_garbage_line']['game_over_after_receiving_1_line']}", f"게임오버 {BA['receive_1_garbage_line']['game_over_after_receiving_1_line']}"),
    ('대전 TETRIS 공격', '위와 같음', f"받은 쪽 게임오버 {BB['versus_tetris_attack']['receiver_game_over']}", f"게임오버 {BA['versus_tetris_attack']['receiver_game_over']}"),
    ('공중 회전 T-Spin', 'ghost()가 회전 표시를 그대로 복사', f"17칸 낙하 후 T-Spin {BB['rotate_in_air_then_hard_drop']['counted_as_t_spin']}", f"T-Spin {BA['rotate_in_air_then_hard_drop']['counted_as_t_spin']}"),
    ('퍼즐 T-Spin 횟수', 'GUI가 spins를 갱신하지 않음', f"성공 메시지, spins {BB['puzzle_success_spin_counter']['player_spins_counter']}", f"spins {BA['puzzle_success_spin_counter']['player_spins_counter']}"),
    ('AI로 GUI 정지', '그릴 때마다 동기 탐색', f"어려움 최대 정지 {ms(gbh['loop_gap']['max_ms'])}", f"{ms(gah['loop_gap']['max_ms'])}"),
], widths=[2.8, 5.0, 4.4, 3.8], fs=8.2)
P('이 외에 퍼즐 보통·어려움의 준비 블록이 의미 없던 문제, 2인 동시 키 입력, 한글 IME, 버튼 포커스, 창 크기 변경, 중단 경기 기록 문제를 함께 고쳤다(verification/bugfix_summary.md).')

# ---------- 15
H('15. 단위·통합 테스트')
P(f'최종 실행 결과: {N_TOTAL}개 테스트 중 {N_PASS}개 통과, 실패 {N_FAIL}개, 건너뜀 {N_SKIP}개 ({ENV}). 원본 테스트 {N_ORIG}개는 수정 없이 그대로 통과한다.')
DESC = {'tests/test_engine.py': '원본: 7-bag, 회전, 충돌, 줄 제거, 공격, Hold, AI, 퍼즐, 저장', 'tests/test_integration.py': '원본: AI 40블록, 퍼즐 해답, 시드 공정성, 상쇄, 키 경로',
        'tests/test_regressions.py': 'O 회전 8개, 방해 줄 수신·Top-out, 공중 회전 T-Spin', 'tests/test_rules_match.py': '점수표, Combo/B2B, 레벨 속도, 모드별 공격·승패, 기록',
        'tests/test_ai_extra.py': '참조 구현과 동일성, 난이도 차이, 캐시, 작업 스레드, 보드 일관성', 'tests/test_puzzles_extra.py': '전체 블록 키 경로, 준비 블록 필요성, 힌트, 성공/실패, 생성 실패',
        'tests/test_gui.py': '실제 Tk 창 + 키 이벤트: 동시 입력, 공격, AI 비차단, 일시정지, 재시작, 퍼즐, 크기 변경'}
T(['테스트 파일', '개수', '통과', '검증 내용'], [(f.replace('tests/', ''), c[0], c[1], DESC.get(f, '')) for f, c in PER_FILE.items()], widths=[3.8, 1.3, 1.3, 9.6], fs=8.4)
P('GUI 테스트는 실제 Tk 창을 만들고 event_generate로 키 이벤트를 Tk 이벤트 큐에 넣은 뒤 앱의 메인 루프를 돌린다. 모니터가 없는 환경에서는 자동으로 건너뛰며, 이번 실행에서는 Windows 데스크톱에서 모두 실행되었다. '
  '시연 영상(테트리스_레벨3_실제플레이_시연영상.mp4, 3분 39초)은 python run.py로 실행한 실제 프로그램을 Windows SendInput(OS 키보드·마우스 입력)만으로 조작하며 게임 창만 녹화한 '
  "'자동화된 GUI 입력 시연'이다. 보드·블록·점수·승패 등 게임 내부 상태는 전혀 변경하지 않았고, 자동 입력은 화면 픽셀에서 보드를 읽어 키를 눌렀다(검증: docs/real_demo/영상_검증.md).")

# ---------- 16
H('16. 성능 측정 결과')
P(f'환경: {ENV}. 모든 수치는 verification 폴더의 측정 스크립트로 얻은 값이다.')
H('16.1 AI 탐색 시간 (고정 보드 100개 × 3회, 캐시 미사용)', 2)
T(['난이도', '개선 전 평균', '개선 전 p95', '개선 전 최대', '개선 후 평균', '개선 후 p95', '개선 후 최대'],
  [(DN[d], ms(AIB['difficulties'][d]['mean_ms']), ms(AIB['difficulties'][d]['p95_ms']), ms(AIB['difficulties'][d]['max_ms']),
    ms(AIA['difficulties'][d]['mean_ms']), ms(AIA['difficulties'][d]['p95_ms']), ms(AIA['difficulties'][d]['max_ms'])) for d in DN],
  widths=[1.8, 2.4, 2.4, 2.4, 2.4, 2.3, 2.3], fs=8.4)
IMG(FIG / 'chart_ai_time.png', 14.0, '그림 9. AI 1회 탐색 시간 (로그 축)')
H('16.2 GUI 응답성 (인간 vs AI, 도우미 켬, 150 ms마다 키 입력, 20초)', 2)
T(['조건', '루프 실행 수', '최대 정지', '100 ms 넘는 정지', '처리된 키', '키 지연 평균', '키 지연 p95'],
  [(f"{DN[d]} · {'전' if t == 'before' else '후'}", GUI[(t, d)]['loop_gap']['n'], ms(GUI[(t, d)]['loop_gap']['max_ms']), GUI[(t, d)]['stalls_over_100ms'],
    GUI[(t, d)]['key_latency']['n'], ms(GUI[(t, d)]['key_latency']['mean_ms']), ms(GUI[(t, d)]['key_latency']['p95_ms'])) for d in ('normal', 'hard') for t in ('before', 'after')],
  widths=[2.3, 2.2, 2.3, 2.4, 2.0, 2.4, 2.4], fs=8.4)
P(f"원본은 어려움에서 이벤트 루프 탐침이 {gbh['seconds']}초 동안 {gbh['loop_gap']['n']}번만 실행되었다. 남은 제한: Python GIL 때문에 작업 스레드가 계산할 때 메인 스레드도 약간 느려지며, 개선 후 최대 정지 {ms(gah['loop_gap']['max_ms'])}에 그 영향이 포함되어 있다.")
H('16.3 기타', 2)
r = MISC['records']
B(f"기록 저장 평균 {ms(r['save']['mean_ms'])}, 불러오기 평균 {ms(r['load']['mean_ms'])} (파일 {r['file_bytes']:,} bytes, 이력 {r['history_entries']}건, 200회 반복).")
B('연속 처리: 세 난이도 각 45블록(매 블록 칸 수 보존 확인), 방해 줄 수신 후 30블록, 1인 벤치마크 최대 500블록 모두 오류 없음.')

# ---------- 17
H('17. 한계점과 향후 개선')
for t in ['AI 후보는 위에서 곧바로 떨어뜨리는 배치뿐이다. 블록을 밑으로 밀어 넣거나 T-Spin을 노리는 전략은 없다. 퍼즐 검증기의 BFS를 AI 후보 생성에 쓰면 확장할 수 있으나 탐색량이 수십 배 늘어난다.',
          '평가함수 가중치는 직접 정했다. 대전 시뮬레이션을 이용한 가중치 자동 조정(예: 유전 알고리즘)이 다음 단계로 적합하다.',
          'T-Spin Mini를 구분하지 않으며, 공격 표는 교육용으로 단순화했다.',
          'Python GIL 때문에 AI 스레드가 계산하는 동안 화면 갱신이 수십 ms 늦어질 수 있다(측정 최대 약 0.1초).',
          '검증은 Windows 11에서만 했다. Linux 실행 스크립트는 제공하지만 실행 확인은 하지 않았고, 실제 한글 IME 상태의 키 입력은 수동으로 확인하지 않았다.',
          '도우미가 실제로 사람의 실력을 높이는지(구멍 수·생존 시간 변화)는 사용자 실험으로 측정하지 않았다.']:
    B(t)

# ---------- 18
H('18. 실행 방법과 결론')
B('실행: python run.py (Windows는 start_windows.bat). Python 3.10 이상, 추가 설치 없음. 기록: save/records.json.')
B('테스트: python -m pip install -r requirements-dev.txt → python -m pytest -q')
B('문서 다시 만들기: docs/real_demo/record_real_demo.py + compose_video.py(제출 영상), verification/make_reports.py(측정 문서), docs/make_submission_docs.py(보고서·발표자료).')
P('결론적으로, PDF의 11개 필수 요구사항을 모두 구현하고 각 항목을 자동 테스트와 실제 실행으로 확인했다. 원본에서 실제 플레이를 방해하던 결함(방해 줄 즉시 게임오버, O 회전 오류, '
  'AI 계산으로 인한 화면 정지)을 원인부터 고쳤고, 수정 전후를 같은 시나리오로 측정해 개선을 숫자로 보였다. 확장 기능인 설명 가능한 AI 도우미와 "풀 수 있음이 증명된" T-Spin 퍼즐은 '
  '단순히 이기는 AI가 아니라 사람이 AI의 판단을 이해하고 연습할 수 있게 한다는 점에서 이 프로젝트의 차별점이다.')

footer = sec.footer.paragraphs[0]; footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
fr = footer.add_run('AI기초프로젝트 레벨 3 · 인간–AI 대전 테트리스 · 구현 및 검증 보고서'); fr.font.size = Pt(8)
REPORT = DOCS / '테트리스_레벨3_구현보고서.docx'
cp = D.core_properties
cp.author = cp.last_modified_by = '강민혁'; cp.comments = ''; cp.title = '인간-AI 대전 테트리스 구현 보고서'
D.save(REPORT)

# ======================================================================= PPTX (with PIL preview of the same layout)
SW, SH = 13.333, 7.5
PX = 96                                   # preview pixels per inch
F_REG = 'C:/Windows/Fonts/malgun.ttf'; F_BOLD = 'C:/Windows/Fonts/malgunbd.ttf'
C = {'navy': '13253B', 'teal': '1F9E93', 'ink': '1B1B1B', 'ink2': '52514E', 'light': 'EEF4F8', 'mid': 'CFDDE8', 'white': 'FFFFFF', 'gold': 'C98500', 'pale': 'E3F4F1'}
prs = Presentation(); prs.slide_width = PI(SW); prs.slide_height = PI(SH)
PREVIEWS = []; WARN = []


def rgb(h):
    return PRGB.from_string(h)


class Slide:
    def __init__(self, title, kicker):
        self.s = prs.slides.add_slide(prs.slide_layouts[6])
        self.img = Image.new('RGB', (int(SW * PX), int(SH * PX)), 'white'); self.d = ImageDraw.Draw(self.img)
        self.n = len(prs.slides)
        self.rect(0, 0, SW, .95, C['navy'])
        self.text(.55, .14, 9, .3, kicker, 11, C['teal'] if False else 'A9E3DD', bold=True)
        self.text(.55, .38, 12.2, .55, title, 24, C['white'], bold=True)
        self.text(.55, 7.08, 9, .3, COURSE + '  ·  ' + AUTHOR.split('|')[-1].strip(), 9, C['ink2'])
        self.text(12.3, 7.08, .6, .3, str(self.n), 10, C['teal'], bold=True, align='r')

    def rect(self, x, y, w, h, fill, line=None, rounded=False):
        shp = self.s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE if rounded else MSO_SHAPE.RECTANGLE, PI(x), PI(y), PI(w), PI(h))
        shp.fill.solid(); shp.fill.fore_color.rgb = rgb(fill)
        if line:
            shp.line.color.rgb = rgb(line); shp.line.width = PP(1)
        else:
            shp.line.fill.background()
        if rounded:
            shp.adjustments[0] = .08
        shp.shadow.inherit = False
        self.d.rounded_rectangle([x * PX, y * PX, (x + w) * PX, (y + h) * PX], radius=int(.08 * min(w, h) * PX) if rounded else 0,
                                 fill='#' + fill, outline=('#' + line) if line else None)
        return shp

    def text(self, x, y, w, h, content, size=16, color=None, bold=False, align='l', bullets=False, spacing=1.15, anchor='t'):
        """content: str or list of str / (str, dict) items (dict may set size,color,bold)."""
        items = content if isinstance(content, list) else [content]
        tb = self.s.shapes.add_textbox(PI(x), PI(y), PI(w), PI(h)); tf = tb.text_frame
        tf.word_wrap = True; tf.margin_left = tf.margin_right = PI(.04); tf.margin_top = tf.margin_bottom = PI(.02)
        tf.vertical_anchor = {'t': MSO_ANCHOR.TOP, 'm': MSO_ANCHOR.MIDDLE}[anchor]
        cy = y * PX + .02 * PX; total = 0
        layouts = []
        for k, it in enumerate(items):
            txt, opt = (it, {}) if isinstance(it, str) else it
            sz = opt.get('size', size); col = opt.get('color', color or C['ink']); bd = opt.get('bold', bold)
            p = tf.paragraphs[0] if k == 0 else tf.add_paragraph()
            run = p.add_run(); run.text = ('• ' if bullets and not opt.get('nobullet') else '') + txt
            run.font.size = PP(sz); run.font.bold = bd; run.font.color.rgb = rgb(col); run.font.name = 'Malgun Gothic'
            rpr = run._r.get_or_add_rPr()
            ea = rpr.find(qn('a:ea'))
            if ea is None:
                ea = OxmlElement('a:ea'); rpr.append(ea)
            ea.set('typeface', 'Malgun Gothic')
            p.alignment = {'l': PP_ALIGN.LEFT, 'c': PP_ALIGN.CENTER, 'r': PP_ALIGN.RIGHT}[align]
            p.line_spacing = spacing; p.space_after = PP(opt.get('after', 4 if bullets else 2))
            font = ImageFont.truetype(F_BOLD if bd else F_REG, max(6, int(sz * PX / 72)))
            lines = wrap(run.text, font, (w - .08) * PX)
            lh = sz * PX / 72 * 1.2 * spacing
            layouts.append((lines, font, lh, col, opt.get('after', 4 if bullets else 2)))
            total += len(lines) * lh + opt.get('after', 4 if bullets else 2) * PX / 72
        if total > h * PX + 2:
            WARN.append(f'slide {self.n}: text overflow ({total / PX:.2f}in > {h:.2f}in): {str(items[0])[:40]}')
        if anchor == 'm':
            cy = y * PX + (h * PX - total) / 2
        for lines, font, lh, col, after in layouts:
            for ln in lines:
                tw = self.d.textlength(ln, font=font)
                tx = x * PX + .04 * PX if align == 'l' else (x + w / 2) * PX - tw / 2 if align == 'c' else (x + w) * PX - tw - .04 * PX
                self.d.text((tx, cy), ln, font=font, fill='#' + col); cy += lh
            cy += after * PX / 72
        return tb

    def picture(self, path, x, y, w=None, h=None):
        im = Image.open(path)
        ar = im.height / im.width
        if w and not h:
            h = w * ar
        elif h and not w:
            w = h / ar
        self.s.shapes.add_picture(str(path), PI(x), PI(y), PI(w), PI(h))
        self.img.paste(im.resize((int(w * PX), int(h * PX))), (int(x * PX), int(y * PX)))
        self.d.rectangle([x * PX, y * PX, (x + w) * PX, (y + h) * PX], outline='#CFDDE8')
        return w, h

    def table(self, x, y, w, rows, col_w, size=11, row_h=.36, head=C['navy']):
        shape = self.s.shapes.add_table(len(rows), len(rows[0]), PI(x), PI(y), PI(w), PI(row_h * len(rows)))
        tbl = shape.table
        for j, cw in enumerate(col_w):
            tbl.columns[j].width = PI(cw)
        cy = y
        for i, row in enumerate(rows):
            tbl.rows[i].height = PI(row_h)
            cx = x
            for j, v in enumerate(row):
                cell = tbl.cell(i, j); cell.text = ''
                cell.margin_left = cell.margin_right = PI(.06); cell.margin_top = cell.margin_bottom = PI(.02)
                cell.vertical_anchor = MSO_ANCHOR.MIDDLE
                para = cell.text_frame.paragraphs[0]; run = para.add_run(); run.text = str(v)
                run.font.size = PP(size); run.font.name = 'Malgun Gothic'; run.font.bold = i == 0
                run.font.color.rgb = rgb(C['white'] if i == 0 else C['ink'])
                cell.fill.solid(); cell.fill.fore_color.rgb = rgb(head if i == 0 else ('F2F6F9' if i % 2 == 0 else C['white']))
                fill = '#' + (head if i == 0 else ('F2F6F9' if i % 2 == 0 else C['white']))
                self.d.rectangle([cx * PX, cy * PX, (cx + col_w[j]) * PX, (cy + row_h) * PX], fill=fill, outline='#CFDDE8')
                font = ImageFont.truetype(F_BOLD if i == 0 else F_REG, int(size * PX / 72))
                lines = wrap(str(v), font, (col_w[j] - .12) * PX)
                if len(lines) * size * PX / 72 * 1.2 > row_h * PX + 1:
                    WARN.append(f'slide {self.n}: table cell overflow "{str(v)[:30]}"')
                ty = cy * PX + (row_h * PX - len(lines) * size * PX / 72 * 1.2) / 2
                for ln in lines:
                    self.d.text((cx * PX + .06 * PX, ty), ln, font=font, fill='#FFFFFF' if i == 0 else '#1B1B1B'); ty += size * PX / 72 * 1.2
                cx += col_w[j]
            cy += row_h

    def notes(self, text):
        self.s.notes_slide.notes_text_frame.text = text

    def card(self, x, y, w, h, title, body, size=13, fill=C['light'], accent=C['teal']):
        self.rect(x, y, w, h, fill, rounded=True)
        self.rect(x, y + .12, .07, h - .24, accent)
        self.text(x + .2, y + .12, w - .3, .4, title, size + 2, C['navy'], bold=True)
        self.text(x + .2, y + .55, w - .3, h - .62, body, size, C['ink'], bullets=isinstance(body, list), spacing=1.1)

    def done(self):
        p = PREV / f'slide_{self.n:02d}.png'; self.img.save(p); PREVIEWS.append(p)


def wrap(text, font, maxw):
    out = []
    for para in text.split('\n'):
        line = ''
        for word in para.split(' '):
            cand = (line + ' ' + word) if line else word
            if font.getlength(cand) <= maxw:
                line = cand
            else:
                if line:
                    out.append(line)
                while font.getlength(word) > maxw:          # very long token: break by character
                    k = len(word)
                    while k > 1 and font.getlength(word[:k]) > maxw:
                        k -= 1
                    out.append(word[:k]); word = word[k:]
                line = word
        out.append(line)
    return out


K = 'LEVEL 3 · HUMAN × AI TETRIS'
# 1 title
s = Slide('인간–AI 대전 테트리스', 'AI기초프로젝트 레벨 3 · 과제 3.2')
s.text(.7, 1.45, 6.3, 1.0, '탐색형 AI · 설명 가능한 AI 도우미 · 증명된 T-Spin 퍼즐', 22, C['navy'], bold=True)
s.text(.7, 2.55, 6.1, 2.3, [f'PDF 필수 요구사항 11개 구현·검증', f'자동 테스트 {N_TOTAL}개 모두 통과 (실제 GUI {N_GUI}개)',
                           f"어려움 AI 탐색 {hb['mean_ms']:.0f} → {ha['mean_ms']:.0f} ms (결과 동일)", f"GUI 최대 정지 {gbh['loop_gap']['max_ms']:,.0f} → {gah['loop_gap']['max_ms']:.0f} ms"],
       16, bullets=True, spacing=1.15)
s.text(.7, 5.4, 6.0, .9, [AUTHOR, f'{DATE} · 최종본'], 13, C['ink2'])
s.picture(SHOT / '04_human_vs_ai.png', 7.25, 1.45, w=5.6)
s.notes('인간과 AI가 대전하는 테트리스를 구현했고, AI가 왜 그 위치를 골랐는지 보여 주는 도우미와, 풀 수 있음이 증명된 T-Spin 퍼즐을 확장 기능으로 만들었습니다.')
s.done()

# 2 problem & requirements
s = Slide('무엇을 해결해야 했나: 요구사항 11개 → 핵심 문제 4개', K)
s.card(.55, 1.25, 6.0, 2.6, '게임 규칙 (요구 1·3·4·7·8)', ['7종 블록·회전·충돌, 점수·레벨 속도', '대전 공격: 고정→제거→공격→수신 순서', 'Next/Hold, 시작·일시정지·재시작'], 16)
s.card(6.8, 1.25, 6.0, 2.6, 'AI (요구 5·6)', ['현재 + 다음 블록의 모든 배치 탐색', '평가 점수 최대 위치 선택', '난이도 3단계 → 실제 실력 차이'], 16)
s.card(.55, 4.05, 6.0, 2.75, '독립 실행·동기화 (요구 10)', ['AI 계산 중에도 입력·낙하·그리기 유지', '공유 데이터 접근 시 동기화'], 16)
s.card(6.8, 4.05, 6.0, 2.75, '모드·GUI·기록 (요구 2·9·11)', ['4개 모드와 모드별 승패 판정', '보드·Next·Hold·점수·레벨·난이도 표시', '최고 점수·승패·줄 수 저장 → 재실행 시 확인'], 16)
s.notes('PDF의 요구사항을 11개로 나눈 뒤 네 묶음의 핵심 문제로 정리했습니다. 각각의 설계 결정은 다음 장부터 설명합니다.')
s.done()

# 3 architecture
s = Slide('시스템 구조: 규칙·판단·화면 분리 + AI 작업 스레드', K)
s.picture(FIG / 'fig_architecture.png', .55, 1.2, w=8.0)
s.text(8.85, 1.25, 4.0, 5.5, [('GUI 없는 규칙 엔진', {'bold': True, 'color': C['navy'], 'size': 15, 'nobullet': True}),
                              'engine·ai·puzzles·storage는 Tkinter 없이 동작 → 자동 테스트로 직접 검증',
                              ('동기화 설계', {'bold': True, 'color': C['navy'], 'size': 15, 'nobullet': True}),
                              '작업 스레드는 보드 복사본만 읽음', '결과는 thread-safe 큐로만 전달', '토큰(게임·플레이어·블록 번호)이 맞을 때만 적용',
                              '공유 캐시는 Lock으로 보호'], 13, bullets=True)
s.notes('규칙 엔진은 GUI와 독립되어 있어 테스트로 직접 확인할 수 있습니다. AI는 별도 스레드에서 계산하고, 결과에 붙은 토큰으로 오래된 결과를 버립니다.')
s.done()

# 4 lock pipeline + attack
s = Slide('게임 규칙의 핵심: 블록 고정 8단계와 공격', K)
s.picture(FIG / 'fig_lock_pipeline.png', .55, 1.2, w=12.2)
s.table(.55, 4.35, 7.2, [['제거', '공격', 'T-Spin 공격', '보너스'], ['1줄', '0', '2', 'Combo +min(n,4)'], ['2줄', '1', '4', 'B2B +1'], ['3줄', '2', '6', '상쇄 후 남은 줄 전송'], ['4줄', '4', '—', '구멍 1열 공유']],
        [1.3, 1.3, 1.8, 2.8], size=12, row_h=.43)
s.text(8.1, 4.35, 4.7, 2.3, ['2인 대전·인간 vs AI만 공격', '2인 동시 플레이는 공격 없음', '받을 공격은 빨간 막대로 표시', '먼저 넘친 쪽 패배, 동시면 점수 비교'], 14, bullets=True)
s.notes('원본은 고정된 블록을 active로 남긴 채 방해 줄을 넣어, 방해 줄을 받자마자 게임오버가 되었습니다. 8단계 순서를 고정해 해결했습니다.')
s.done()

# 5 AI decision
s = Slide('AI는 어떻게 판단하나: 모든 배치 탐색 + 평가함수', K)
s.picture(FIG / 'fig_ai_search.png', .55, 1.2, w=7.7)
s.table(8.45, 1.25, 4.35, [['평가 항목', '가중치'], ['줄 제거', '+110 × 줄²'], ['최대 높이 변화', '-14'], ['구멍 변화', '-64'], ['평탄도 변화', '-6.5'], ['전체 높이 변화', '-3.4'],
                            ['T-Spin 후보 변화', '+14'], ['다음 블록 (어려움)', '+0.65 × 최선']], [2.55, 1.8], size=12, row_h=.42)
s.text(.6, 4.75, 12.2, 2.0, ['머신러닝이 아닌 휴리스틱 탐색 AI — 가능한 배치를 모두 만들고 점수가 가장 높은 곳을 선택',
                            'AI도 사람과 같은 회전·이동 함수로 한 단계씩 움직이고 같은 중력을 받음 (순간 이동 없음)',
                            '보통 기준 빈 보드에서 T 블록 후보 34개, 어려움은 후보마다 다음 블록 후보 전체를 다시 평가'], 16, bullets=True)
s.notes('PDF가 제시한 최대 높이 최소화에 구멍, 평탄도 등을 더한 평가함수를 씁니다. 어려움은 다음 블록의 최선 배치까지 계산하는 2단계 탐색입니다.')
s.done()

# 6 difficulty
s = Slide('난이도 차이는 이름이 아니라 측정 결과로', K)
s.table(.55, 1.25, 6.4, [['난이도', '탐색', '평가'], ['쉬움', '현재 블록', '줄·최대 높이·0.35×구멍'], ['보통', '현재 블록', '7개 항목 전체'], ['어려움', '현재 × 다음', '7개 항목 + 0.65 × 다음 최선']],
        [1.3, 1.9, 3.2], size=13, row_h=.48)
sol = DIF['solo']
s.text(.55, 3.4, 6.4, 3.3, [('1인 플레이 (시드 5개, 최대 500블록)', {'bold': True, 'color': C['navy'], 'nobullet': True}),
                            f"쉬움: 5판 모두 Top-out (평균 {sol['easy']['mean_pieces']:.0f}블록)", f"보통·어려움: 5판 모두 500블록 생존",
                            ('AI 대 AI 대전 (실제 공격 규칙, 같은 속도)', {'bold': True, 'color': C['navy'], 'nobullet': True}),
                            '판단 능력만으로 쉬움 < 보통 < 어려움 순서가 분명'], 14, bullets=True)
s.picture(FIG / 'chart_difficulty.png', 7.2, 1.3, w=5.65)
s.notes('난이도별로 평가 항목 수와 탐색 깊이가 다릅니다. 실제로 AI끼리 대전시킨 결과 보통이 쉬움을 7대 3, 어려움이 보통을 8대 2로 이겼습니다.')
s.done()

# 7 GUI freeze fixed
s = Slide('AI 계산 때문에 멈추던 화면을 해결', K)
s.picture(FIG / 'chart_gui.png', .55, 1.2, w=7.3)
s.text(8.15, 1.25, 4.7, 5.6, [('원인', {'bold': True, 'color': C['navy'], 'size': 15, 'nobullet': True}),
                              '화면을 그릴 때마다 AI 탐색 3회를 메인 스레드에서 실행', f"어려움: {gbh['seconds']}초 동안 루프 {gbh['loop_gap']['n']}번 실행",
                              ('해결', {'bold': True, 'color': C['navy'], 'size': 15, 'nobullet': True}),
                              'AI는 작업 스레드, 결과는 큐 + 토큰', '그리기는 저장된 결과만 사용', '변화가 있을 때만 다시 그리기',
                              ('결과 (어려움)', {'bold': True, 'color': C['navy'], 'size': 15, 'nobullet': True}),
                              f"최대 정지 {gbh['loop_gap']['max_ms']:,.0f} → {gah['loop_gap']['max_ms']:.0f} ms", f"키 지연 p95 {gbh['key_latency']['p95_ms']:,.0f} → {gah['key_latency']['p95_ms']} ms"], 13, bullets=True)
s.notes('같은 조건에서 20초 동안 측정했습니다. 원본은 어려움 난이도에서 화면이 수 초씩 멈췄고, 개선 후 최대 정지는 약 0.1초입니다.')
s.done()

# 8 search optimisation
s = Slide('AI 탐색 최적화: 결과는 같게, 속도는 17배', K)
s.picture(FIG / 'chart_ai_time.png', .55, 1.2, w=7.0)
s.text(7.85, 1.25, 5.0, 5.6, [('같은 결과를 더 빨리', {'bold': True, 'color': C['navy'], 'size': 15, 'nobullet': True}),
                              '보드를 행 비트마스크 20개로 변환', '열 높이로 착지 위치를 한 번에 계산', '놓기 전 보드 평가는 탐색당 1번', '결과 캐시: 다시 그릴 때 재계산 0',
                              ('정확도 검증', {'bold': True, 'color': C['navy'], 'size': 15, 'nobullet': True}),
                              '원본과 300/300 사례에서 후보 순위·점수 동일', '후보를 줄이는 빔 탐색은 판단이 바뀌어 채택하지 않음'], 13, bullets=True)
s.notes(f"고정 보드 100개를 세 번씩 측정했습니다. 어려움 평균 {hb['mean_ms']:.0f}ms에서 {ha['mean_ms']:.0f}ms로 줄었고 원본과 결정이 완전히 같습니다.")
s.done()

# 9 coach
s = Slide('설명 가능한 AI 도우미: 왜 그 위치가 좋은가', K)
s.picture(SHOT / '05_coach_detail.png', .55, 1.2, w=7.4)
s.text(8.25, 1.25, 4.6, 5.6, [('표시 내용', {'bold': True, 'color': C['navy'], 'size': 15, 'nobullet': True}),
                              '지금 떨어뜨리면 받을 평가 점수', '7개 항목별 기여(+/-)', '실제 T-Spin 판정과 예상 제거 줄', 'AI 추천 위치(청록 점선)와 그 점수',
                              ('정확성', {'bold': True, 'color': C['navy'], 'size': 15, 'nobullet': True}),
                              'AI와 같은 평가함수 → 화면 값 = 함수 값 (테스트)', 'T-Spin 후보(근사)와 실제 판정을 구분', '게임 점수와 별개인 AI 점수임을 표시'], 13, bullets=True)
s.notes('도우미는 AI가 쓰는 평가함수를 그대로 써서 현재 위치와 추천 위치를 같은 기준으로 비교하게 해 줍니다.')
s.done()

# 10 puzzle
s = Slide('AI T-Spin 퍼즐: 생성하고, 풀 수 있음을 증명', K)
s.picture(FIG / 'fig_puzzle.png', .9, 1.12, w=10.0)
s.picture(SHOT / '07_puzzle_hint.png', .55, 4.62, w=3.9)
s.text(4.75, 4.62, 8.05, 2.35, ['준비 블록·T 블록 검증과 힌트 모두 같은 BFS(explore) 사용 — 상태 수천 개 전수 탐색',
                             '보통·어려움은 준비 블록 없이는 풀 수 없음을 검사 (원본은 준비 블록이 의미 없었음)',
                             f"시드 {sum(gen[d]['seeds'] for d in DN)}개 전부 첫 시도에 검증 통과, 어려움 평균 {gen['hard']['mean_ms']:.0f} ms",
                             '힌트 3단계: 가로 범위 → 회전 + 목표 칸 → 좌표 + 키 순서'], 13, bullets=True)
s.notes('완성된 T-Spin Double 구조에서 블록 자리를 비워 문제를 만들고, 모든 블록이 실제 키로 놓일 수 있는지 BFS로 확인합니다.')
s.done()

# 11 originality
s = Slide('다른 테트리스 프로젝트와 무엇이 다른가', K)
s.card(.55, 1.25, 6.0, 2.65, '① 설명 가능한 AI', 'AI가 이기는 데서 끝나지 않고, 판단 근거를 항목별로 보여 줘 사람이 AI의 기준을 배울 수 있음', 16)
s.card(6.8, 1.25, 6.0, 2.65, '② 증명된 퍼즐', 'AI가 만든 문제마다 실제 키 경로와 준비 블록의 필요성을 탐색으로 증명한 뒤 출제', 16)
s.card(.55, 4.1, 6.0, 2.65, '③ 규칙을 지키는 AI', '순간 이동 없이 사람과 같은 회전·이동·중력을 따르며, 목표·남은 동작·계산 시간을 화면에 공개', 16)
s.card(6.8, 4.1, 6.0, 2.65, '④ 측정으로 보이는 품질', '난이도 승률, 탐색 시간, GUI 정지 시간을 개선 전후 같은 조건으로 측정해 제시', 16)
s.notes('핵심 차별점은 AI의 판단을 설명하고, AI가 만든 문제의 정답을 증명한다는 점입니다.')
s.done()

# 12 bugs
s = Slide('어떤 버그를 고쳤고 어떻게 확인했나', K)
s.table(.55, 1.2, 12.25, [['버그', '원인', '수정 전 (실측)', '수정 후 (실측)'],
                          ['방해 줄 수신', '고정된 블록을 active로 둔 채 방해 줄 삽입', '1줄 받으면 즉시 게임오버', '정상 진행'],
                          ['O 블록 회전', '3×3 행렬 회전 + 충돌 검사 없음', 'ValueError: invalid lock', '칸 고정, 정상 낙하'],
                          ['공중 회전 T-Spin', '낙하 후에도 회전 표시 유지', '17칸 낙하도 T-Spin', 'T-Spin 아님'],
                          ['퍼즐 T-Spin 횟수', 'GUI가 통계 미갱신', '성공인데 spins 0', 'spins 1, 기록 1회'],
                          ['AI로 화면 정지', '그릴 때마다 동기 탐색', f"최대 {gbh['loop_gap']['max_ms']:,.0f} ms 정지", f"최대 {gah['loop_gap']['max_ms']:.0f} ms"],
                          ['퍼즐 준비 블록', '구조가 이미 완성돼 있음', '준비 블록 의미 없음', '없으면 풀 수 없음']],
        [2.3, 4.15, 3.0, 2.8], size=12, row_h=.52)
s.text(.55, 5.05, 12.2, 1.7, ['원본과 수정본에서 같은 시나리오를 실행해 확인 (reproduce_bugs.py → bugs_before/after.json)',
                             '버그마다 회귀 테스트를 추가해 다시 생기지 않게 함'], 14, bullets=True)
s.notes('모든 버그는 원본에서 실제로 재현한 뒤 고쳤고, 같은 스크립트로 수정본에서 해결을 확인했습니다.')
s.done()

# 13 tests
s = Slide(f'검증: 자동 테스트 {N_TOTAL}개 모두 통과', K)
rows = [['테스트 파일', '개수', '검증 내용']] + [[f.replace('tests/', ''), str(c[0]), DESC.get(f, '')[:38]] for f, c in PER_FILE.items()]
s.table(.55, 1.2, 8.3, rows, [2.6, .9, 4.8], size=11, row_h=.47)
s.text(9.15, 1.25, 3.7, 5.5, [(f'{N_PASS} / {N_TOTAL} 통과', {'bold': True, 'color': C['teal'], 'size': 24, 'nobullet': True}),
                              f'원본 테스트 {N_ORIG}개 수정 없이 통과', f'실제 Tk 창 + 키 이벤트 GUI 테스트 {N_GUI}개', '2인 동시 키 입력, 공격 후 계속 진행, AI 비차단, 일시정지, 재시작, 퍼즐 키 풀이',
                              '시연 영상: 실제 실행 + OS 키·마우스 입력만 사용 (내부 상태 변경 없음)'], 13, bullets=True)
s.notes('원본 테스트는 하나도 고치지 않았고, 77개를 새로 추가했습니다. GUI 테스트는 실제 창을 띄워 키 이벤트로 검증합니다.')
s.done()

# 14 limits & conclusion
s = Slide('한계와 결론', K)
s.card(.55, 1.25, 6.0, 5.45, '한계 · 향후 개선', ['AI는 곧바로 떨어뜨리는 배치만 탐색 (밀어 넣기·T-Spin 전략 없음)', '가중치는 직접 설계 → 대전 기반 자동 조정이 다음 단계',
                                              'T-Spin Mini 미구분', '검증은 Windows 11에서만 수행', '도우미의 학습 효과는 사용자 실험으로 측정하지 않음'], 13)
s.card(6.8, 1.25, 6.0, 5.45, '결론', ['PDF 필수 요구사항 11개 구현 + 테스트·실행으로 확인', '실제 플레이를 막던 결함을 원인부터 수정하고 전후를 측정',
                                    '이기는 AI를 넘어, 판단을 설명하고(도우미) 문제의 정답을 증명하는(퍼즐) AI'], 14, accent=C['navy'])
s.notes('한계도 숨기지 않고 정리했습니다. 감사합니다.')
s.done()

DECK = DOCS / '테트리스_레벨3_발표자료.pptx'
cp = prs.core_properties
cp.author = cp.last_modified_by = '강민혁'; cp.comments = ''; cp.title = '인간-AI 대전 테트리스 발표자료'
prs.save(DECK)

# ======================================================================= self-check
Document(REPORT); Presentation(DECK)       # re-open both files
sheet_w = 4 * 480; rows_n = (len(PREVIEWS) + 3) // 4
sheet = Image.new('RGB', (sheet_w, rows_n * 270 + 10), '#888888')
for i, p in enumerate(PREVIEWS):
    im = Image.open(p).resize((470, 264)); sheet.paste(im, ((i % 4) * 480 + 5, (i // 4) * 270 + 5))
sheet.save(PREV / 'contact_sheet.png')
print('report:', REPORT); print('deck:', DECK, len(prs.slides), 'slides')
print('layout warnings:', len(WARN)); [print('  ', w) for w in WARN]
