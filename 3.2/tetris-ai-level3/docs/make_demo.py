"""Record the demonstration video from the REAL running program (not used by the game itself).

  python docs/make_demo.py            (Windows desktop; needs Pillow + imageio-ffmpeg)

How it works
  * the real GameApp runs in its normal Tk main loop;
  * every human action is a key event delivered to the app's own key handler (GameApp.key_down /
    key_up -- the handler bound to the keyboard), so focus is never stolen from other programs
    (the Tk event-queue path itself is covered by tests/test_gui.py);
  * the "virtual player" decides which keys to press with the program's own public functions
    (AI coach recommendation, puzzle BFS), re-planned from the current piece before every key;
  * the program's OWN windows are captured with the Win32 PrintWindow API (tools/wincapture.py),
    never the screen, so other windows/desktop content can never appear in the video;
    frames are encoded as H.264 at 10 fps in real time;
  * the caption band under each frame names the scene. Scenes that start from a prepared board
    (Tetris-ready well, T-Spin slot) say so in the caption.
Screenshots for the report are written to docs/screens/.
"""
import ctypes
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
try:
    ctypes.windll.user32.SetProcessDPIAware()          # physical pixels == Tk pixels
except Exception:
    pass
import tkinter as tk
from types import SimpleNamespace
from PIL import Image, ImageDraw, ImageFont, ImageStat
sys.path.insert(0, str(ROOT / 'tools'))
from wincapture import grab, toplevel_hwnd, is_minimized
import imageio_ffmpeg
from tetris.gui import GameApp
from tetris.engine import Piece, W, H
from tetris.ai import plan_actions
from tetris.puzzles import generate, solve_spin_actions, reachable_placements

OUT = ROOT / 'docs' / '자동시연영상.mp4'
SHOTS = ROOT / 'docs' / 'screens'; SHOTS.mkdir(parents=True, exist_ok=True)
SAVE = ROOT / 'docs' / '_demo_records.json'
FPS = 10
OUT_W = 1280
FONT = ImageFont.truetype('C:/Windows/Fonts/malgunbd.ttf', 22)
FONT_S = ImageFont.truetype('C:/Windows/Fonts/malgun.ttf', 16)
P1 = {'cw': 'Up', 'ccw': 'z', 'left': 'Left', 'right': 'Right', 'down': 'Down', 'hard': 'space', 'hold': 'c'}
P2 = {'cw': 'w', 'ccw': 'e', 'left': 'a', 'right': 'd', 'down': 's', 'hard': 'f', 'hold': 'q'}

if SAVE.exists():
    SAVE.unlink()
root = tk.Tk()
app = GameApp(root, save_path=SAVE)
root.geometry('1440x860+20+10')
root.update()
HWND = toplevel_hwnd(root)
caption = {'title': '', 'sub': ''}
stop = threading.Event()
extra_windows = []        # (tk toplevel) program-owned popups composited into the frame
latest = {'img': None}


def capture_program():
    """Main-thread capture of the program's own windows only (PrintWindow), composited."""
    if is_minimized(HWND):
        root.deiconify()                     # the recording needs the window rendered
        return
    img = grab(HWND)
    if img is None or ImageStat.Stat(img.resize((64, 40))).mean[0] > 150:   # failed render -> skip
        return
    for top in list(extra_windows):
        try:
            if top.winfo_exists() and top.winfo_ismapped():
                pop = grab(toplevel_hwnd(top))
                if pop is not None:
                    img.paste(pop, (top.winfo_rootx() - root.winfo_rootx(), top.winfo_rooty() - root.winfo_rooty()))
        except tk.TclError:
            pass
    latest['img'] = img


def update_bbox():
    capture_program()


def compose(img):
    w = OUT_W; h = int(img.height * w / img.width) // 2 * 2
    img = img.resize((w, h), Image.LANCZOS)
    band = 64
    frame = Image.new('RGB', (w, h + band), (12, 17, 28))
    frame.paste(img, (0, 0))
    d = ImageDraw.Draw(frame)
    d.rectangle([0, h, w, h + band], fill=(16, 24, 40))
    d.rectangle([0, h, 8, h + band], fill=(74, 214, 200))
    d.text((22, h + 6), caption['title'], font=FONT, fill=(239, 194, 111))
    d.text((22, h + 37), caption['sub'], font=FONT_S, fill=(200, 212, 228))
    return frame


def capture():
    writer = None
    t_next = time.perf_counter(); last = None
    while not stop.is_set():
        img = latest['img']
        if img is not None:
            last = compose(img)
        if last is not None:
            if writer is None:
                writer = imageio_ffmpeg.write_frames(str(OUT), last.size, fps=FPS, codec='libx264',
                                                     pix_fmt_out='yuv420p', quality=7, macro_block_size=2)
                writer.send(None)
            now = time.perf_counter()
            while t_next <= now:                  # keep real time: duplicate if capture fell behind
                writer.send(last.tobytes()); t_next += 1 / FPS
        time.sleep(max(0, t_next - time.perf_counter()))
    if writer is not None:
        writer.close()


def shot(name):
    root.update(); capture_program()
    if latest['img'] is not None:
        latest['img'].save(SHOTS / f'{name}.png')


def press(keysym):
    ev = SimpleNamespace(keysym=keysym, keycode=0)
    app.key_down(ev); app.key_up(ev)


def cap(title, sub=''):
    caption['title'] = title; caption['sub'] = sub


def next_coach_keys(i, keymap):
    """Keys toward the coach's recommended placement (computed by the program's own AI)."""
    p = app.players[i]
    best = app.coach_best(i)
    if best is None or p.active is None:
        return None
    return [keymap[a] for a in plan_actions(p.board, p.active, best.piece)]


def play_coach(i, keymap, seconds, key_gap=0.09, piece_gap=0.25):
    """Generator: a virtual player that follows the coach recommendation with real key presses."""
    end = time.monotonic() + seconds
    while time.monotonic() < end and app.active and not app.finished:
        keys = next_coach_keys(i, keymap)
        if keys is None:
            yield 0.05; continue
        for k in keys:
            press(k); yield key_gap
        yield piece_gap


def interleave(*gens):
    """Run several key generators 'simultaneously' (two players on one keyboard)."""
    timers = [0.0] * len(gens); gens = list(gens)
    while gens:
        i = min(range(len(gens)), key=lambda j: timers[j])
        dt = timers[i]
        for j in range(len(timers)):
            timers[j] -= dt
        yield dt
        try:
            timers[i] = next(gens[i])
        except StopIteration:
            gens.pop(i); timers.pop(i)


def spin_route_step():
    p = app.players[0]
    route = solve_spin_actions(p.board, start=p.active)
    return route


def script():
    # 0. title
    app.mode.set('ai'); app.mode_changed()
    cap('AI기초프로젝트 레벨3 · 인간-AI 대전 테트리스', '실제 프로그램 실행 화면 녹화 · 모든 조작은 Tk 키보드 이벤트로 입력')
    yield 4.0; shot('00_main')

    # 1. solo
    app.mode.set('solo'); app.mode_changed(); app.seed = 11; app.start()
    cap('① 1인용 플레이', '←/→ 이동 · ↑ 회전 · Space 즉시 낙하 · C Hold  |  청록 점선 = AI 도우미 추천 위치, 회색 테두리 = 낙하 예상(Ghost)')
    yield 0.5
    press('c'); yield 0.6                                    # hold once
    yield from play_coach(0, P1, 9.0)
    shot('01_solo_coach')

    # 2. two players
    app.mode.set('two'); app.mode_changed(); app.seed = 23; app.start()
    cap('② 2인 동시 플레이 (공격 없음)', 'P1: 방향키 / P2: A·D·W·F  ·  보드·낙하 타이머·점수 독립 관리, 같은 시드의 7-bag으로 공정한 블록 순서')
    yield 0.4
    yield from interleave(play_coach(0, P1, 9.0, 0.08), play_coach(1, P2, 9.0, 0.11, 0.3))
    shot('02_two_players')

    # 3. versus attack
    app.mode.set('versus'); app.mode_changed(); app.seed = 31; app.start()
    a, b = app.players
    for y in range(H - 4, H):
        a.board[y] = ['G'] * W; a.board[y][7] = None
    a.active = Piece('I'); a.version += 1
    cap('③ 2인 대전 · 공격 시스템', '시연을 위해 P1 보드를 "테트리스 직전" 상태로 구성 → P1이 I 블록으로 4줄 제거')
    yield 1.5
    for k in ('Up', 'Right', 'Right'):            # vertical I -> column 7 (the well)
        press(k); yield 0.25
    yield 0.4; press('space'); yield 0.3
    cap('③ 2인 대전 · 공격 시스템', f'TETRIS → 상대에게 방해 줄 {b.pending}줄 예약 (빨간 막대)  ·  상대가 블록을 고정하면 실제 보드에 삽입')
    yield 2.2; shot('03_versus_pending')
    press('f'); yield 0.6
    cap('③ 2인 대전 · 방해 줄 수신 후에도 정상 진행', '수정 전에는 방해 줄을 받는 즉시 GAME OVER가 되던 버그 → 수정 후 정상적으로 게임 계속')
    yield from interleave(play_coach(0, P1, 6.0, 0.08), play_coach(1, P2, 6.0, 0.1, 0.3))
    shot('03_versus_after')

    # 4. human vs AI with difficulty selection
    app.mode_buttons['ai'].invoke(); app.diff_buttons['normal'].invoke(); app.seed = 41; app.start()
    cap('④ 인간 vs AI · 난이도 보통', 'AI는 백그라운드 스레드에서 모든 회전·위치를 평가 · 노란 점선 = AI 목표 · 오른쪽 패널 = AI 판단 근거')
    yield from play_coach(0, P1, 7.0, 0.12, 0.35)
    app.diff_buttons['hard'].invoke()
    cap('⑤ AI 난이도 선택 → 어려움', '다음 블록까지 고려하는 2단계 탐색(현재 블록 × 다음 블록)  ·  계산 중에도 입력·낙하·화면 갱신이 멈추지 않음')
    yield from play_coach(0, P1, 10.0, 0.12, 0.35)
    shot('04_human_vs_ai')

    # 5. coach detail
    app.mode.set('solo'); app.mode_changed(); app.seed = 52; app.start()
    p = app.players[0]
    for kind_moves in range(5):
        best = None
        for _ in range(40):
            best = app.coach_best(0)
            if best:
                break
            yield 0.05
        keys = [P1[a] for a in plan_actions(p.board, p.active, best.piece)]
        for k in keys:
            press(k); yield 0.08
        yield 0.15
    cap('⑥ AI 도우미 · 설명 가능한 평가', '블록을 움직일 때마다 줄 제거·높이·구멍·평탄화·T-Spin 후보의 기여 점수가 갱신 (게임 점수와 별개인 AI 평가)')
    for k in ('Left', 'Left', 'Up', 'Right', 'Right', 'Right', 'Up', 'Right'):
        press(k); yield 0.75
    shot('05_coach_detail')
    best = app.coach_best(0)
    if best:
        for k in [P1[a] for a in plan_actions(p.board, p.active, best.piece)]:
            press(k); yield 0.1

    # 6. T-Spin in a normal game
    app.mode.set('solo'); app.mode_changed(); app.seed = 61; app.start()
    p = app.players[0]
    pz = generate(8, 'easy')
    p.board = [r[:] for r in pz.board]; p.active = Piece('T'); p.version += 1
    cap('⑦ T-Spin 판정 (일반 게임)', '시연을 위해 T-Spin Double 구멍이 있는 보드를 구성 → 실제 회전(SRS 킥)으로 T를 끼워 넣음')
    yield 1.5
    for _ in range(60):
        route = solve_spin_actions(p.board, start=p.active, min_lines=pz.target_lines)
        if not route:
            break
        press(P1[route[0]]); yield 0.07 if route[0] == 'down' else 0.35
    press('space'); yield 0.3
    cap('⑦ T-Spin 판정 (일반 게임)', f'결과: {p.last_action} · 마지막 동작이 회전 + 모서리 3칸 이상 막힘 → T-Spin (공중 회전 후 낙하는 인정하지 않음)')
    yield 3.0; shot('06_tspin_game')

    # 7-8. puzzle
    app.mode_buttons['puzzle'].invoke(); app.diff_buttons['hard'].invoke(); app.seed = 77; app.start()
    pz = app.session.puzzle
    cap('⑧ AI T-Spin 퍼즐 생성 · 어려움 (I → O → T)', 'BFS로 모든 블록의 실제 키 입력 경로(이동·회전·SRS 킥)를 검증한 문제만 출제 · 준비 블록 없이는 풀 수 없음도 확인')
    yield 3.0; shot('07_puzzle_start')
    for lv in range(3):
        press('h'); yield 1.6
    shot('07_puzzle_hint')
    cap('⑨ 퍼즐 풀이 (실제 키 입력)', '준비 블록(I: 지붕, O: 빈칸 채우기) 배치 → T를 회전시켜 슬롯에 넣고 Space로 고정')
    pl = app.players[0]
    for i, kind in enumerate(pz.sequence):
        if kind == 'T':
            for _ in range(80):
                route = solve_spin_actions(pl.board, start=pl.active, min_lines=pz.target_lines)
                if not route:
                    break
                press(P1[route[0]]); yield 0.07 if route[0] == 'down' else 0.3
        else:
            x, y, r = pz.solution[i]
            target = frozenset(Piece(kind, x, y, r).squares())
            for _ in range(80):
                hit = reachable_placements(pl.board, kind, start=pl.active).get(target)
                if not hit or hit[1][0] == 'hard':
                    break
                press(P1[hit[1][0]]); yield 0.07
        yield 0.3; press('space'); yield 0.8
    cap('⑨ 퍼즐 성공 → 통계 갱신', app.message_var.get())
    yield 3.0; shot('08_puzzle_success')

    # 9. records
    app.stop(); app.mode.set('ai'); app.mode_changed()
    cap('⑩ 기록 저장·불러오기', 'records.json에 플레이어별 최고 점수·승패·제거 줄 수·퍼즐 성공 기록 저장 → 재실행 시 자동 표시')
    top = app.show_records()
    extra_windows.append(top)
    top.geometry(f'+{root.winfo_rootx() + 420}+{root.winfo_rooty() + 260}')
    yield 4.0; shot('09_records')
    top.destroy(); yield 2.5
    stop.set()


gen = script()


def tick():
    try:
        update_bbox()
        delay = next(gen)
        root.after(max(1, int(delay * 1000)), tick)
    except StopIteration:
        root.after(800, finish)


def finish():
    th.join(timeout=10)
    app.close()


def capture_timer():
    capture_program()
    if not stop.is_set():
        root.after(int(1000 / FPS), capture_timer)


capture_program()
root.after(50, capture_timer)
th = threading.Thread(target=capture, daemon=True)
th.start()
root.after(300, tick)
root.mainloop()
stop.set(); th.join(timeout=10)
if SAVE.exists():
    SAVE.unlink()
print('video:', OUT, 'screens:', SHOTS)
