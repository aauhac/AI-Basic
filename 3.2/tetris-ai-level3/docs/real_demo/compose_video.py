"""Edit the raw window recordings into the submission video (1920x1080, 30 fps, H.264).

Only editing is done here: scene title cards, captions, a key/click overlay built from the input
log (the keys that were really sent), the real mouse-cursor position, and 2x speed-up of waiting
parts (always labelled on screen). Game pixels are copied 1:1 (no scaling, no retouching).

Usage: python docs/real_demo/compose_video.py <raw_dir> <output.mp4>
"""
import bisect
import json
import sys
from pathlib import Path

import imageio_ffmpeg
import numpy as np
from PIL import Image, ImageDraw, ImageFont

RAW = Path(sys.argv[1]); OUT = Path(sys.argv[2])
W, H, FPS = 1920, 1080, 30
BG = (11, 15, 24); INK = (234, 241, 250); MUTED = (167, 181, 199); ACCENT = (74, 214, 200); GOLD = (239, 194, 111)
FONT = 'C:/Windows/Fonts/malgun.ttf'; FONTB = 'C:/Windows/Fonts/malgunbd.ttf'
F_CAP = ImageFont.truetype(FONTB, 30); F_KEY = ImageFont.truetype(FONTB, 24); F_SMALL = ImageFont.truetype(FONT, 20)
F_TITLE = ImageFont.truetype(FONTB, 60); F_BODY = ImageFont.truetype(FONT, 32); F_TAG = ImageFont.truetype(FONTB, 22)
GX, GY = None, 8                         # game frame placement (computed from the frame size)
BAND_Y = 948
BADGE = '자동화된 GUI 입력 시연 · Windows SendInput 키보드/마우스 · 게임 창만 녹화'
CARD_SEC, FIRST_CARD_SEC = 2.8, 6.0

events = json.loads((RAW / 'events.json').read_text(encoding='utf-8'))
# Optional caption corrections (applied to captions only, never to game footage):
#   [{"t": <event time>, "old_prefix": "...", "new": "...", "reason": "..."}]
if len(sys.argv) > 3:
    for fix in json.loads(Path(sys.argv[3]).read_text(encoding='utf-8')):
        hit = [e for e in events if e['kind'] == 'caption' and abs(e['t'] - fix['t']) < 0.01
               and e['value'].startswith(fix['old_prefix'])]
        assert len(hit) == 1, fix
        hit[0]['value'] = fix['new']


# ----------------------------------------------------------------------------- timeline
def build_timeline():
    items, cur = [], None
    for e in events:
        k = e['kind']
        if k == 'card':
            items.append({'type': 'card', 'title': e['value'], 'body': e.get('body', '')})
        elif k == 'seg_start':
            cur = {'type': 'clip', 'name': e['value'], 'session': e['session'], 't0': e['t'], 'speed0': e.get('speed', 1.0),
                   'speeds': [], 'captions': [], 't1': None}
        elif k == 'seg_end' and cur:
            cur['t1'] = e['t']; items.append(cur); cur = None
        elif cur is not None and k == 'speed':
            cur['speeds'].append((e['t'], e['value']))
        elif cur is not None and k == 'caption':
            cur['captions'].append((e['t'], e['value']))
    keys = [(e['t'], e['value'], e['kind']) for e in events if e['kind'] in ('key', 'click')]
    return items, keys


class Source:
    """Sequential reader of one raw session video + its per-frame timestamps."""

    def __init__(self, session):
        self.frames = json.loads((RAW / f'session{session}_frames.json').read_text())
        self.t = np.maximum.accumulate(np.array([f['t'] for f in self.frames]))
        self.reader = imageio_ffmpeg.read_frames(str(RAW / f'session{session}.mp4'))
        meta = next(self.reader)
        self.size = meta['size']
        self.idx = -1; self.img = None

    def at(self, ts):
        want = max(0, bisect.bisect_right(self.t, ts) - 1)
        while self.idx < want:
            buf = next(self.reader)
            self.idx += 1
            if self.idx == want:
                self.img = np.frombuffer(buf, np.uint8).reshape(self.size[1], self.size[0], 3)
        return self.img, self.frames[self.idx]


def draw_cursor(d, x, y):
    pts = [(x, y), (x, y + 26), (x + 7, y + 20), (x + 12, y + 31), (x + 17, y + 29), (x + 12, y + 18), (x + 21, y + 18)]
    d.polygon(pts, fill=(255, 255, 255), outline=(0, 0, 0))


def text_w(d, s, f):
    return d.textbbox((0, 0), s, font=f)[2]


def card_frame(title, body, idx_label):
    im = Image.new('RGB', (W, H), BG); d = ImageDraw.Draw(im)
    d.rectangle([0, 0, 14, H], fill=ACCENT)
    d.text((140, 330), title, font=F_TITLE, fill=INK)
    y = 440
    for line in body.split('\n'):
        d.text((140, y), line, font=F_BODY, fill=MUTED); y += 54
    d.text((140, H - 110), BADGE, font=F_SMALL, fill=ACCENT)
    if idx_label:
        d.text((W - 140 - text_w(d, idx_label, F_TAG), 120), idx_label, font=F_TAG, fill=GOLD)
    return np.asarray(im)


def render(game, meta, caption, keys_now, speed, clicks_now):
    global GX
    gh, gw = game.shape[:2]
    if GX is None:
        GX = (W - gw) // 2
    im = Image.new('RGB', (W, H), BG)
    im.paste(Image.fromarray(game), (GX, GY))
    d = ImageDraw.Draw(im)
    d.rectangle([GX - 1, GY - 1, GX + gw, GY + gh], outline=(50, 65, 94))
    cx, cy = meta['cursor']
    if 0 <= cx < gw and 0 <= cy < gh:
        for age in clicks_now:
            r = int(10 + 50 * age)
            d.ellipse([GX + cx - r, GY + cy - r, GX + cx + r, GY + cy + r], outline=GOLD, width=3)
        draw_cursor(d, GX + cx, GY + cy)
    d.text((GX, BAND_Y + 6), caption or '', font=F_CAP, fill=INK)
    ky = BAND_Y + 62
    lab = '입력 '
    d.text((GX, ky), lab, font=F_KEY, fill=MUTED)
    x = GX + text_w(d, lab, F_KEY) + 6
    for k in keys_now:
        tw = text_w(d, k, F_KEY)
        d.rounded_rectangle([x - 8, ky - 2, x + tw + 8, ky + 34], 6, fill=(33, 45, 67), outline=(74, 98, 130))
        d.text((x, ky), k, font=F_KEY, fill=ACCENT)
        x += tw + 26
    bw = text_w(d, BADGE, F_SMALL)
    d.text((GX + gw - bw, BAND_Y + 70), BADGE, font=F_SMALL, fill=MUTED)
    if speed != 1.0:
        tag = f'▶▶ {speed:g}배속 (편집)'
        tw = text_w(d, tag, F_TAG)
        d.rounded_rectangle([GX + gw - tw - 30, BAND_Y + 10, GX + gw, BAND_Y + 48], 8, fill=(80, 60, 20))
        d.text((GX + gw - tw - 15, BAND_Y + 12), tag, font=F_TAG, fill=GOLD)
    return np.asarray(im)


def main():
    items, keys = build_timeline()
    key_t = [k[0] for k in keys]
    writer = imageio_ffmpeg.write_frames(str(OUT), (W, H), fps=FPS, codec='libx264', quality=None, pix_fmt_out='yuv420p',
                                         macro_block_size=1, output_params=['-crf', '18', '-preset', 'medium', '-movflags', '+faststart'])
    writer.send(None)
    sources = {}
    out_t = 0.0
    index = []
    n_cards = sum(1 for it in items if it['type'] == 'card')
    ci = 0
    for it in items:
        if it['type'] == 'card':
            ci += 1
            dur = FIRST_CARD_SEC if ci == 1 else CARD_SEC
            fr = card_frame(it['title'], it['body'], '' if ci == 1 else it['title'].split('·')[0].strip())
            for _ in range(int(dur * FPS)):
                writer.send(fr)
            index.append({'type': 'card', 'title': it['title'], 'out_start': round(out_t, 2), 'out_end': round(out_t + dur, 2)})
            out_t += int(dur * FPS) / FPS
            continue
        s = it['session']
        if s not in sources:
            sources[s] = Source(s)
        src = sources[s]
        ts, speed = it['t0'], it['speed0']
        sp = list(it['speeds']); caps = list(it['captions'])
        start = out_t
        nframes = 0; sped = 0.0
        while ts < it['t1']:
            while sp and sp[0][0] <= ts:
                speed = sp.pop(0)[1]
            cap = None
            for t, c in caps:
                if t <= ts:
                    cap = c
            if cap:
                cap = cap.replace('☰ 기록', '[기록]')          # glyph missing in Malgun Gothic
                if speed == 1.0:                               # never claim a speed-up that is not active
                    cap = cap.replace(' (2배속 편집)', '')
            img, meta = src.at(ts)
            lo = bisect.bisect_left(key_t, ts - 1.6); hi = bisect.bisect_right(key_t, ts)
            recent = keys[lo:hi]
            labels = [('클릭' if kind == 'click' else v) for t, v, kind in recent if kind == 'key' or t > ts - 0.8][-12:]
            clicks = [ts - t for t, v, kind in recent if kind == 'click' and ts - t < 0.45]
            writer.send(render(img, meta, cap, labels, speed, clicks))
            nframes += 1
            if speed != 1.0:
                sped += 1 / FPS
            ts += speed / FPS
        out_t += nframes / FPS
        index.append({'type': 'clip', 'name': it['name'], 'session': s, 'src_start': round(it['t0'], 2), 'src_end': round(it['t1'], 2),
                      'out_start': round(start, 2), 'out_end': round(out_t, 2), 'sped_up_out_sec': round(sped, 1)})
    writer.close()
    (OUT.with_suffix('.index.json')).write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding='utf-8')
    print(json.dumps({'duration_sec': round(out_t, 2), 'cards': n_cards, 'clips': len(index) - n_cards}, ensure_ascii=False))


if __name__ == '__main__':
    main()
