"""Format generated images to LINE sticker specifications.

Pipeline per sticker:
  1. Prefer the SAM-segmented *_nobg.png produced by ComfyUI.
  2. If SAM ate too much of the subject (content ratio below threshold),
     fall back to flood-fill background removal on the *_raw.png.
  3. Resize result to LINE sticker canvas (370x320) with 10px margin.
  4. Save sticker_XX.png to formatted/.
  5. For the first sticker, also create main.png (240x240) and tab.png (96x74).
"""
import glob
import json
import os
from io import BytesIO

import numpy as np
from PIL import Image, ImageDraw, ImageFont

import config


# ---------------------------------------------------------------------------
# Text overlay
# ---------------------------------------------------------------------------

TEXT_FONT_HUNINN = os.path.join(os.path.dirname(__file__), "fonts", "jf-openhuninn-2.1.ttf")
TEXT_FONT_BOLD = "msjhbd.ttc"   # Microsoft JhengHei Bold (fallback)
TEXT_FONT_REGULAR = "msjh.ttc"

# Text style — warm dark brown + thick white stroke for hand-drawn feel
TEXT_FILL = (75, 55, 45, 255)
TEXT_STROKE = (255, 255, 255, 255)
TEXT_STROKE_WIDTH = 6

# Small decorative marks per emotion (CJK-safe characters only)
EMOTION_DECO = {
    # v1-v3 emotions
    "嘻嘻": "～",   "才怪": "！",   "干你事": "",     "嘴嘴": "～",
    "你誰": "？",   "回我": "！！", "哼": "！",       "吵屁": "！",
    "略略": "～",   "滾": "！",    "識相": "～",      "欠揍": "！",
    "切": "～",     "煩欸": "…",   "比心": "～",      "愛你屁": "！", "才不要": "！",
    # v4 food emotions
    "好餓": "…",    "吃什麼": "？", "開動": "！",      "太好吃": "～",
    "再一口": "～",  "吃飽了": "～", "不夠吃": "！",    "是我的": "！",
    "宵夜": "～",   "減肥": "！",   "明天再說": "～",   "外送到了": "！",
    "請客": "～",   "我請你": "！", "甜點胃": "～",    "打包": "！",
}

# Slight horizontal offset per sticker for variety (-1=left, 0=center, 1=right)
TEXT_OFFSET = {
    1: -12, 2: 8, 3: -6, 4: 10, 5: -8, 6: 6, 7: -10, 8: 12,
    9: -6, 10: 8, 11: -12, 12: 10, 13: -8, 14: 6, 15: -10, 16: 12,
}


def _get_font(size):
    """Load Chinese font — prefer huninn (hand-drawn round), fallback to system."""
    for name in [TEXT_FONT_HUNINN, TEXT_FONT_BOLD, TEXT_FONT_REGULAR]:
        try:
            return ImageFont.truetype(name, size)
        except (OSError, IOError):
            continue
    return ImageFont.load_default()


def add_text_overlay(canvas, text, position="bottom", sticker_id=1):
    """Draw text on the sticker canvas with decorative marks and slight offset."""
    if not text:
        return canvas

    result = canvas.copy()
    draw = ImageDraw.Draw(result)

    # Add decorative mark
    deco = EMOTION_DECO.get(text, "")
    display_text = text + deco

    # Font size — bigger for fewer chars (based on original text, not deco)
    if len(text) <= 1:
        font_size = 64
    elif len(text) <= 2:
        font_size = 58
    elif len(text) <= 3:
        font_size = 50
    elif len(text) <= 5:
        font_size = 44
    else:
        font_size = 38

    font = _get_font(font_size)

    # Measure
    bbox = draw.textbbox((0, 0), display_text, font=font, stroke_width=TEXT_STROKE_WIDTH)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]

    # Horizontal: center + slight offset for variety
    offset_x = TEXT_OFFSET.get(sticker_id, 0)
    x = (canvas.width - text_w) // 2 + offset_x
    x = max(4, min(x, canvas.width - text_w - 4))  # clamp

    # Vertical: overlap into cat area for an integrated hand-drawn feel
    if position == "top":
        y = 2
    else:
        y = canvas.height - text_h - 4

    # Drop shadow
    shadow_offset = 2
    draw.text((x + shadow_offset, y + shadow_offset), display_text, font=font,
              fill=(0, 0, 0, 40),
              stroke_width=TEXT_STROKE_WIDTH,
              stroke_fill=(0, 0, 0, 0))

    # Main text
    draw.text((x, y), display_text, font=font,
              fill=TEXT_FILL,
              stroke_width=TEXT_STROKE_WIDTH,
              stroke_fill=TEXT_STROKE)

    return result


# ---------------------------------------------------------------------------
# Background removal helpers
# ---------------------------------------------------------------------------

def _content_ratio(img_rgba):
    """Return the fraction of pixels that are non-transparent (alpha > 10)."""
    arr = np.array(img_rgba)
    if arr.shape[2] < 4:
        return 1.0  # no alpha channel means fully opaque
    return float(np.sum(arr[:, :, 3] > 10)) / (arr.shape[0] * arr.shape[1])


def flood_fill_remove_bg(img_rgba, tolerance=30):
    """Remove background using flood fill from all four corners.

    Works by finding connected corner pixels whose color is close to the
    seed corner color, then setting them transparent.  More robust than
    rembg for white/light subjects when SAM has failed.

    Args:
        img_rgba: PIL RGBA image.
        tolerance: Color distance tolerance for flood fill.

    Returns:
        New RGBA PIL image with background removed.
    """
    img = img_rgba.convert("RGBA")
    arr = np.array(img, dtype=np.int32)
    h, w = arr.shape[:2]
    alpha = np.ones((h, w), dtype=bool)  # True = keep (foreground)

    # We'll fill from each corner seed
    seeds = [(0, 0), (0, w - 1), (h - 1, 0), (h - 1, w - 1)]

    for sy, sx in seeds:
        seed_color = arr[sy, sx, :3]
        visited = np.zeros((h, w), dtype=bool)
        stack = [(sy, sx)]
        while stack:
            y, x = stack.pop()
            if y < 0 or y >= h or x < 0 or x >= w:
                continue
            if visited[y, x]:
                continue
            visited[y, x] = True
            diff = np.abs(arr[y, x, :3] - seed_color)
            if np.max(diff) <= tolerance:
                alpha[y, x] = False  # mark as background
                stack.extend([(y + 1, x), (y - 1, x), (y, x + 1), (y, x - 1)])

    result = img_rgba.convert("RGBA").copy()
    result_arr = np.array(result)
    result_arr[:, :, 3] = np.where(alpha, result_arr[:, :, 3], 0)
    return Image.fromarray(result_arr.astype(np.uint8), "RGBA")


def remove_background(raw_path, nobg_path):
    """Decide which background-removal strategy to use and return an RGBA image.

    Prefers the SAM nobg image.  Falls back to flood fill if SAM ate too much.

    Args:
        raw_path: Path to the raw (with background) PNG.
        nobg_path: Path to the SAM-processed transparent PNG (may be None).

    Returns:
        PIL RGBA image with background removed.
    """
    # Try SAM result first
    if nobg_path and os.path.exists(nobg_path):
        sam_img = Image.open(nobg_path).convert("RGBA")
        ratio = _content_ratio(sam_img)
        if ratio >= config.SAM_CONTENT_RATIO_MIN:
            return sam_img
        print(f"    SAM content ratio too low ({ratio:.2%}), falling back to flood fill.")

    # Fallback: flood fill on raw image
    if raw_path and os.path.exists(raw_path):
        raw_img = Image.open(raw_path).convert("RGBA")
        print(f"    Applying flood-fill background removal...")
        return flood_fill_remove_bg(raw_img)

    raise FileNotFoundError(
        f"Neither raw nor nobg image available: raw={raw_path}, nobg={nobg_path}"
    )


# ---------------------------------------------------------------------------
# Resizing helpers
# ---------------------------------------------------------------------------

def _fit_on_canvas(img_rgba, canvas_w, canvas_h, margin=config.STICKER_MARGIN):
    """Fit img_rgba inside a canvas of (canvas_w x canvas_h) with given margin.

    The subject is scaled to fit within the inner area (canvas minus margins)
    and centered.  The canvas background is transparent.
    """
    inner_w = canvas_w - margin * 2
    inner_h = canvas_h - margin * 2

    w, h = img_rgba.size
    scale = min(inner_w / w, inner_h / h)
    new_w = max(1, int(w * scale))
    new_h = max(1, int(h * scale))

    resized = img_rgba.resize((new_w, new_h), Image.LANCZOS)
    canvas = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
    x = (canvas_w - new_w) // 2
    y = (canvas_h - new_h) // 2
    canvas.paste(resized, (x, y), resized)
    return canvas


def _detect_content_center(img_rgba):
    """Return the vertical center of mass of non-transparent pixels (0.0=top, 1.0=bottom)."""
    arr = np.array(img_rgba)
    if arr.shape[2] < 4:
        return 0.5
    alpha = arr[:, :, 3]
    rows = np.where(alpha > 10)[0]
    if len(rows) == 0:
        return 0.5
    return float(np.mean(rows)) / arr.shape[0]


def resize_to_sticker(img_rgba, text=None, text_pos="bottom"):
    """Resize to LINE sticker canvas (370x320).

    If text is provided, shrink cat and place it opposite to text_pos.
    """
    if text:
        margin = config.STICKER_MARGIN
        canvas_w = config.STICKER_MAX_W
        canvas_h = config.STICKER_MAX_H
        inner_w = canvas_w - margin * 2
        inner_h = int((canvas_h - margin * 2) * 0.82)

        w, h = img_rgba.size
        scale = min(inner_w / w, inner_h / h)
        new_w = max(1, int(w * scale))
        new_h = max(1, int(h * scale))

        resized = img_rgba.resize((new_w, new_h), Image.LANCZOS)
        canvas = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
        x = (canvas_w - new_w) // 2

        if text_pos == "top":
            # Text on top → cat goes to bottom
            y = canvas_h - new_h - margin
        else:
            # Text on bottom → cat goes to top
            y = margin

        canvas.paste(resized, (x, y), resized)
        return canvas
    else:
        return _fit_on_canvas(img_rgba, config.STICKER_MAX_W, config.STICKER_MAX_H, config.STICKER_MARGIN)


def create_main_image(img_rgba):
    """Resize to LINE main image (240x240)."""
    return _fit_on_canvas(img_rgba, config.MAIN_IMAGE_SIZE[0], config.MAIN_IMAGE_SIZE[1], config.STICKER_MARGIN)


def create_tab_image(img_rgba):
    """Resize to LINE tab image (96x74)."""
    return _fit_on_canvas(img_rgba, config.TAB_IMAGE_SIZE[0], config.TAB_IMAGE_SIZE[1], 4)


# ---------------------------------------------------------------------------
# PNG optimization
# ---------------------------------------------------------------------------

def optimize_png(img, max_size_kb=config.MAX_FILE_SIZE_KB):
    """Save image as optimized PNG bytes, downscaling if over size limit."""
    buf = BytesIO()
    img.save(buf, format="PNG", optimize=True)
    if buf.tell() <= max_size_kb * 1024:
        return buf.getvalue()
    # Iteratively downscale
    scale = 0.9
    while buf.tell() > max_size_kb * 1024 and scale > 0.3:
        new_size = (max(1, int(img.width * scale)), max(1, int(img.height * scale)))
        shrunk = img.resize(new_size, Image.LANCZOS)
        buf = BytesIO()
        shrunk.save(buf, format="PNG", optimize=True)
        scale -= 0.1
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Main format pass
# ---------------------------------------------------------------------------

def format_all(theme, version):
    """Process all raw images into LINE-ready stickers.

    Looks for pairs of:
      raw/sticker_{N:02d}_raw.png   - with background
      raw/sticker_{N:02d}_nobg.png  - SAM-segmented (preferred)

    Also accepts the old naming convention (sticker_{N:02d}.png) for
    backwards compatibility with existing raw directories.

    Outputs:
      formatted/sticker_{N:02d}.png  - LINE sticker (370x320)
      formatted/main.png             - cover image (240x240), from sticker #1
      formatted/tab.png              - tab image (96x74), from sticker #1
    """
    paths = config.get_paths(theme, version)
    raw_dir = paths["raw"]
    fmt_dir = paths["formatted"]
    os.makedirs(fmt_dir, exist_ok=True)

    # Collect sticker indices from raw directory
    nobg_files = sorted(glob.glob(os.path.join(raw_dir, "sticker_*_nobg.png")))
    raw_files = sorted(glob.glob(os.path.join(raw_dir, "sticker_*_raw.png")))
    legacy_files = sorted(glob.glob(os.path.join(raw_dir, "sticker_[0-9]*.png")))

    # Build index → (raw_path, nobg_path) mapping
    index_map = {}

    for f in raw_files:
        name = os.path.basename(f)
        # e.g. sticker_01_raw.png
        try:
            idx = int(name.split("_")[1])
            index_map.setdefault(idx, {})["raw"] = f
        except (IndexError, ValueError):
            pass

    for f in nobg_files:
        name = os.path.basename(f)
        try:
            idx = int(name.split("_")[1])
            index_map.setdefault(idx, {})["nobg"] = f
        except (IndexError, ValueError):
            pass

    # Legacy: sticker_01.png style (no suffix)
    for f in legacy_files:
        name = os.path.basename(f)
        if "_raw" in name or "_nobg" in name:
            continue
        try:
            idx = int(name.replace("sticker_", "").replace(".png", ""))
            index_map.setdefault(idx, {})["raw"] = f
        except ValueError:
            pass

    if not index_map:
        print(f"No raw sticker images found in {raw_dir}")
        return

    # Load prompts.json for text overlay
    prompts_file = config.get_prompts_file(theme, version)
    text_map = {}
    if os.path.exists(prompts_file):
        with open(prompts_file, "r", encoding="utf-8") as pf:
            pdata = json.load(pf)
        for s in pdata.get("stickers", []):
            sid = s.get("id")
            text_map[sid] = s.get("text", s.get("emotion", ""))

    indices = sorted(index_map.keys())
    print(f"\nFormatting {len(indices)} stickers for [{theme}/{version}]...\n")

    for i, idx in enumerate(indices):
        entry = index_map[idx]
        raw_path = entry.get("raw")
        nobg_path = entry.get("nobg")

        print(f"  [#{idx:02d}] Removing background...")
        img = remove_background(raw_path, nobg_path)

        text = text_map.get(idx, "")
        text_pos = "top" if idx % 2 == 1 else "bottom"
        sticker = resize_to_sticker(img, text=text, text_pos=text_pos)
        if text:
            sticker = add_text_overlay(sticker, text, position=text_pos, sticker_id=idx)
            print(f"  [#{idx:02d}] Text overlay: {text} ({text_pos})")
        sticker_data = optimize_png(sticker)
        sticker_path = os.path.join(fmt_dir, f"sticker_{idx:02d}.png")
        with open(sticker_path, "wb") as f_out:
            f_out.write(sticker_data)
        print(f"  [#{idx:02d}] Saved sticker ({len(sticker_data) // 1024}KB): {sticker_path}")

        # Create main.png and tab.png from the first sticker
        if i == 0:
            main_img = create_main_image(img)
            main_data = optimize_png(main_img)
            with open(os.path.join(fmt_dir, "main.png"), "wb") as f_out:
                f_out.write(main_data)

            tab_img = create_tab_image(img)
            tab_data = optimize_png(tab_img)
            with open(os.path.join(fmt_dir, "tab.png"), "wb") as f_out:
                f_out.write(tab_data)

            print(f"  [#{idx:02d}] main.png and tab.png saved.")

    print(f"\nDone! Formatted stickers in {fmt_dir}")


if __name__ == "__main__":
    import sys
    theme = sys.argv[1] if len(sys.argv) > 1 else "default"
    version = sys.argv[2] if len(sys.argv) > 2 else config.get_latest_version(theme) or "v1"
    format_all(theme, version)
