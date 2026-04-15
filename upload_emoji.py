"""Automated LINE Creators Market EMOJI upload using Playwright API calls.

Separate from upload_line.py (which is sticker-only). LINE emoji API uses
different endpoints and a different payload format.

Usage:
    # Full upload: create, upload images, set main 4, done (manual submit for now)
    python upload_emoji.py <theme> <version>

    # With existing emoji_id (resume)
    python upload_emoji.py <theme> <version> --emoji-id 501602

    # Login (shared session with sticker)
    python upload_line.py --login

    # List all emoji packs
    python upload_emoji.py --list

Reads:
    output/{theme}/{version}/listing.md     — titles/descriptions/copyright
    output/{theme}/{version}/formatted/     — sticker_XX.png + tab.png
    output/{theme}/{version}/prompts.json   — stickers array for main selection hint

API endpoints (learned from api_log_emoji.json):
    POST /api/emoji/                             create
    PUT  /api/emoji/{id}/image/count             set count
    PUT  /api/emoji/{id}/image/                  upload {type, content:base64}
    PUT  /api/emoji/{id}/image/main_selection    set 4 main images
"""
import argparse
import base64
import glob
import json
import os
import re
import sys
import time

import config
# Reuse sticker's emotion tag map + tag name map — same tagging system
from upload_line import EMOTION_TAG_MAP, ZH_EMOTION_TAGS, get_tags_for_emotion, load_tags

SESSION_FILE = os.path.join(os.path.dirname(__file__), "line_session.json")
# Navigate to emoji list page so Referer/CSRF context is emoji-scoped
LINE_DASHBOARD_URL = "https://creator.line.me/my/7LHIQLNaztCXeJE8/emoji/?status=all&query=&page=1"
API_BASE = "https://creator.line.me/my/7LHIQLNaztCXeJE8"


JS_GET_XSRF = """
(() => {
    const cookies = document.cookie.split(';');
    for (const c of cookies) {
        const t = c.trim();
        if (t.startsWith('XSRF-TOKEN=')) return t.substring(11);
    }
    return '';
})()
"""

JS_POST_JSON = """
async ([url, bodyJson, token]) => {
    const r = await fetch(url, {
        method: 'POST',
        headers: {'Content-Type': 'application/json', 'X-XSRF-TOKEN': token},
        body: bodyJson
    });
    const text = await r.text();
    const prefix = ")]}'";
    const clean = text.startsWith(prefix) ? text.substring(text.indexOf('\\n') + 1) : text;
    try { return {status: r.status, body: JSON.parse(clean)}; }
    catch { return {status: r.status, body: clean.substring(0, 500)}; }
}
"""

JS_PUT_JSON = """
async ([url, bodyJson, token]) => {
    const r = await fetch(url, {
        method: 'PUT',
        headers: {'Content-Type': 'application/json', 'X-XSRF-TOKEN': token},
        body: bodyJson
    });
    const text = await r.text();
    const prefix = ")]}'";
    const clean = text.startsWith(prefix) ? text.substring(text.indexOf('\\n') + 1) : text;
    try { return {status: r.status, body: JSON.parse(clean)}; }
    catch { return {status: r.status, body: clean.substring(0, 500)}; }
}
"""


def parse_listing(listing_path):
    """Extract titles, descriptions, copyright from listing.md."""
    with open(listing_path, encoding="utf-8") as f:
        text = f.read()

    def extract(pattern):
        m = re.search(pattern, text)
        return m.group(1).strip() if m else ""

    return {
        "zh": {
            "title": extract(r'[-–]\s*標題[:：]\s*(.+)'),
            "desc":  extract(r'[-–]\s*說明[:：]\s*(.+)'),
        },
        "en": {
            "title": extract(r'[-–]\s*Title[:：]\s*(.+)'),
            "desc":  extract(r'[-–]\s*Description[:：]\s*(.+)'),
        },
        "ja": {
            "title": extract(r'[-–]\s*タイトル[:：]\s*(.+)'),
            "desc":  extract(r'[-–]\s*説明[:：]\s*(.+)'),
        },
        "copyright": extract(r'(Copyright.+)'),
        "main_selection": extract(r'主要圖片建議[^\*]*\*\*([0-9,\s]+)\*\*'),
    }


def _open_page(pw):
    browser = pw.chromium.launch(headless=True)
    ctx = browser.new_context(storage_state=SESSION_FILE)
    page = ctx.new_page()
    page.goto(LINE_DASHBOARD_URL)
    page.wait_for_load_state("networkidle")
    time.sleep(2)
    token = page.evaluate(JS_GET_XSRF)
    return browser, ctx, page, token


def do_upload(theme, version, emoji_id=None, submit=False):
    from playwright.sync_api import sync_playwright

    ver_dir = config.get_version_dir(theme, version)
    fmt_dir = os.path.join(ver_dir, "formatted")
    listing_path = os.path.join(ver_dir, "listing.md")
    prompts_file = config.get_prompts_file(theme, version)

    if not os.path.exists(listing_path):
        print(f"ERROR: listing.md not found: {listing_path}")
        sys.exit(1)
    if not os.path.exists(SESSION_FILE):
        print("ERROR: No session. Run: python upload_line.py --login")
        sys.exit(1)

    info = parse_listing(listing_path)
    sticker_files = sorted(glob.glob(os.path.join(fmt_dir, "sticker_*.png")))
    tab_file = os.path.join(fmt_dir, "tab.png")

    # Load emotion mapping for tagging
    with open(prompts_file, encoding="utf-8") as f:
        prompts_data = json.load(f)
    sticker_defs = {s["id"]: s for s in prompts_data.get("stickers", [])}
    tag_name_map = load_tags()

    if not sticker_files:
        print(f"ERROR: no sticker_*.png in {fmt_dir}")
        sys.exit(1)
    if not os.path.exists(tab_file):
        print(f"ERROR: tab.png missing")
        sys.exit(1)

    print(f"\n{'='*50}")
    print(f"  Emoji Upload [{theme}/{version}]")
    print(f"  ZH: {info['zh']['title']}")
    print(f"  EN: {info['en']['title']}")
    print(f"  JA: {info['ja']['title']}")
    print(f"  Copyright: {info['copyright']}")
    print(f"  Emoji: {len(sticker_files)}")
    print(f"{'='*50}\n")

    with sync_playwright() as p:
        browser, ctx, page, token = _open_page(p)

        # 1. Create or reuse
        if emoji_id:
            print(f"Using existing emoji_id: {emoji_id}")
        else:
            print("Step 1: Creating emoji...")
            body = json.dumps({
                "all_area": True,
                "copyright": info["copyright"],
                "design_url": None,
                "meta": [
                    {"language_code": "en",      "title": info["en"]["title"], "description": info["en"]["desc"]},
                    {"language_code": "ja",      "title": info["ja"]["title"], "description": info["ja"]["desc"]},
                    {"language_code": "zh-Hant", "title": info["zh"]["title"], "description": info["zh"]["desc"]},
                ],
                "emoji_type": "static",
                "package_type_name": "original",
                "is_auto_release": True,
                "use_photo": False,
                "request_comment": "",
                "campaign": None,
                "subscription": {"participation": True},
                "is_ai_generated": True,
                "attachment_file": None,
                # Full country codes for global release (matches LINE web form default)
                "area_codes": [
                    "TW","JP","TH","ID","KR","BD","BN","BT","HK","IN","KH","LA","LK","MM","MN","MO","MV","MY","NP","PH","PK","SG","TL","VN",
                    "AU","CK","FJ","FM","KI","MH","NR","NU","NZ","PG","PW","SB","TO","TV","VU","WS",
                    "CA","GU","US","AG","AR","BB","BO","BR","BS","BZ","CL","CO","CR","CU","DM","DO","EC","GD","GT","GY","HN","HT","JM","KN","LC","MX","NI","PA","PE","PY","SR","SV","TT","UY","VC","VE",
                    "AD","AL","AM","AT","AZ","BA","BE","BG","BY","CH","CY","CZ","DE","DK","EE","ES","FI","FR","GB","GE","GR","HR","HU","IE","IS","IT","KG","KZ","LI","LT","LU","LV","MC","MD","ME","MK","MT","NL","NO","PL","PT","RO","RS","SE","SI","SK","SM","TJ","TM","UA","UZ","VA",
                    "AE","AF","BH","IL","IQ","IR","JO","KW","LB","OM","PS","QA","SA","TR","YE",
                    "AO","BF","BI","BJ","BW","CD","CF","CG","CI","CM","CV","DJ","DZ","EG","ER","ET","GA","GH","GM","GN","GQ","GW","KE","KM","LR","LS","LY","MA","MG","ML","MR","MU","MW","MZ","NA","NE","NG","RW","SC","SD","SL","SN","SO","SS","ST","SZ","TD","TG","TN","TZ","UG","ZA","ZM","ZW",
                ],
            })
            r = page.evaluate(JS_POST_JSON, [f"{API_BASE}/api/emoji/", body, token])
            if r["status"] != 200 or not isinstance(r["body"], dict):
                print(f"  FAIL: {r}")
                browser.close()
                sys.exit(1)
            emoji_id = r["body"].get("id") or r["body"].get("emoji_id")
            print(f"  Created emoji_id: {emoji_id}")

        count = len(sticker_files)
        total_count = count + 1  # image_count includes tab

        # 2. Set count (LINE counts tab as one of the image slots)
        print(f"Step 2: Setting count to {total_count} ({count} emoji + 1 tab)...")
        r = page.evaluate(JS_PUT_JSON, [
            f"{API_BASE}/api/emoji/{emoji_id}/image/count",
            json.dumps({"image_count": total_count}),
            token,
        ])
        print(f"  count={total_count}: {r['status']}")

        # 3. Upload tab + emoji images
        upload_url = f"{API_BASE}/api/emoji/{emoji_id}/image/"

        print(f"Step 3: Uploading tab.png + {count} emoji...")
        tab_b64 = base64.b64encode(open(tab_file, "rb").read()).decode()
        r = page.evaluate(JS_PUT_JSON, [
            upload_url,
            json.dumps({"type": "tab", "content": tab_b64}),
            token,
        ])
        print(f"  tab.png -> {r['status']}")

        for i, sf in enumerate(sticker_files, 1):
            img_type = f"{i:03d}"  # 001, 002, ...
            b64 = base64.b64encode(open(sf, "rb").read()).decode()
            r = page.evaluate(JS_PUT_JSON, [
                upload_url,
                json.dumps({"type": img_type, "content": b64}),
                token,
            ])
            print(f"  {os.path.basename(sf)} as {img_type} -> {r['status']}")

        # 4. Set 4 main selection
        # Parse "001, 003, 005, 002" from listing.md or default to first 4
        main_str = info.get("main_selection", "")
        main_ids = [s.strip().zfill(3) for s in re.findall(r'\d+', main_str)][:4]
        if len(main_ids) < 4:
            main_ids = [f"{i:03d}" for i in range(1, 5)]
        print(f"Step 4: Setting 4 main images: {main_ids}")
        main_body = [
            {"main_position": i + 1, "type": main_ids[i]}
            for i in range(4)
        ]
        r = page.evaluate(JS_PUT_JSON, [
            f"{API_BASE}/api/emoji/{emoji_id}/image/main_selection",
            json.dumps(main_body),
            token,
        ])
        print(f"  main_selection -> {r['status']}")

        # 5. Tagging (same as sticker flow, 3-digit keys instead of 2-digit)
        print(f"Step 5: Tagging {count} emoji...")
        tag_url = f"{API_BASE}/api/emoji/{emoji_id}/update_taggings"
        for i, sf in enumerate(sticker_files, 1):
            num = f"{i:03d}"
            sid = i
            emotion = sticker_defs.get(sid, {}).get("emotion", "")
            tags = get_tags_for_emotion(emotion)
            names = [tag_name_map.get(t, t) for t in tags]
            body = json.dumps({num: tags})
            r = page.evaluate(JS_POST_JSON, [tag_url, body, token])
            print(f"  #{num} [{emotion}] ({len(tags)}) -> {r['status']} {names}")

        # 6. Submit for review (emoji uses PUT request_review, different from sticker's do_request)
        if submit:
            print("Step 6: Submitting for review...")
            submit_url = f"{API_BASE}/api/emoji/{emoji_id}/request_review"
            r = page.evaluate(JS_PUT_JSON, [submit_url, "{}", token])
            print(f"  Submit -> {r['status']}")
            status_label = 'Submitted' if r['status'] == 200 else 'Check manually'
        else:
            status_label = 'Not submitted (pass --submit to submit for review)'

        ctx.storage_state(path=SESSION_FILE)

        print(f"\n{'='*50}")
        print(f"  Done! emoji_id={emoji_id}")
        print(f"  Status: {status_label}")
        print(f"  Dashboard: https://creator.line.me/my/7LHIQLNaztCXeJE8/emoji/{emoji_id}")
        print(f"{'='*50}")

        browser.close()
    return emoji_id


def do_list():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser, ctx, page, token = _open_page(p)
        js = """
        async (url) => {
            const r = await fetch(url);
            const text = await r.text();
            const prefix = ")]}'";
            const clean = text.startsWith(prefix) ? text.substring(text.indexOf('\\n') + 1) : text;
            return JSON.parse(clean);
        }
        """
        data = page.evaluate(js, f"{API_BASE}/api/emoji?page=1")
        print(f"\n{'ID':>10} | {'Status':>25} | Title")
        print("-" * 80)
        for entry in data.get("items", []):
            eid = entry.get("id", "?")
            title = entry.get("title", "?")
            status = entry.get("confirmationStatus", "?")
            print(f"{eid:>10} | {status:>25} | {title}")
        ctx.storage_state(path=SESSION_FILE)
        browser.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("theme", nargs="?")
    ap.add_argument("version", nargs="?")
    ap.add_argument("--emoji-id", type=int)
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--submit", action="store_true", help="Submit for review after upload")
    args = ap.parse_args()

    if args.list:
        do_list()
    elif args.theme and args.version:
        do_upload(args.theme, args.version, emoji_id=args.emoji_id, submit=args.submit)
    else:
        ap.print_help()
