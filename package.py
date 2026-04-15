"""Package formatted stickers into a ZIP ready for LINE Creators Market upload."""
import glob
import json
import os
import zipfile

import config


def create_package(theme, version, lang=None):
    """Create a ZIP file with all formatted stickers + metadata.

    Reads from:  output/{theme}/{version}/{lang}/ (if lang given)
                 output/{theme}/{version}/formatted/ (fallback)
    Writes to:   output/{theme}/{version}/{lang}/package/ (if lang given)
                 output/{theme}/{version}/package/ (fallback)

    The ZIP contains:
      main.png        - cover image (240x240)
      tab.png         - tab image (96x74)
      01.png ... NN.png - sticker images (370x320), numbered sequentially
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
    main_file = os.path.join(fmt_dir, "main.png")
    tab_file = os.path.join(fmt_dir, "tab.png")

    if not sticker_files:
        print(f"No formatted stickers found in {fmt_dir}")
        return None

    # Load title/description from prompts file
    title = theme
    desc = f"{theme} LINE Sticker Pack"
    prompts_file = config.get_prompts_file(theme, version)
    if os.path.exists(prompts_file):
        with open(prompts_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        title = data.get("title", title)
        desc = data.get("description", desc)

    zip_path = os.path.join(pkg_dir, "stickers.zip")

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        if os.path.exists(main_file):
            zf.write(main_file, "main.png")
        if os.path.exists(tab_file):
            zf.write(tab_file, "tab.png")
        for seq, sticker_path in enumerate(sticker_files, 1):
            zf.write(sticker_path, f"{seq:02d}.png")

    files_meta = {
        "stickers": [f"{seq:02d}.png" for seq in range(1, len(sticker_files) + 1)],
    }
    if os.path.exists(main_file):
        files_meta["main"] = "main.png"
    if os.path.exists(tab_file):
        files_meta["tab"] = "tab.png"

    metadata = {
        "theme": theme,
        "version": version,
        "title": title,
        "description": desc,
        "sticker_count": len(sticker_files),
        "files": files_meta,
    }

    meta_path = os.path.join(pkg_dir, "metadata.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)

    size_kb = os.path.getsize(zip_path) // 1024
    print(f"\nPackage created [{theme}/{version}]:")
    print(f"  ZIP:      {zip_path} ({size_kb}KB)")
    print(f"  Stickers: {len(sticker_files)}")
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
