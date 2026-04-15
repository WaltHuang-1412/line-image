"""Package formatted emoji into a ZIP ready for LINE Creators Market upload.

Separate from package.py (which handles stickers).

LINE emoji spec differences vs sticker:
- Filenames: 001.png - 040.png (3-digit padding, not 2)
- No main.png (emoji bodies ARE the "main images")
- tab.png 96x74
- ZIP < 20MB
"""
import glob
import json
import os
import zipfile

import config


def create_package(theme, version, lang=None):
    """Create emoji ZIP: 001.png ~ NNN.png + tab.png.

    LINE Creators Market emoji upload rule: files numbered 001-040 (3 digits).
    """
    ver_dir = config.get_version_dir(theme, version)
    if lang:
        fmt_dir = os.path.join(ver_dir, lang)
        pkg_dir = os.path.join(ver_dir, lang, "package")
    else:
        paths = config.get_paths(theme, version)
        fmt_dir = paths["formatted"]
        pkg_dir = paths["package"]
    os.makedirs(pkg_dir, exist_ok=True)

    sticker_files = sorted(glob.glob(os.path.join(fmt_dir, "sticker_*.png")))
    tab_file = os.path.join(fmt_dir, "tab.png")

    if not sticker_files:
        print(f"No formatted emoji found in {fmt_dir}")
        return None

    title = theme
    desc = f"{theme} LINE Emoji Pack"
    prompts_file = config.get_prompts_file(theme, version)
    if os.path.exists(prompts_file):
        with open(prompts_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        title = data.get("title", title)
        desc = data.get("description", desc)

    zip_path = os.path.join(pkg_dir, "emoji.zip")

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        if os.path.exists(tab_file):
            zf.write(tab_file, "tab.png")
        for seq, sticker_path in enumerate(sticker_files, 1):
            zf.write(sticker_path, f"{seq:03d}.png")  # 3-digit padding

    files_meta = {
        "emoji": [f"{seq:03d}.png" for seq in range(1, len(sticker_files) + 1)],
    }
    if os.path.exists(tab_file):
        files_meta["tab"] = "tab.png"

    metadata = {
        "theme": theme,
        "version": version,
        "title": title,
        "description": desc,
        "type": "emoji",
        "emoji_count": len(sticker_files),
        "files": files_meta,
    }

    meta_path = os.path.join(pkg_dir, "metadata.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)

    size_kb = os.path.getsize(zip_path) // 1024
    print(f"\nEmoji package created [{theme}/{version}]:")
    print(f"  ZIP:      {zip_path} ({size_kb}KB)")
    print(f"  Emoji:    {len(sticker_files)} (named 001-{len(sticker_files):03d})")
    print(f"  Metadata: {meta_path}")
    print(f"\nUpload to: https://creator.line.me/")

    return zip_path


if __name__ == "__main__":
    import sys
    theme = sys.argv[1] if len(sys.argv) > 1 else "default"
    version = sys.argv[2] if len(sys.argv) > 2 else config.get_latest_version(theme) or "v1"
    lang = None
    if "--lang" in sys.argv:
        lang = sys.argv[sys.argv.index("--lang") + 1]
    create_package(theme, version, lang=lang)
