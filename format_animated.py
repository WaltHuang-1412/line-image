"""Animated APNG stickers — static cat + animated text overlay.

Each sticker gets an animation effect chosen per emotion. The cat image is
static; only the text layer animates. Hold frames use a single long-delay
frame to keep file size down.

Usage (via main.py):
    python main.py animate <theme> <version> [--lang zh|ja]
"""
import glob as _glob
import json
import math
import os
from io import BytesIO

from PIL import Image, ImageDraw

import config
from format_stickers import (
    EMOTION_DECO, TEXT_FILL, TEXT_OFFSET, TEXT_STROKE,
    _get_font, _stroke_width, remove_background, resize_to_sticker,
)


# ---------------------------------------------------------------------------
# Effect routing — per emotion
# ---------------------------------------------------------------------------

EMOTION_ANIMATION = {
    "去健身房": "pop_bounce",
    "舉重":     "shake",
    "跑步":     "slide_in",
    "呼拉圈":   "wave",
    "游泳":     "slide_in",
    "瑜珈":     "pop_bounce",
    "爬山":     "slide_in",
    "騎車":     "slide_in",
    "打球":     "pop_bounce",
    "大流汗":   "shake",
    "肌肉痠":   "shake",
    "喝蛋白質": "pop_bounce",
    "量體重":   "typewriter",
    "今天有練": "pop_bounce",
    "拉筋":     "slide_in",
    "翹掉了":   "typewriter",
}

DEFAULT_EFFECT = "pop_bounce"


# ---------------------------------------------------------------------------
# Text rendering helpers
# ---------------------------------------------------------------------------

def _font_size(text):
    n = len(text)
    if n <= 1: return 64
    if n <= 2: return 58
    if n <= 3: return 50
    if n <= 5: return 44
    return 38


def _display(text):
    return text + EMOTION_DECO.get(text, "")


def _render_text_layer(canvas_size, text, text_pos, sticker_id):
    """Render text onto a full-size transparent canvas.

    Returns (layer_rgba, (x, y, x2, y2)) — bbox is the raw text area.
    """
    w, h = canvas_size
    disp = _display(text)
    fs = _font_size(text)
    font = _get_font(fs)
    sw = _stroke_width(fs)

    dummy = Image.new("RGBA", (1, 1))
    bbox = ImageDraw.Draw(dummy).textbbox((0, 0), disp, font=font, stroke_width=sw)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]

    ox = TEXT_OFFSET.get(sticker_id, 0)
    x = max(4, min((w - tw) // 2 + ox, w - tw - 4))
    y = 2 if text_pos == "top" else h - th - 4

    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    draw.text((x + 2, y + 2), disp, font=font,
              fill=(0, 0, 0, 40), stroke_width=sw, stroke_fill=(0, 0, 0, 0))
    draw.text((x, y), disp, font=font,
              fill=TEXT_FILL, stroke_width=sw, stroke_fill=TEXT_STROKE)

    return layer, (x, y, x + tw, y + th)


def _overlay(cat, layer):
    out = cat.copy()
    out.paste(layer, (0, 0), layer)
    return out


def _shift_layer(layer, dx=0, dy=0):
    shifted = Image.new("RGBA", layer.size, (0, 0, 0, 0))
    shifted.paste(layer, (dx, dy), layer)
    return shifted


def _scale_crop(layer, bbox, scale):
    """Crop text bbox from layer, scale it, and paste back centered."""
    x1, y1, x2, y2 = bbox
    pad = 12  # safe margin (max stroke + buffer)
    cx1 = max(0, x1 - pad)
    cy1 = max(0, y1 - pad)
    cx2 = min(layer.width, x2 + pad)
    cy2 = min(layer.height, y2 + pad)
    crop = layer.crop((cx1, cy1, cx2, cy2))
    cw, ch = crop.size
    nw = max(1, int(cw * scale))
    nh = max(1, int(ch * scale))
    scaled = crop.resize((nw, nh), Image.LANCZOS)

    out = Image.new("RGBA", layer.size, (0, 0, 0, 0))
    center_x = (cx1 + cx2) // 2
    center_y = (cy1 + cy2) // 2
    out.paste(scaled, (center_x - nw // 2, center_y - nh // 2), scaled)
    return out


# ---------------------------------------------------------------------------
# Effects
# ---------------------------------------------------------------------------

def _frames_pop_bounce(cat, text_layer, text_bbox):
    """Scale 0 → 1.1 → 1.0, then hold."""
    scales = [0.05, 0.3, 0.6, 0.9, 1.10, 1.03, 1.08, 1.0]
    frames, delays = [], []
    for s in scales:
        frames.append(_overlay(cat, _scale_crop(text_layer, text_bbox, s)))
        delays.append(40)
    frames.append(_overlay(cat, text_layer))
    delays.append(900)
    return frames, delays


def _frames_slide_in(cat, text_layer, text_bbox, text_pos):
    """Slide text in from off-canvas edge, slight overshoot."""
    _, y1, _, y2 = text_bbox
    th = y2 - y1
    if text_pos == "top":
        dy_seq = [-(th + 20), -(th // 2 + 8), -(th // 4), -2, 4, 1, 0]
    else:
        start = cat.height - y1 + 20
        dy_seq = [start, start // 2, th // 4, 2, -4, -1, 0]
    frames, delays = [], []
    for dy in dy_seq:
        frames.append(_overlay(cat, _shift_layer(text_layer, dy=dy)))
        delays.append(35)
    frames.append(_overlay(cat, text_layer))
    delays.append(900)
    return frames, delays


def _frames_typewriter(cat, text, text_pos, sticker_id):
    """Characters appear one by one, brief blank flash, then hold."""
    disp = _display(text)
    w, h = cat.size
    fs = _font_size(text)
    font = _get_font(fs)
    sw = _stroke_width(fs)

    dummy = Image.new("RGBA", (1, 1))
    draw_d = ImageDraw.Draw(dummy)
    bbox = draw_d.textbbox((0, 0), disp, font=font, stroke_width=sw)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    ox = TEXT_OFFSET.get(sticker_id, 0)
    x = max(4, min((w - tw) // 2 + ox, w - tw - 4))
    y = 2 if text_pos == "top" else h - th - 4

    frames, delays = [], []
    for n in range(1, len(disp) + 1):
        layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer)
        partial = disp[:n]
        draw.text((x + 2, y + 2), partial, font=font,
                  fill=(0, 0, 0, 40), stroke_width=sw, stroke_fill=(0, 0, 0, 0))
        draw.text((x, y), partial, font=font,
                  fill=TEXT_FILL, stroke_width=sw, stroke_fill=TEXT_STROKE)
        frames.append(_overlay(cat, layer))
        delays.append(150)

    # brief blank flash
    frames.append(cat.copy())
    delays.append(80)

    full_layer, _ = _render_text_layer(cat.size, text, text_pos, sticker_id)
    frames.append(_overlay(cat, full_layer))
    delays.append(900)
    return frames, delays


def _frames_shake(cat, text_layer, text_bbox):
    """Quick pop-in, then horizontal shake, then hold."""
    scales_pop = [0.4, 0.8, 1.0]
    shake_dx = [-9, 9, -7, 7, -4, 4, -2, 2, 0]
    frames, delays = [], []
    for s in scales_pop:
        frames.append(_overlay(cat, _scale_crop(text_layer, text_bbox, s)))
        delays.append(30)
    for dx in shake_dx:
        frames.append(_overlay(cat, _shift_layer(text_layer, dx=dx)))
        delays.append(40)
    frames.append(_overlay(cat, text_layer))
    delays.append(900)
    return frames, delays


def _frames_wave(cat, text, text_pos, sticker_id):
    """Each character oscillates up/down with a phase offset (continuous loop)."""
    disp = _display(text)
    w, h = cat.size
    fs = _font_size(text)
    font = _get_font(fs)
    sw = _stroke_width(fs)
    amplitude = 5

    dummy = Image.new("RGBA", (1, 1))
    draw_d = ImageDraw.Draw(dummy)
    bbox = draw_d.textbbox((0, 0), disp, font=font, stroke_width=sw)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    ox = TEXT_OFFSET.get(sticker_id, 0)
    base_x = max(4, min((w - tw) // 2 + ox, w - tw - 4))
    base_y = 2 if text_pos == "top" else h - th - 4

    # Measure cumulative x position for each character
    char_xs = [0]
    for i in range(1, len(disp)):
        b = draw_d.textbbox((0, 0), disp[:i], font=font, stroke_width=sw)
        char_xs.append(b[2] - b[0])

    n_frames = 12
    frames, delays = [], []
    for f in range(n_frames):
        layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer)
        for i, char in enumerate(disp):
            phase = (i / max(len(disp), 1)) * 2 * math.pi
            dy = int(amplitude * math.sin(2 * math.pi * f / n_frames - phase))
            cx = base_x + char_xs[i]
            cy = base_y + dy
            draw.text((cx + 2, cy + 2), char, font=font,
                      fill=(0, 0, 0, 40), stroke_width=sw, stroke_fill=(0, 0, 0, 0))
            draw.text((cx, cy), char, font=font,
                      fill=TEXT_FILL, stroke_width=sw, stroke_fill=TEXT_STROKE)
        frames.append(_overlay(cat, layer))
        delays.append(80)
    return frames, delays


# ---------------------------------------------------------------------------
# APNG output
# ---------------------------------------------------------------------------

def _save_apng(frames, delays_ms, path):
    from apng import APNG, PNG
    im = APNG()
    for frame, delay in zip(frames, delays_ms):
        buf = BytesIO()
        frame.convert("RGBA").save(buf, format="PNG", optimize=True)
        im.append(PNG.from_bytes(buf.getvalue()), delay=delay, delay_den=1000)
    im.save(str(path))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def animate_sticker(idx, img_rgba, text, text_pos, effect=None, out_path=None):
    """Generate one animated APNG. Returns file size in KB."""
    if effect is None:
        effect = EMOTION_ANIMATION.get(text, DEFAULT_EFFECT)

    cat = resize_to_sticker(img_rgba, text=text, text_pos=text_pos)
    text_layer, text_bbox = _render_text_layer(cat.size, text, text_pos, idx)

    dispatch = {
        "pop_bounce": lambda: _frames_pop_bounce(cat, text_layer, text_bbox),
        "slide_in":   lambda: _frames_slide_in(cat, text_layer, text_bbox, text_pos),
        "typewriter": lambda: _frames_typewriter(cat, text, text_pos, idx),
        "shake":      lambda: _frames_shake(cat, text_layer, text_bbox),
        "wave":       lambda: _frames_wave(cat, text, text_pos, idx),
    }
    frames, delays = dispatch.get(effect, dispatch["pop_bounce"])()

    _save_apng(frames, delays, out_path)
    return os.path.getsize(out_path) // 1024


def animate_all(theme, version, lang=None):
    """Process all stickers into animated APNGs."""
    paths = config.get_paths(theme, version)
    raw_dir = paths["raw"]
    ver_dir = config.get_version_dir(theme, version)

    if lang:
        out_dir = os.path.join(ver_dir, f"{lang}_anim")
        lang_prompts = os.path.join(ver_dir, lang, "prompts.json")
        prompts_file = lang_prompts if os.path.exists(lang_prompts) else config.get_prompts_file(theme, version)
    else:
        out_dir = os.path.join(ver_dir, "anim")
        prompts_file = config.get_prompts_file(theme, version)

    os.makedirs(out_dir, exist_ok=True)

    text_map = {}
    if os.path.exists(prompts_file):
        with open(prompts_file, "r", encoding="utf-8") as f:
            for s in json.load(f).get("stickers", []):
                text_map[s["id"]] = s.get("text", s.get("emotion", ""))

    raw_files, nobg_files = {}, {}
    for f in _glob.glob(os.path.join(raw_dir, "sticker_[0-9]*.png")):
        name = os.path.basename(f)
        if "_nobg" in name or "_raw" in name:
            continue
        try:
            raw_files[int(name.replace("sticker_", "").replace(".png", ""))] = f
        except ValueError:
            pass
    for f in _glob.glob(os.path.join(raw_dir, "sticker_*_nobg.png")):
        try:
            nobg_files[int(os.path.basename(f).split("_")[1])] = f
        except (IndexError, ValueError):
            pass

    indices = sorted(set(raw_files) | set(nobg_files))
    print(f"\nAnimating {len(indices)} stickers [{theme}/{version}]...\n")

    for idx in indices:
        text = text_map.get(idx, "")
        text_pos = "top" if idx % 2 == 1 else "bottom"
        effect = EMOTION_ANIMATION.get(text, DEFAULT_EFFECT)
        img = remove_background(raw_files.get(idx), nobg_files.get(idx))
        out_path = os.path.join(out_dir, f"sticker_{idx:02d}.apng")
        size_kb = animate_sticker(idx, img, text, text_pos, effect, out_path)
        print(f"  [#{idx:02d}] {text} ({effect}) → {size_kb}KB")

    print(f"\nDone! Output: {out_dir}")
