"""QA pipeline orchestrator.

Runs checks based on product profile (sticker/emoji) and stage (raw/nobg/format).
Each check is an independent module in qa/ with a check() function.
"""
import importlib
import json
import os

import config
from qa import ollama


def _load_check(name):
    """Dynamically import a check module from qa/ package."""
    return importlib.import_module(f"qa.{name}")


def _get_sticker_data(theme, version):
    """Load prompts.json and return parsed data."""
    prompts_file = config.get_prompts_file(theme, version)
    with open(prompts_file, "r", encoding="utf-8") as f:
        return json.load(f)


def run_stage(theme, version, stage, sticker_ids=None):
    """Run all QA checks for a given stage.

    Args:
        theme: Theme name.
        version: Version string.
        stage: "raw_qa", "nobg_qa", or "format_qa".
        sticker_ids: Optional list of IDs to check. None = all.

    Returns:
        dict of {sticker_id: [(check_name, passed, detail), ...]} for failed stickers.
    """
    pdata = _get_sticker_data(theme, version)
    profile = config.get_profile(theme, version)
    check_names = profile.get(stage, [])

    if not check_names:
        print(f"  No checks defined for stage '{stage}'")
        return {}

    sticker_defs = {s["id"]: s for s in pdata.get("stickers", [])}
    character_desc = pdata.get("character_desc", config.CHARACTER_DESC)
    character_parts = pdata.get("character_parts", config.CHARACTER_PARTS)
    product_type = pdata.get("type", "sticker")

    if sticker_ids is None:
        sticker_ids = sorted(sticker_defs.keys())

    # Determine image directory based on stage
    paths = config.get_paths(theme, version)
    if stage == "raw_qa":
        img_dir = paths["raw"]
        suffix = ""
    elif stage == "nobg_qa":
        img_dir = paths["raw"]
        suffix = "_nobg"
    else:
        img_dir = paths["formatted"]
        suffix = ""

    ollama.check_running()

    print(f"\n{'='*60}")
    print(f"  QA: {theme}/{version} — {stage}")
    print(f"  Type: {product_type}")
    print(f"  Checks: {', '.join(check_names)}")
    print(f"  Stickers: {len(sticker_ids)}")
    print(f"{'='*60}\n")

    all_failed = {}

    for sid in sticker_ids:
        sdef = sticker_defs.get(sid)
        if not sdef:
            continue

        emotion = sdef.get("emotion", "")
        img_path = os.path.join(img_dir, f"sticker_{sid:02d}{suffix}.png")

        if not os.path.exists(img_path):
            print(f"  #{sid:02d} [{emotion}] — FILE MISSING")
            all_failed[sid] = [("file", False, "missing")]
            continue

        print(f"  #{sid:02d} [{emotion}]", end="", flush=True)
        failures = []

        for check_name in check_names:
            mod = _load_check(check_name)
            try:
                passed, detail = mod.check(
                    img_path, emotion, character_desc,
                )
            except TypeError:
                # Some checks accept extra kwargs
                passed, detail = mod.check(
                    img_path, emotion, character_desc,
                    character_parts=character_parts,
                )

            if passed:
                print(f" [{check_name}: OK]", end="", flush=True)
            else:
                print(f" [{check_name}: FAIL]", end="", flush=True)
                failures.append((check_name, False, detail))

        if failures:
            print(f" ✗")
            for name, _, detail in failures:
                print(f"         {name}: {detail[:120]}")
            all_failed[sid] = failures
        else:
            print(f" ✓")

    # Summary
    passed = len(sticker_ids) - len(all_failed)
    print(f"\n  PASS: {passed}/{len(sticker_ids)}")
    if all_failed:
        print(f"  FAIL: {list(all_failed.keys())}")

    return all_failed
