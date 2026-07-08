"""Check if the cat has unwanted white fur patches (model bias for dark long-haired cats).

Uses pixel sampling to detect bright white/cream areas on the cat body.
Background (purple/colored) is excluded by checking color channels.
"""
from PIL import Image
import numpy as np


def check(image_path, emotion, character_desc, **kwargs):
    """Returns (passed: bool, detail: str)."""
    img = Image.open(image_path).convert("RGBA")
    arr = np.array(img, dtype=np.float32)
    r, g, b, a = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2], arr[:, :, 3]

    # Cat pixels: visible (alpha > 200) and not purple background (r >= b * 0.75)
    is_cat = (a > 200) & (r >= b * 0.75)
    total_cat = np.sum(is_cat)

    if total_cat == 0:
        return True, "no cat pixels detected"

    # White/cream pixels: bright AND low saturation (not warm highlights)
    # Warm brown highlights have R >> G >> B (high saturation)
    # True white has R ≈ G ≈ B (low saturation)
    brightness = (r + g + b) / 3.0
    saturation = np.maximum(r, np.maximum(g, b)) - np.minimum(r, np.minimum(g, b))
    is_bright = brightness > 175
    is_desaturated = saturation < 50  # low color = grey/white, not warm brown
    is_white_ish = is_cat & is_bright & is_desaturated

    white_count = np.sum(is_white_ish)
    white_ratio = white_count / total_cat

    # More than 7% white on the cat body = FAIL
    if white_ratio > 0.07:
        return False, f"white fur detected: {white_ratio:.1%} of cat body is bright/white (threshold 8%)"

    return True, f"white fur ratio {white_ratio:.1%} OK"
