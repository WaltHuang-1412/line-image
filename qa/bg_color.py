"""Check background color is safe for bg removal.

Goal: background should have enough contrast with the character for clean bg removal.
Specifically reject:
- Near-white backgrounds (would clash with white cat face/belly)
- Near-grey backgrounds (would clash with grey cat body)
- Near-black backgrounds (would clash with pupils/outlines)

Implementation: pixel sampling only. No Ollama — Ollama is too strict about color
names (calls "pale orange" as "beige" and fails), but contrast is what matters
for bg removal, not the exact color name.
"""
import os
from PIL import Image


def _sample_corners(image_path):
    """Sample 4 corner pixels, return average RGB."""
    img = Image.open(image_path).convert("RGB")
    w, h = img.size
    m = 5
    corners = [
        img.getpixel((m, m)),
        img.getpixel((w - m, m)),
        img.getpixel((m, h - m)),
        img.getpixel((w - m, h - m)),
    ]
    return tuple(sum(c[i] for c in corners) // 4 for i in range(3))


def _is_near_white(rgb, threshold=235):
    return all(c > threshold for c in rgb)


def _is_near_black(rgb, threshold=40):
    return all(c < threshold for c in rgb)


def _is_greyish(rgb, tolerance=15):
    """All 3 channels within `tolerance` of each other = grey-ish."""
    r, g, b = rgb
    return max(r, g, b) - min(r, g, b) < tolerance


def check(image_path, emotion, character_desc, **kwargs):
    """Returns (passed: bool, detail: str)."""
    avg = _sample_corners(image_path)

    if _is_near_white(avg):
        return False, f"bg RGB{avg} is near-white — will clash with white cat face/belly"

    if _is_near_black(avg):
        return False, f"bg RGB{avg} is near-black — will clash with pupils/outlines"

    if _is_greyish(avg):
        return False, f"bg RGB{avg} is grey-ish — will clash with grey cat body"

    return True, f"bg RGB{avg} has sufficient color for bg removal"
