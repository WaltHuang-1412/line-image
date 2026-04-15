"""Format emoji images to LINE emoji spec (180x180, no margin, no text).

Shares low-level helpers with format_stickers.py but keeps the emoji flow
fully isolated so changes to either flow don't affect the other.
"""
import glob
import json
import os

from format_stickers import remove_background, optimize_png, _fit_on_canvas
import config


# LINE emoji spec
# emoji 沒有獨立 240x240 main image（sticker 才有）
# 表情貼本體（180x180 x 16-40 張）就是「主要圖片」
EMOJI_CANVAS = (180, 180)
EMOJI_MARGIN = 0
EMOJI_TAB_SIZE = (96, 74)
EMOJI_MAX_FILE_SIZE_KB = 1000


def format_all(theme, version, lang=None):
    """Format all emoji raw images to LINE emoji spec.

    Looks for sticker_{N:02d}_nobg.png (preferred) or sticker_{N:02d}.png in raw/.
    Outputs to {version}/formatted/ (or {version}/{lang}/ if lang given).
    """
    paths = config.get_paths(theme, version)
    raw_dir = paths["raw"]
    if lang:
        ver_dir = config.get_version_dir(theme, version)
        fmt_dir = os.path.join(ver_dir, lang)
    else:
        fmt_dir = paths["formatted"]
    os.makedirs(fmt_dir, exist_ok=True)

    # Index raw + nobg files
    nobg_files = sorted(glob.glob(os.path.join(raw_dir, "sticker_*_nobg.png")))
    legacy_files = sorted(glob.glob(os.path.join(raw_dir, "sticker_[0-9]*.png")))

    index_map = {}
    for f in nobg_files:
        try:
            idx = int(os.path.basename(f).split("_")[1])
            index_map.setdefault(idx, {})["nobg"] = f
        except (IndexError, ValueError):
            pass
    for f in legacy_files:
        name = os.path.basename(f)
        if "_nobg" in name or "_raw" in name:
            continue
        try:
            idx = int(name.replace("sticker_", "").replace(".png", ""))
            index_map.setdefault(idx, {})["raw"] = f
        except ValueError:
            pass

    if not index_map:
        print(f"No raw emoji images found in {raw_dir}")
        return

    indices = sorted(index_map.keys())
    print(f"\nFormatting {len(indices)} emoji for [{theme}/{version}] ({EMOJI_CANVAS[0]}x{EMOJI_CANVAS[1]})...\n")

    for i, idx in enumerate(indices):
        entry = index_map[idx]
        raw_path = entry.get("raw")
        nobg_path = entry.get("nobg")

        print(f"  [#{idx:02d}] Removing background...")
        img = remove_background(raw_path, nobg_path)

        emoji_img = _fit_on_canvas(img, EMOJI_CANVAS[0], EMOJI_CANVAS[1], EMOJI_MARGIN)
        emoji_data = optimize_png(emoji_img, max_size_kb=EMOJI_MAX_FILE_SIZE_KB)
        emoji_path = os.path.join(fmt_dir, f"sticker_{idx:02d}.png")
        with open(emoji_path, "wb") as f_out:
            f_out.write(emoji_data)
        print(f"  [#{idx:02d}] Saved emoji ({len(emoji_data) // 1024}KB, {EMOJI_CANVAS[0]}x{EMOJI_CANVAS[1]}): {emoji_path}")

        # tab image from first emoji (emoji has no separate main image)
        if i == 0:
            tab_img = _fit_on_canvas(img, EMOJI_TAB_SIZE[0], EMOJI_TAB_SIZE[1], 4)
            tab_data = optimize_png(tab_img, max_size_kb=EMOJI_MAX_FILE_SIZE_KB)
            with open(os.path.join(fmt_dir, "tab.png"), "wb") as f_out:
                f_out.write(tab_data)
            print(f"  [#{idx:02d}] tab.png saved.")

    print(f"\nDone! Formatted emoji in {fmt_dir}")


if __name__ == "__main__":
    import sys
    theme = sys.argv[1] if len(sys.argv) > 1 else "default"
    version = sys.argv[2] if len(sys.argv) > 2 else config.get_latest_version(theme) or "v1"
    format_all(theme, version)
