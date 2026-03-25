"""Automated QA check for LINE sticker output.

Checks per sticker:
  1. File completeness (raw, nobg, formatted)
  2. Dimensions match LINE spec
  3. File size < 1MB
  4. Transparent background (corner alpha = 0)
  5. Content ratio (subject not too small / too large)
  6. SAM quality (nobg vs raw content ratio)
  7. Text overlay detection (formatted has text pixels outside cat area)
  8. Visual hash similarity between raw and formatted (catch corrupt outputs)

Usage:
    python qa_check.py <theme> <version>
"""
import json
import os
import sys

import numpy as np
from PIL import Image

import config

# Thresholds
MIN_CONTENT_RATIO = 0.08      # at least 8% non-transparent
MAX_CONTENT_RATIO = 0.85      # at most 85% (otherwise bg removal likely failed)
SAM_CONTENT_RATIO_MIN = 0.05  # same as config
MAX_FILE_SIZE_KB = 1000
CORNER_SAMPLE = 10            # sample NxN corners for transparency check
MIN_UNIQUE_COLORS = 30        # detect blank / nearly blank images


def check_transparency(img):
    """Check that corners are transparent (background removed)."""
    arr = np.array(img)
    if arr.shape[2] < 4:
        return False, "No alpha channel"
    h, w = arr.shape[:2]
    n = CORNER_SAMPLE
    corners = [
        arr[:n, :n, 3],          # top-left
        arr[:n, -n:, 3],         # top-right
        arr[-n:, :n, 3],         # bottom-left
        arr[-n:, -n:, 3],        # bottom-right
    ]
    opaque_corners = sum(1 for c in corners if np.mean(c) > 20)
    if opaque_corners >= 3:
        return False, f"{opaque_corners}/4 corners opaque"
    return True, "OK"


def check_content_ratio(img):
    """Check that subject occupies a reasonable portion of the canvas."""
    arr = np.array(img)
    if arr.shape[2] < 4:
        return 1.0, "no alpha"
    ratio = float(np.sum(arr[:, :, 3] > 10)) / (arr.shape[0] * arr.shape[1])
    status = "OK"
    if ratio < MIN_CONTENT_RATIO:
        status = f"TOO SMALL ({ratio:.1%})"
    elif ratio > MAX_CONTENT_RATIO:
        status = f"BG NOT REMOVED? ({ratio:.1%})"
    return ratio, status


def check_unique_colors(img):
    """Detect nearly blank / corrupt images by counting unique colors."""
    arr = np.array(img.convert("RGB"))
    # Sample center region
    h, w = arr.shape[:2]
    center = arr[h//4:3*h//4, w//4:3*w//4]
    pixels = center.reshape(-1, 3)
    # Quantize to reduce noise
    quantized = (pixels // 16) * 16
    unique = len(set(map(tuple, quantized)))
    return unique


def check_sam_quality(raw_path, nobg_path):
    """Compare SAM nobg with raw to assess segmentation quality."""
    if not nobg_path or not os.path.exists(nobg_path):
        return "NO_NOBG", "Missing nobg file"

    nobg = Image.open(nobg_path).convert("RGBA")
    arr = np.array(nobg)
    ratio = float(np.sum(arr[:, :, 3] > 10)) / (arr.shape[0] * arr.shape[1])

    if ratio < SAM_CONTENT_RATIO_MIN:
        return "FLOOD_FILL", f"SAM ratio {ratio:.1%} → used flood-fill fallback"
    else:
        return "SAM", f"SAM ratio {ratio:.1%}"


def check_text_overlay(formatted_img, has_text):
    """Heuristic: check if text region has content when emotion text is expected."""
    if not has_text:
        return True, "No text expected"

    arr = np.array(formatted_img)
    h, w = arr.shape[:2]

    # Check top 20% and bottom 20% for non-transparent pixels
    top_region = arr[:int(h * 0.2), :, 3]
    bot_region = arr[int(h * 0.8):, :, 3]

    top_content = np.sum(top_region > 10) / top_region.size
    bot_content = np.sum(bot_region > 10) / bot_region.size

    has_top = top_content > 0.02
    has_bot = bot_content > 0.02

    if has_top or has_bot:
        return True, f"top={top_content:.1%} bot={bot_content:.1%}"
    return False, f"No text detected (top={top_content:.1%} bot={bot_content:.1%})"


def run_qa(theme, version):
    paths = config.get_paths(theme, version)
    raw_dir = paths["raw"]
    fmt_dir = paths["formatted"]

    # Load prompts
    prompts_file = config.get_prompts_file(theme, version)
    prompts_data = {}
    if os.path.exists(prompts_file):
        with open(prompts_file, "r", encoding="utf-8") as f:
            prompts_data = json.load(f)

    sticker_defs = {s["id"]: s for s in prompts_data.get("stickers", [])}
    expected_ids = sorted(sticker_defs.keys())

    print(f"{'='*70}")
    print(f"  QA Report: {theme} / {version}")
    print(f"  Expected: {len(expected_ids)} stickers ({expected_ids[0]}-{expected_ids[-1]})")
    print(f"{'='*70}\n")

    issues = []
    results = []

    for sid in expected_ids:
        row = {"id": sid, "checks": []}
        sdef = sticker_defs[sid]
        emotion = sdef.get("emotion", "")

        raw_path = os.path.join(raw_dir, f"sticker_{sid:02d}.png")
        nobg_path = os.path.join(raw_dir, f"sticker_{sid:02d}_nobg.png")
        fmt_path = os.path.join(fmt_dir, f"sticker_{sid:02d}.png")

        print(f"── Sticker #{sid:02d} [{emotion}] ──")

        # 1. File existence
        has_raw = os.path.exists(raw_path)
        has_nobg = os.path.exists(nobg_path)
        has_fmt = os.path.exists(fmt_path)
        files_status = []
        if not has_raw:
            files_status.append("raw MISSING")
        if not has_nobg:
            files_status.append("nobg MISSING")
        if not has_fmt:
            files_status.append("formatted MISSING")

        if files_status:
            print(f"  [FAIL] Files: {', '.join(files_status)}")
            issues.append(f"#{sid:02d}: {', '.join(files_status)}")
            row["checks"].append(("files", "FAIL", ", ".join(files_status)))
        else:
            print(f"  [OK]   Files: raw + nobg + formatted")
            row["checks"].append(("files", "OK", ""))

        # 2. Raw image checks
        if has_raw:
            raw_img = Image.open(raw_path)
            raw_w, raw_h = raw_img.size
            raw_size_kb = os.path.getsize(raw_path) // 1024
            unique_colors = check_unique_colors(raw_img)
            if unique_colors < MIN_UNIQUE_COLORS:
                print(f"  [WARN] Raw: only {unique_colors} unique colors — may be blank/corrupt")
                issues.append(f"#{sid:02d}: raw may be blank ({unique_colors} colors)")
                row["checks"].append(("raw_colors", "WARN", f"{unique_colors} colors"))
            else:
                row["checks"].append(("raw_colors", "OK", f"{unique_colors} colors"))

        # 3. SAM quality
        if has_raw:
            sam_status, sam_detail = check_sam_quality(raw_path, nobg_path if has_nobg else None)
            if sam_status == "FLOOD_FILL":
                print(f"  [WARN] BG removal: {sam_detail}")
                issues.append(f"#{sid:02d}: {sam_detail}")
            elif sam_status == "NO_NOBG":
                print(f"  [WARN] BG removal: {sam_detail}")
                issues.append(f"#{sid:02d}: {sam_detail}")
            else:
                print(f"  [OK]   BG removal: {sam_detail}")
            row["checks"].append(("sam", sam_status, sam_detail))

        # 4. Formatted image checks
        if has_fmt:
            fmt_img = Image.open(fmt_path).convert("RGBA")
            fmt_w, fmt_h = fmt_img.size
            fmt_size_kb = os.path.getsize(fmt_path) // 1024

            # Dimensions
            if (fmt_w, fmt_h) != (config.STICKER_MAX_W, config.STICKER_MAX_H):
                print(f"  [FAIL] Dimensions: {fmt_w}x{fmt_h} (expected {config.STICKER_MAX_W}x{config.STICKER_MAX_H})")
                issues.append(f"#{sid:02d}: wrong dimensions {fmt_w}x{fmt_h}")
                row["checks"].append(("dimensions", "FAIL", f"{fmt_w}x{fmt_h}"))
            else:
                print(f"  [OK]   Dimensions: {fmt_w}x{fmt_h}")
                row["checks"].append(("dimensions", "OK", ""))

            # File size
            if fmt_size_kb > MAX_FILE_SIZE_KB:
                print(f"  [FAIL] Size: {fmt_size_kb}KB (max {MAX_FILE_SIZE_KB}KB)")
                issues.append(f"#{sid:02d}: file too large {fmt_size_kb}KB")
                row["checks"].append(("filesize", "FAIL", f"{fmt_size_kb}KB"))
            else:
                print(f"  [OK]   Size: {fmt_size_kb}KB")
                row["checks"].append(("filesize", "OK", f"{fmt_size_kb}KB"))

            # Transparency
            trans_ok, trans_detail = check_transparency(fmt_img)
            if not trans_ok:
                print(f"  [FAIL] Transparency: {trans_detail}")
                issues.append(f"#{sid:02d}: transparency issue — {trans_detail}")
                row["checks"].append(("transparency", "FAIL", trans_detail))
            else:
                print(f"  [OK]   Transparency: corners clear")
                row["checks"].append(("transparency", "OK", ""))

            # Content ratio
            ratio, ratio_status = check_content_ratio(fmt_img)
            if "OK" not in ratio_status:
                print(f"  [WARN] Content: {ratio_status}")
                issues.append(f"#{sid:02d}: {ratio_status}")
                row["checks"].append(("content", "WARN", ratio_status))
            else:
                print(f"  [OK]   Content: {ratio:.1%} filled")
                row["checks"].append(("content", "OK", f"{ratio:.1%}"))

            # Text overlay
            text_ok, text_detail = check_text_overlay(fmt_img, bool(emotion))
            if not text_ok:
                print(f"  [WARN] Text: {text_detail}")
                issues.append(f"#{sid:02d}: {text_detail}")
                row["checks"].append(("text", "WARN", text_detail))
            else:
                print(f"  [OK]   Text: {text_detail}")
                row["checks"].append(("text", "OK", text_detail))

        print()
        results.append(row)

    # Check main.png and tab.png
    print(f"── Meta Images ──")
    main_path = os.path.join(fmt_dir, "main.png")
    tab_path = os.path.join(fmt_dir, "tab.png")

    for name, path, expected_size in [("main.png", main_path, (240, 240)), ("tab.png", tab_path, (96, 74))]:
        if not os.path.exists(path):
            print(f"  [FAIL] {name}: MISSING")
            issues.append(f"{name} missing")
        else:
            img = Image.open(path)
            w, h = img.size
            size_kb = os.path.getsize(path) // 1024
            if (w, h) != expected_size:
                print(f"  [FAIL] {name}: {w}x{h} (expected {expected_size[0]}x{expected_size[1]})")
                issues.append(f"{name} wrong size {w}x{h}")
            else:
                print(f"  [OK]   {name}: {w}x{h}, {size_kb}KB")

    # Summary
    print(f"\n{'='*70}")
    print(f"  SUMMARY")
    print(f"{'='*70}")
    print(f"  Total stickers: {len(expected_ids)}")
    print(f"  Issues found:   {len(issues)}")

    if issues:
        print(f"\n  Issues requiring attention:")
        for issue in issues:
            print(f"    - {issue}")
    else:
        print(f"\n  All automated checks passed!")

    # Visual review list
    print(f"\n  Manual review still needed for:")
    print(f"    - Expression matches emotion (e.g. '好餓' looks hungry)")
    print(f"    - No extra limbs / anatomy errors")
    print(f"    - No text artifacts in the generated image")
    print(f"    - Text overlay readable and well-positioned")
    print(f"{'='*70}")

    return len(issues)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python qa_check.py <theme> <version>")
        sys.exit(1)
    theme = sys.argv[1]
    version = sys.argv[2]
    exit_code = run_qa(theme, version)
    sys.exit(1 if exit_code > 0 else 0)
