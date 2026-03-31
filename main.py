"""LINE Sticker Auto-Generation Pipeline — unified CLI.

Usage:
    python main.py generate <theme> [version]          Generate stickers via ComfyUI
    python main.py format  <theme> <version>           Format/resize to LINE spec
    python main.py package <theme> <version>           Package into ZIP
    python main.py all     <theme> [version]           Run full pipeline (generate → format → package)
    python main.py list                                List all themes and versions
    python main.py fix     <theme> <version> <ids...>  Regenerate specific sticker IDs

Examples:
    python main.py all 圓滾貓的日常
    python main.py all 圓滾貓的日常 v2
    python main.py generate 圓滾貓的日常 v3
    python main.py format 圓滾貓的日常 v1
    python main.py package 圓滾貓的日常 v1
    python main.py fix 圓滾貓的日常 v2 3 7 12
    python main.py list
"""
import json
import os
import sys
import urllib.request

import config


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def check_comfyui():
    """Return True if ComfyUI is reachable, else print an error and return False."""
    try:
        resp = urllib.request.urlopen(f"{config.COMFYUI_URL}/system_stats", timeout=5)
        data = json.loads(resp.read())
        gpu = data.get("devices", [{}])[0].get("name", "unknown")
        print(f"ComfyUI is running [{gpu}]")
        return True
    except Exception:
        print(f"ERROR: ComfyUI is not running at {config.COMFYUI_URL}")
        print(f"  Start it: cd ComfyUI && python main.py --listen")
        return False


def check_prompts(theme, version=None):
    """Return True if a prompts.json exists for the theme (and optionally version)."""
    prompts_file = config.get_prompts_file(theme, version)
    if not os.path.exists(prompts_file):
        print(f"ERROR: prompts.json not found: {prompts_file}")
        print("  Create a prompts.json for this theme/version before generating.")
        return False
    return True


def _section(title):
    print(f"\n{'='*50}")
    print(f"  {title}")
    print(f"{'='*50}")


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_generate(theme, version):
    """Generate raw stickers for a theme/version."""
    _section(f"GENERATE  [{theme}/{version}]")
    if not check_comfyui():
        sys.exit(1)
    if not check_prompts(theme, version):
        sys.exit(1)
    from generate import generate_all
    generate_all(theme, version)


def cmd_format(theme, version, lang=None):
    """Format raw images to LINE spec."""
    label = f"{theme}/{version}" + (f"/{lang}" if lang else "")
    _section(f"FORMAT  [{label}]")
    from format_stickers import format_all
    format_all(theme, version, lang=lang)


def cmd_package(theme, version):
    """Package formatted stickers into a ZIP."""
    _section(f"PACKAGE  [{theme}/{version}]")
    from package import create_package
    create_package(theme, version)


def cmd_all(theme, version):
    """Run the full pipeline: generate → format → package."""
    print(f"\n{'='*50}")
    print(f"  FULL PIPELINE")
    print(f"  Theme:   {theme}")
    print(f"  Version: {version}")
    print(f"{'='*50}")

    cmd_generate(theme, version)
    cmd_format(theme, version)
    cmd_package(theme, version)

    print(f"\n{'='*50}")
    print(f"  ALL DONE! [{theme}/{version}]")
    print(f"{'='*50}\n")


def cmd_list():
    """List all themes and their versions."""
    output_dir = config.OUTPUT_DIR
    if not os.path.exists(output_dir):
        print("No themes found (output/ directory does not exist).")
        return

    themes = sorted(
        d for d in os.listdir(output_dir)
        if os.path.isdir(os.path.join(output_dir, d))
    )
    if not themes:
        print("No themes found.")
        return

    print(f"\nExisting themes in {output_dir}:")
    print("-" * 50)
    for theme in themes:
        theme_dir = os.path.join(output_dir, theme)
        versions = sorted(
            d for d in os.listdir(theme_dir)
            if os.path.isdir(os.path.join(theme_dir, d)) and d.startswith("v")
        )
        has_prompts = os.path.exists(os.path.join(theme_dir, "prompts.json"))
        print(f"  {theme}")
        print(f"    Versions: {', '.join(versions) if versions else '(none)'}")
        print(f"    prompts.json: {'yes' if has_prompts else 'no'}")

        for ver in versions:
            paths = config.get_paths(theme, ver)
            raw_count = len([
                f for f in os.listdir(paths["raw"])
                if f.endswith(".png")
            ]) if os.path.isdir(paths["raw"]) else 0
            fmt_count = len([
                f for f in os.listdir(paths["formatted"])
                if f.startswith("sticker_") and f.endswith(".png")
            ]) if os.path.isdir(paths["formatted"]) else 0
            pkg_exists = os.path.exists(os.path.join(paths["package"], "stickers.zip"))
            ver_prompts = os.path.exists(
                os.path.join(config.get_version_dir(theme, ver), "prompts.json")
            )
            print(
                f"      {ver}: raw={raw_count} formatted={fmt_count} "
                f"zip={'yes' if pkg_exists else 'no'} "
                f"prompts={'yes' if ver_prompts else 'no'}"
            )
    print()


def cmd_fix(theme, version, sticker_ids):
    """Regenerate specific stickers by ID, then re-format only those stickers."""
    id_list = [int(x) for x in sticker_ids]
    _section(f"FIX stickers {id_list}  [{theme}/{version}]")

    if not check_comfyui():
        sys.exit(1)
    if not check_prompts(theme, version):
        sys.exit(1)

    from generate import generate_all
    from format_stickers import remove_background, resize_to_sticker, optimize_png
    import glob

    paths = config.get_paths(theme, version)
    fmt_dir = paths["formatted"]
    os.makedirs(fmt_dir, exist_ok=True)

    # Regenerate the requested stickers
    results = generate_all(theme, version, sticker_ids=id_list)

    # Re-format only the regenerated stickers
    print(f"\nRe-formatting {len(results)} sticker(s)...")
    for entry in results:
        idx = entry["id"]
        raw_path = entry.get("raw")
        nobg_path = entry.get("nobg")

        print(f"  [#{idx:02d}] Re-formatting...")
        img = remove_background(raw_path, nobg_path)
        sticker = resize_to_sticker(img)
        sticker_data = optimize_png(sticker)
        sticker_path = os.path.join(fmt_dir, f"sticker_{idx:02d}.png")
        with open(sticker_path, "wb") as f:
            f.write(sticker_data)
        print(f"  [#{idx:02d}] Updated: {sticker_path}")

    print(f"\nFix complete. Run 'python main.py package {theme} {version}' to repackage.")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def usage():
    print(__doc__)
    sys.exit(1)


def main():
    args = sys.argv[1:]
    if not args:
        usage()

    cmd = args[0].lower()

    if cmd == "list":
        cmd_list()

    elif cmd == "generate":
        if len(args) < 2:
            print("Usage: python main.py generate <theme> [version]")
            sys.exit(1)
        theme = args[1]
        version = args[2] if len(args) > 2 else config.get_next_version(theme)
        cmd_generate(theme, version)

    elif cmd == "format":
        if len(args) < 3:
            print("Usage: python main.py format <theme> <version> [--lang zh|ja]")
            sys.exit(1)
        theme, version = args[1], args[2]
        lang = None
        if "--lang" in args:
            lang = args[args.index("--lang") + 1]
        cmd_format(theme, version, lang=lang)

    elif cmd == "package":
        if len(args) < 3:
            print("Usage: python main.py package <theme> <version>")
            sys.exit(1)
        theme, version = args[1], args[2]
        cmd_package(theme, version)

    elif cmd == "all":
        if len(args) < 2:
            print("Usage: python main.py all <theme> [version]")
            sys.exit(1)
        theme = args[1]
        version = args[2] if len(args) > 2 else config.get_next_version(theme)
        cmd_all(theme, version)

    elif cmd == "fix":
        if len(args) < 4:
            print("Usage: python main.py fix <theme> <version> <sticker_id> [<sticker_id> ...]")
            sys.exit(1)
        theme, version = args[1], args[2]
        sticker_ids = args[3:]
        cmd_fix(theme, version, sticker_ids)

    else:
        print(f"Unknown command: {cmd}")
        usage()


if __name__ == "__main__":
    main()
