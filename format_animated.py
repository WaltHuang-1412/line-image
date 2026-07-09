"""Animated APNG stickers — Tier 2: body motion + particles + animated text.

Composition per sticker (LINE animated spec: 320x270, APNG, <=300KB, 1-4s):
  1. body layer  — source nobg image with squash/stretch/rotate/shift per frame
  2. particle layer — programmatic effects (stars, tears, sweat, anger, zzz...)
  3. text layer  — emotion word, behavior matched to the body motion

prompts.json (type "animated_sticker") entries:
  {"id": 1, "emotion": "嗯嗯", "source": {"version": "v14", "sid": 1},
   "motion": "nod", "particles": "sparkle"}

APNG gotchas handled here (learned the hard way):
  - APNG shares ONE palette across all frames -> quantize with a shared palette
  - PIL trims tRNS to palette length -> transparent index must be a real entry
  - optimize=True reorders the palette and breaks tRNS -> never use it

Usage (via main.py):
    python main.py animate <theme> <version> [--lang zh|ja]
"""
import json
import math
import os
from io import BytesIO

from PIL import Image, ImageDraw, ImageFont

import config

W, H = 320, 270           # LINE animated sticker canvas
MAIN_SIZE = (240, 240)    # animated main image
TAB_SIZE = (96, 74)       # static tab image
MAX_KB = 300
FONT_PATH = r"C:\Windows\Fonts\msjhbd.ttc"
PALETTE_COLORS = 254      # +1 reserved transparent index


# ---------------------------------------------------------------------------
# Body transforms
# ---------------------------------------------------------------------------

def _load_body(path, target_h=190):
    img = Image.open(path).convert("RGBA")
    img = img.crop(img.getbbox())
    scale = target_h / img.height
    return img.resize((int(img.width * scale), target_h), Image.LANCZOS)


def _squash(body, sy):
    sx = 1.0 / math.sqrt(sy)
    return body.resize((int(body.width * sx), int(body.height * sy)), Image.LANCZOS)


def _transform(body, sy=1.0, rot=0.0):
    out = body if sy == 1.0 else _squash(body, sy)
    if rot:
        out = out.rotate(rot, resample=Image.BICUBIC, expand=True)
    return out


# Each motion returns a list of per-frame params: (sy, rot, dx, dy, delay_ms)
MOTIONS = {
    "nod": lambda: [(1.0, 0, 0, 0, 110), (0.96, 0, 0, 2, 100), (0.93, 0, 0, 4, 100),
                    (0.97, 0, 0, 2, 100), (1.0, 0, 0, 0, 110), (0.96, 0, 0, 2, 100),
                    (0.93, 0, 0, 4, 100), (0.97, 0, 0, 2, 100), (1.0, 0, 0, 0, 220)],
    "nod_slow": lambda: [(1.0, 0, 0, 0, 140)] + [(1 - 0.05 * math.sin(math.pi * i / 5), 0, 0,
                    3 * math.sin(math.pi * i / 5), 120) for i in range(1, 6)] + [(1.0, 0, 0, 0, 260)],
    "bounce": lambda: [(1.0, 0, 0, 0, 110), (0.90, 0, 0, 0, 100), (0.82, 0, 0, 0, 90),
                       (0.95, 0, 0, 0, 90), (1.10, 0, 0, -14, 100), (1.04, 0, 0, -4, 100),
                       (1.0, 0, 0, 0, 110), (1.0, 0, 0, 0, 150), (1.0, 0, 0, 0, 150), (1.0, 0, 0, 0, 150)],
    "bounce_soft": lambda: [(1.0, 0, 0, 0, 120), (0.94, 0, 0, 0, 110), (0.90, 0, 0, 0, 100),
                            (1.05, 0, 0, -8, 110), (1.0, 0, 0, 0, 120), (1.0, 0, 0, 0, 160),
                            (0.97, 0, 0, 0, 130), (1.0, 0, 0, 0, 160)],
    "sway": lambda: [(1.0, 3.0 * math.sin(2 * math.pi * i / 12), 0, 0, 105) for i in range(12)],
    "sway_slow": lambda: [(1.0, 2.5 * math.sin(2 * math.pi * i / 14), 0, 0, 125) for i in range(14)],
    "pop": lambda: [(0.72, 0, 0, 0, 90), (1.12, 0, 0, -6, 90), (0.96, 0, 0, 0, 90),
                    (1.04, 0, 0, -2, 90), (1.0, 0, 0, 0, 110), (1.0, 2, 1, 0, 110),
                    (1.0, -2, -1, 0, 110), (1.0, 2, 1, 0, 110), (1.0, 0, 0, 0, 240)],
    "tremble": lambda: [(0.99 if i % 2 else 1.0, 0, 2 if i % 2 else -2, 0, 85) for i in range(12)],
    "rock": lambda: [(1.0, 3.2 * math.sin(2 * math.pi * i / 12), (1 if i % 2 else -1), 0, 105) for i in range(12)],
    "shake": lambda: [(0.985 if i % 4 in (1, 2) else 1.0, 0, (4 if i % 2 == 0 else -4), 0, 95) for i in range(12)],
    "headshake": lambda: [(1.0, 0, x, 0, 115) for x in (0, -4, -6, -4, 0, 4, 6, 4, 0, 0)],
    "sink": lambda: [(1.0, 0, 0, 0, 130), (0.985, 0, 0, 1, 130), (0.97, 0.6, 0, 2, 130),
                     (0.955, 1.2, 0, 3, 140), (0.94, 1.8, 0, 4, 170), (0.94, 1.8, 0, 4, 260),
                     (0.955, 1.2, 0, 3, 130), (0.985, 0.4, 0, 1, 130)],
    "lean": lambda: [(1.0, -x, x * 0.8, 0, 105) for x in (0, 2, 4, 5, 5, 4, 2, 0, 0, 0)],
    "leanback": lambda: [(1.0, x, -x, 0, 100) for x in (0, 3, 5, 6, 6, 5, 3, 0, 0, 0)],
    "bow": lambda: [(1.0, x, 0, x * 0.7, 115) for x in (0, 3, 6, 8, 8, 8, 6, 3, 0, 0)],
}


# ---------------------------------------------------------------------------
# Particles
# ---------------------------------------------------------------------------

def _star(d, cx, cy, r, fill):
    pts = []
    for i in range(8):
        ang = math.pi / 4 * i - math.pi / 2
        rr = r if i % 2 == 0 else r * 0.4
        pts.append((cx + rr * math.cos(ang), cy + rr * math.sin(ang)))
    d.polygon(pts, fill=fill)


def _anger(d, cx, cy, r, alpha):
    col = (230, 60, 60, alpha)
    wdt = max(3, int(r * 0.28))
    for ang in (45, 135, 225, 315):
        a = math.radians(ang)
        d.line([(cx + r * 0.35 * math.cos(a), cy + r * 0.35 * math.sin(a)),
                (cx + r * math.cos(a), cy + r * math.sin(a))], fill=col, width=wdt)


def _symbol(d, ch, cx, cy, size, fill, alpha=255):
    font = ImageFont.truetype(FONT_PATH, size)
    bb = d.textbbox((0, 0), ch, font=font, stroke_width=3)
    d.text((cx - (bb[2] - bb[0]) / 2, cy - (bb[3] - bb[1]) / 2 - bb[1]), ch, font=font,
           fill=fill + (alpha,), stroke_width=3, stroke_fill=(255, 255, 255, alpha))


def _p_sparkle(d, i, n, top):
    ph = i % 4
    for j, (x, y) in enumerate([(46, top + 66), (276, top + 52), (290, top + 118)]):
        if (j + ph) % 3 != 2:
            _star(d, x, y, 7 if (j + ph) % 2 == 0 else 5, (255, 224, 120, 235))


def _p_stars(d, i, n, top):
    ph = 1 + i % 2
    for j, (x, y) in enumerate([(50, top + 60), (272, top + 46), (36, top + 130), (284, top + 132)]):
        _star(d, x, y, 10 if (j + ph) % 2 == 0 else 6, (255, 214, 70, 255))


def _p_exclaim(d, i, n, top):
    pulse = 1.0 + 0.18 * math.sin(2 * math.pi * i / max(1, n // 2))
    _symbol(d, "!", 282, top + 58, int(40 * pulse), (235, 90, 60))


def _p_question(d, i, n, top):
    prog = (i / n) % 1.0
    alpha = int(255 * (1.0 - prog * 0.5))
    _symbol(d, "?", 280, top + 70 - prog * 22, 40, (110, 130, 200), alpha)


def _p_sweat(d, i, n, top):
    for k, (bx, by, ang) in enumerate([(60, top + 40, 210), (266, top + 36, -30), (286, top + 90, 20)]):
        prog = ((i / n) + k * 0.33) % 1.0
        a = math.radians(ang)
        x, y = bx + prog * 26 * math.cos(a), by + prog * 26 * math.sin(a) + prog * 10
        alpha = int(235 * (1 - prog * 0.6))
        r = 6 - prog * 2
        d.ellipse([x - r, y - r * 1.4, x + r, y + r * 1.4], fill=(130, 195, 255, alpha))


def _p_tears(d, i, n, top):
    for side, bx in ((-1, W / 2 - 52), (1, W / 2 + 52)):
        for k in range(2):
            prog = ((i / n) + k * 0.5) % 1.0
            ty = top + 92 + prog * 88
            alpha = int(255 * (1.0 - prog * 0.55))
            r = 7 - prog * 2.5
            d.ellipse([bx - r, ty - r * 1.5, bx + r, ty + r * 1.5], fill=(120, 190, 255, alpha))


def _p_anger(d, i, n, top):
    pulse = 0.75 + 0.25 * math.sin(2 * math.pi * i / 6)
    _anger(d, 268, top + 36, 20 * pulse, 255)
    _anger(d, 240, top + 70, 11 * pulse, 200)


def _p_anger_small(d, i, n, top):
    pulse = 0.8 + 0.2 * math.sin(2 * math.pi * i / 6)
    _anger(d, 272, top + 44, 13 * pulse, 235)


def _p_zzz(d, i, n, top):
    for k in range(3):
        prog = ((i / n) + k * 0.33) % 1.0
        alpha = int(230 * (1 - prog * 0.7))
        _symbol(d, "Z", int(252 + prog * 34 + k * 6), int(top + 80 - prog * 52 - k * 4),
                int(20 + 12 * prog), (140, 150, 210), alpha)


def _p_gloom(d, i, n, top):
    sway = 2 * math.sin(2 * math.pi * i / n)
    for k, x in enumerate((120, 152, 184)):
        y0 = top + 6 + (k % 2) * 4
        d.line([(x + sway, y0), (x + sway, y0 + 22)], fill=(90, 100, 160, 190), width=4)


def _p_dust(d, i, n, top):
    for k in range(3):
        prog = ((i / n) + k * 0.33) % 1.0
        alpha = int(190 * (1 - prog))
        r = 6 + prog * 8
        x, y = 62 - prog * 34 - k * 8, H - 26 - k * 6 - prog * 8
        d.ellipse([x - r, y - r * 0.7, x + r, y + r * 0.7], fill=(200, 195, 185, alpha))


PARTICLES = {
    "sparkle": _p_sparkle, "stars": _p_stars, "exclaim": _p_exclaim,
    "question": _p_question, "sweat": _p_sweat, "tears": _p_tears,
    "anger": _p_anger, "anger_small": _p_anger_small, "zzz": _p_zzz,
    "gloom": _p_gloom, "dust": _p_dust,
}


# ---------------------------------------------------------------------------
# Text layer
# ---------------------------------------------------------------------------

def _font_size(text):
    n = len(text)
    return {1: 56, 2: 52, 3: 46, 4: 40}.get(n, 34)


def _text_layer(text, pos_y, dx=0, dy=0, scale=1.0):
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    fs = max(10, int(_font_size(text) * scale))
    font = ImageFont.truetype(FONT_PATH, fs)
    d = ImageDraw.Draw(layer)
    sw = max(2, fs // 9)
    bb = d.textbbox((0, 0), text, font=font, stroke_width=sw)
    x = (W - (bb[2] - bb[0])) / 2 - bb[0] + dx
    y = pos_y - (bb[3] - bb[1]) / 2 - bb[1] + dy
    d.text((x, y), text, font=font, fill=(80, 50, 30, 255),
           stroke_width=sw, stroke_fill=(255, 255, 255, 255))
    return layer


def _text_params(motion, i, n):
    """(dx, dy, scale) for the text on frame i, matched to body motion energy."""
    if motion in ("pop", "bounce", "bounce_soft"):
        if i == 0:
            return 0, 0, 0.0
        if i == 1:
            return 0, 0, 0.7
        if i == 2:
            return 0, 0, 1.2
        return 0, 0, 1.0
    if motion in ("shake", "tremble"):
        return (3 if i % 2 else -3), 0, 1.0
    if motion == "rock":
        return 3 * math.sin(2 * math.pi * i / n * 2), 0, 1.0
    return 0, 1 if i % 4 in (1, 2) else 0, 1.0


# ---------------------------------------------------------------------------
# APNG assembly (shared palette — APNG has a single PLTE for all frames)
# ---------------------------------------------------------------------------

def _shared_palette(frames, colors):
    cols = min(4, len(frames))
    rows = (len(frames) + cols - 1) // cols
    tw, th = frames[0].width // 2, frames[0].height // 2
    comp = Image.new("RGBA", (cols * tw, rows * th), (0, 0, 0, 0))
    for i, f in enumerate(frames):
        comp.alpha_composite(f.resize((tw, th)), ((i % cols) * tw, (i // cols) * th))
    grey = Image.new("RGBA", comp.size, (130, 130, 130, 255))
    grey.alpha_composite(comp)
    return grey.convert("RGB").quantize(colors=colors, method=Image.MEDIANCUT)


def _quantize_frame(f, pal, t_index):
    grey = Image.new("RGBA", f.size, (130, 130, 130, 255))
    grey.alpha_composite(f)
    q = grey.convert("RGB").quantize(palette=pal, dither=Image.Dither.NONE)
    plist = q.getpalette()[: t_index * 3]
    plist += [0, 0, 0] * (t_index + 1 - len(plist) // 3)
    q.putpalette(plist)
    mask = f.getchannel("A").point(lambda a: 255 if a < 128 else 0)
    q.paste(t_index, mask)
    return q


def save_apng(frames, delays, path, colors=PALETTE_COLORS):
    """Write APNG with one shared palette + reserved transparent index. Returns KB."""
    from apng import APNG, PNG
    pal = _shared_palette(frames, colors)
    trns = b"\xff" * colors + b"\x00"
    ap = APNG()
    for f, ms in zip(frames, delays):
        q = _quantize_frame(f, pal, colors)
        q.info["transparency"] = trns
        buf = BytesIO()
        q.save(buf, "PNG")
        ap.append(PNG.from_bytes(buf.getvalue()), delay=int(ms))
    ap.save(path)
    kb = os.path.getsize(path) / 1024
    if kb > MAX_KB and colors > 128:
        return save_apng(frames, delays, path, colors=max(128, colors - 64))
    return kb


# ---------------------------------------------------------------------------
# Sticker assembly
# ---------------------------------------------------------------------------

def render_frames(body_img, text, text_pos, motion, particles, canvas=(W, H)):
    """Compose all frames for one sticker. Returns (frames, delays)."""
    cw, ch = canvas
    params = MOTIONS[motion]()
    n = len(params)
    body_top = ch - 6 - body_img.height  # particle anchor
    frames, delays = [], []
    for i, (sy, rot, dx, dy, ms) in enumerate(params):
        c = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
        b = _transform(body_img, sy, rot)
        c.alpha_composite(b, (int(cw / 2 - b.width / 2 + dx), int(ch - 6 - b.height + dy)))
        if particles:
            d = ImageDraw.Draw(c)
            PARTICLES[particles](d, i, n, max(6, body_top - 8))
        tdx, tdy, tscale = _text_params(motion, i, n)
        if tscale > 0:
            pos_y = 34 if text_pos == "top" else ch - 32
            c.alpha_composite(_text_layer(text, pos_y, tdx, tdy, tscale))
        frames.append(c)
        delays.append(ms)
    return frames, delays


def animate_sticker(entry, theme, out_path, canvas=(W, H), body_h=None):
    src = entry["source"]
    src_dir = config.get_paths(theme, src["version"])["raw"]
    src_png = os.path.join(src_dir, f"sticker_{src['sid']:02d}_nobg.png")
    bh = body_h or (canvas[1] - 80)
    body = _load_body(src_png, bh)
    text_pos = "top" if entry["id"] % 2 == 1 else "bottom"
    frames, delays = render_frames(body, entry["emotion"], text_pos,
                                   entry["motion"], entry.get("particles"), canvas)
    return save_apng(frames, delays, out_path)


def animate_all(theme, version, lang=None):
    """Generate all animated stickers + animated main + static tab."""
    lang = lang or "zh"
    ver_dir = config.get_version_dir(theme, version)
    prompts_file = os.path.join(ver_dir, lang, "prompts.json")
    if not os.path.exists(prompts_file):
        prompts_file = os.path.join(ver_dir, "prompts.json")
    with open(prompts_file, encoding="utf-8") as f:
        data = json.load(f)

    out_dir = os.path.join(ver_dir, lang)
    os.makedirs(out_dir, exist_ok=True)
    print(f"\n=== Animate {len(data['stickers'])} stickers [{theme}/{version}/{lang}] ===\n")

    for s in data["stickers"]:
        out = os.path.join(out_dir, f"sticker_{s['id']:02d}.png")
        kb = animate_sticker(s, theme, out)
        flag = "" if kb <= MAX_KB else "  !! OVER 300KB"
        print(f"  [#{s['id']:02d}] {s['emotion']:8s} {s['motion']:12s} {kb:4.0f}KB{flag}")

    main_id = data.get("main_id", 1)
    main_entry = next(s for s in data["stickers"] if s["id"] == main_id)
    kb = animate_sticker(main_entry, theme, os.path.join(out_dir, "main.png"),
                         canvas=MAIN_SIZE, body_h=168)
    print(f"  [main] animated {kb:.0f}KB")

    src = main_entry["source"]
    src_png = os.path.join(config.get_paths(theme, src["version"])["raw"],
                           f"sticker_{src['sid']:02d}_nobg.png")
    body = _load_body(src_png, TAB_SIZE[1] - 6)
    tab = Image.new("RGBA", TAB_SIZE, (0, 0, 0, 0))
    tab.alpha_composite(body, (int(TAB_SIZE[0] / 2 - body.width / 2), 3))
    tab.save(os.path.join(out_dir, "tab.png"))
    print("  [tab] static saved")
    print(f"\nDone! -> {out_dir}")
