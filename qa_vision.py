"""Local vision QA using ollama (gemma3:4b).

Runs all visual checks locally — zero cloud token cost.

Usage:
    python qa_vision.py <theme> <version>
    python qa_vision.py <theme> <version> --ids 1 5 11   # check specific stickers
    python qa_vision.py <theme> <version> --raw           # check raw images
    python qa_vision.py <theme> <version> --lang zh       # check zh/ or ja/ directory
"""
import argparse
import base64
import json
import os
import re
import sys
import urllib.request
import urllib.error

import config

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "gemma3:4b"


def check_ollama():
    """Verify ollama is running. Exits with error if not."""
    try:
        urllib.request.urlopen("http://localhost:11434/api/tags", timeout=5)
    except Exception:
        print(f"ERROR: ollama is not running at localhost:11434")
        print(f"  Start it: ollama serve")
        sys.exit(1)


def ask_ollama(image_path, prompt):
    """Send an image + prompt to ollama and return the response text."""
    with open(image_path, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode("utf-8")

    payload = {
        "model": MODEL,
        "prompt": prompt,
        "images": [img_b64],
        "stream": False,
    }

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        OLLAMA_URL,
        data=data,
        headers={"Content-Type": "application/json"},
    )
    resp = urllib.request.urlopen(req, timeout=120)
    result = json.loads(resp.read())
    return result.get("response", "")


def check_sticker(image_path, emotion, is_raw=False):
    """Single ollama call covering all QA checks. Returns raw response string."""
    if is_raw:
        prompt = (
            f'LINE sticker — round chubby grey cat, ink painting style. '
            f'Intended emotion: "{emotion}".\n\n'
            f'Answer each line exactly as shown:\n'
            f'SEMANTIC: YES or NO — does the cat expression match "{emotion}"?\n'
            f'TEXT: NO — or YES:"exact unwanted text" (ignore punctuation/symbols/decorative marks)\n'
            f'QUALITY: 1-5 — one sentence reason'
        )
    else:
        prompt = (
            f'LINE sticker — round chubby grey cat, ink painting style. '
            f'The Chinese label "{emotion}" is intentional — ignore it.\n\n'
            f'Answer each line exactly as shown:\n'
            f'SEMANTIC: YES or NO — does the cat expression match "{emotion}"?\n'
            f'TEXT: NO — or YES:"exact unwanted text" (ignore the "{emotion}" label and punctuation/symbols)\n'
            f'BG: CLEAN or DIRTY — ink brush strokes and shadows are NORMAL; '
            f'mark DIRTY only for large opaque patches, rectangular artifacts, '
            f'or clearly cut-off body parts (ears, belly, paws)\n'
            f'QUALITY: 1-5 — one sentence reason'
        )
    return ask_ollama(image_path, prompt)


def parse_pass_fail(response, is_raw=False):
    """Parse combined ollama response into list of issue strings."""
    issues = []
    lines = response.upper()

    # SEMANTIC
    m = re.search(r'SEMANTIC:\s*(YES|NO)', lines)
    if m and m.group(1) == "NO":
        # Extract original-case line for display
        orig = re.search(r'(?i)SEMANTIC:.*', response)
        snippet = orig.group(0)[:80] if orig else "NO"
        issues.append(f"semantic: {snippet}")

    # TEXT ARTIFACTS
    m = re.search(r'TEXT:\s*(NO|YES)', lines)
    if m and m.group(1) == "YES":
        orig = re.search(r'(?i)TEXT:.*', response)
        text_line = orig.group(0) if orig else ""
        quoted = re.findall(r'"([^"]+)"', text_line)
        has_real_text = any(
            re.search(r'[a-zA-Z\u3040-\u30ff\u4e00-\u9fff]{2,}', q)
            for q in quoted
        )
        if has_real_text:
            issues.append(f"text: {text_line[:80]}")

    # BG QUALITY (formatted only)
    if not is_raw:
        m = re.search(r'BG:\s*(CLEAN|DIRTY)', lines)
        if m and m.group(1) == "DIRTY":
            orig = re.search(r'(?i)BG:.*', response)
            snippet = orig.group(0)[:80] if orig else "DIRTY"
            issues.append(f"bg: {snippet}")

    # QUALITY SCORE
    m = re.search(r'QUALITY:\s*([1-5])', lines)
    if m:
        score = int(m.group(1))
        if score <= 2:
            orig = re.search(r'(?i)QUALITY:.*', response)
            snippet = orig.group(0)[:80] if orig else str(score)
            issues.append(f"quality: {snippet}")

    return issues


def _find_image(img_dir, sid, is_raw):
    """Locate the image file for a sticker ID."""
    if is_raw:
        # New naming first, then legacy
        for name in [f"sticker_{sid:02d}_raw.png", f"sticker_{sid:02d}.png"]:
            path = os.path.join(img_dir, name)
            if os.path.exists(path):
                return path
        return None
    else:
        path = os.path.join(img_dir, f"sticker_{sid:02d}.png")
        return path if os.path.exists(path) else None


def run_qa(theme, version, sticker_ids=None, check_raw=False, lang=None):
    """Run vision QA on stickers."""
    paths = config.get_paths(theme, version)
    prompts_file = config.get_prompts_file(theme, version)

    with open(prompts_file, "r", encoding="utf-8") as f:
        pdata = json.load(f)

    sticker_defs = {s["id"]: s for s in pdata.get("stickers", [])}

    if sticker_ids is None:
        sticker_ids = sorted(sticker_defs.keys())

    if check_raw:
        img_dir = paths["raw"]
        label = "raw"
    elif lang:
        img_dir = os.path.join(config.get_version_dir(theme, version), lang)
        label = lang
    else:
        img_dir = paths["formatted"]
        label = "formatted"

    check_ollama()

    print(f"{'='*60}")
    print(f"  Vision QA: {theme}/{version} ({label})")
    print(f"  Model: {MODEL} (local)")
    print(f"  Checking {len(sticker_ids)} stickers")
    print(f"{'='*60}\n")

    all_issues = {}

    for sid in sticker_ids:
        sdef = sticker_defs.get(sid)
        if not sdef:
            print(f"  #{sid:02d} — no definition in prompts.json, skipping")
            continue

        emotion = sdef.get("emotion", "")
        img_path = _find_image(img_dir, sid, is_raw=check_raw)

        if not img_path:
            print(f"  #{sid:02d} [{emotion}] — FILE MISSING")
            all_issues[sid] = ["file missing"]
            continue

        print(f"  #{sid:02d} [{emotion}] checking...", end="", flush=True)
        try:
            response = check_sticker(img_path, emotion, is_raw=check_raw)
            issues = parse_pass_fail(response, is_raw=check_raw)
        except urllib.error.URLError as e:
            print(f" ERROR (ollama: {e})")
            all_issues[sid] = [f"ollama error: {e}"]
            continue
        except Exception as e:
            print(f" ERROR ({e})")
            all_issues[sid] = [f"error: {e}"]
            continue

        if issues:
            print(f" FAIL")
            for issue in issues:
                print(f"         - {issue}")
            all_issues[sid] = issues
        else:
            print(f" PASS")

    # Summary
    print(f"\n{'='*60}")
    passed = len(sticker_ids) - len(all_issues)
    print(f"  PASS: {passed}/{len(sticker_ids)}")
    if all_issues:
        print(f"  FAIL: {list(all_issues.keys())}")
    print(f"{'='*60}")

    return all_issues


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Local vision QA using ollama")
    parser.add_argument("theme", help="Theme name")
    parser.add_argument("version", help="Version string")
    parser.add_argument("--ids", nargs="+", type=int, help="Specific sticker IDs to check")
    parser.add_argument("--raw", action="store_true", help="Check raw images instead of formatted")
    parser.add_argument("--lang", choices=["zh", "ja"], help="Check language-specific directory (zh/ or ja/)")
    args = parser.parse_args()

    if args.raw and args.lang:
        print("ERROR: --raw and --lang are mutually exclusive")
        sys.exit(1)

    issues = run_qa(args.theme, args.version, args.ids, args.raw, args.lang)
    sys.exit(1 if issues else 0)
