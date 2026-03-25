"""LINE Sticker Auto-Generation Configuration"""
import os

# === Paths ===
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
WORKFLOW_FILE = os.path.join(BASE_DIR, "workflow", "generate_with_sam.json")
REFERENCE_IMAGE = os.path.join(BASE_DIR, "v3.png")  # IP-Adapter reference image

# === ComfyUI ===
COMFYUI_URL = "http://127.0.0.1:8188"
COMFYUI_DIR = os.path.join(BASE_DIR, "ComfyUI")

# === Model ===
CHECKPOINT_NAME = "animagine-xl-3.1.safetensors"

# === IP-Adapter ===
IPADAPTER_PRESET = "STANDARD (medium strength)"
IPADAPTER_WEIGHT = 0.5
IPADAPTER_REFERENCE_IMAGE = "v3.png"  # filename as seen by ComfyUI

# === Generation ===
IMAGE_WIDTH = 1024
IMAGE_HEIGHT = 1024
STEPS = 28
CFG_SCALE = 7.0
SAMPLER = "euler_ancestral"
SCHEDULER = "normal"

NEGATIVE_PROMPT = (
    "lowres, bad anatomy, text, error, worst quality, low quality, "
    "jpeg artifacts, signature, watermark, blurry, multiple cats, "
    "realistic, human, humanoid, catgirl, anime girl, person, clothing, "
    "extra limbs, japanese text, kanji, hiragana, katakana"
)

# === LINE Sticker Specs ===
STICKER_MAX_W = 370
STICKER_MAX_H = 320
STICKER_MARGIN = 10       # px margin on each side when fitting subject
MAIN_IMAGE_SIZE = (240, 240)
TAB_IMAGE_SIZE = (96, 74)
MAX_FILE_SIZE_KB = 1000   # 1MB

# === SAM / Background Removal ===
# Content ratio below this threshold means SAM likely ate the subject (white cat issue).
# Fall back to flood-fill background removal in that case.
SAM_CONTENT_RATIO_MIN = 0.05   # at least 5% of pixels should be non-transparent after SAM

# Output structure per theme/version:
#
# output/{theme_name}/
# ├── prompts.json           (or v1/prompts.json, v2/prompts.json per version)
# └── v1/
#     ├── raw/              (raw sticker_*.png + sticker_nobg_*.png from ComfyUI)
#     ├── formatted/        (LINE-spec sticker_*.png, main.png, tab.png)
#     └── package/          (stickers.zip, metadata.json)


def get_theme_dir(theme):
    """Get the base directory for a theme."""
    return os.path.join(OUTPUT_DIR, theme)


def get_version_dir(theme, version):
    """Get the directory for a specific theme version."""
    return os.path.join(OUTPUT_DIR, theme, version)


def get_paths(theme, version):
    """Get all sub-directory paths for a specific theme/version."""
    ver_dir = get_version_dir(theme, version)
    return {
        "raw": os.path.join(ver_dir, "raw"),
        "formatted": os.path.join(ver_dir, "formatted"),
        "package": os.path.join(ver_dir, "package"),
    }


def get_prompts_file(theme, version=None):
    """Get the prompts.json path for a theme.

    Checks version-specific prompts first (output/{theme}/{version}/prompts.json),
    then falls back to the theme-level file (output/{theme}/prompts.json).
    """
    if version:
        ver_path = os.path.join(get_version_dir(theme, version), "prompts.json")
        if os.path.exists(ver_path):
            return ver_path
    return os.path.join(get_theme_dir(theme), "prompts.json")


def get_next_version(theme):
    """Auto-detect the next version number for a theme."""
    theme_dir = get_theme_dir(theme)
    if not os.path.exists(theme_dir):
        return "v1"
    existing = [
        d for d in os.listdir(theme_dir)
        if os.path.isdir(os.path.join(theme_dir, d)) and d.startswith("v")
    ]
    if not existing:
        return "v1"
    nums = []
    for d in existing:
        try:
            nums.append(int(d[1:]))
        except ValueError:
            pass
    return f"v{max(nums) + 1}" if nums else "v1"


def get_latest_version(theme):
    """Get the latest version directory for a theme, or None if none exist."""
    theme_dir = get_theme_dir(theme)
    if not os.path.exists(theme_dir):
        return None
    existing = [
        d for d in os.listdir(theme_dir)
        if os.path.isdir(os.path.join(theme_dir, d)) and d.startswith("v")
    ]
    if not existing:
        return None
    nums = []
    for d in existing:
        try:
            nums.append(int(d[1:]))
        except ValueError:
            pass
    return f"v{max(nums)}" if nums else None
