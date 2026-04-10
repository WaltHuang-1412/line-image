"""Automated LINE Creators Market sticker upload using Playwright API calls.

Prerequisites:
    pip install playwright
    playwright install chromium

Usage:
    # 第一次：手動登入並儲存 session
    python upload_line.py --login

    # 完整上架：建立 + 上傳圖片 + tag + 送審
    python upload_line.py <theme> <version> --lang zh

    # 用已建立的 sticker ID（跳過建立）
    python upload_line.py <theme> <version> --lang zh --sticker-id 43790300

    # 只更新 tag（不上傳圖片、不送審）
    python upload_line.py <theme> <version> --lang zh --sticker-id 43790300 --tags-only

    # 只送審（不建立、不上傳、不 tag）
    python upload_line.py --submit 43790300

    # 列出所有貼圖包
    python upload_line.py --list
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

SESSION_FILE = os.path.join(os.path.dirname(__file__), "line_session.json")
TAGS_FILE = os.path.join(os.path.dirname(__file__), "line_tags.json")
LINE_DASHBOARD_URL = "https://creator.line.me/my/7LHIQLNaztCXeJE8/sticker/?status=all&query=&page=1"
API_BASE = "https://creator.line.me/my/7LHIQLNaztCXeJE8"


# ---------------------------------------------------------------------------
# JS templates for Playwright evaluate (avoid f-string/quote issues)
# ---------------------------------------------------------------------------

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
    catch { return {status: r.status, body: clean.substring(0, 300)}; }
}
"""

JS_POST_FORM = """
async ([url, fields, token]) => {
    const form = new FormData();
    for (const [k, v] of Object.entries(fields)) {
        form.append(k, v);
    }
    const r = await fetch(url, {
        method: 'POST',
        body: form,
        headers: {'X-XSRF-TOKEN': token}
    });
    return r.status;
}
"""

JS_UPLOAD_IMAGE = """
async ([url, b64, filename, imgType, token]) => {
    const binary = atob(b64);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
    const blob = new Blob([bytes], {type: 'image/png'});
    const form = new FormData();
    form.append('image', blob, filename);
    form.append('type', imgType);
    const r = await fetch(url, {method: 'POST', body: form, headers: {'X-XSRF-TOKEN': token}});
    const text = await r.text();
    const prefix = ")]}'";
    const clean = text.startsWith(prefix) ? text.substring(text.indexOf('\\n') + 1) : text;
    try { return {status: r.status, body: JSON.parse(clean)}; }
    catch { return {status: r.status, body: clean.substring(0, 300)}; }
}
"""

JS_LIST_STICKERS = """
async (url) => {
    const r = await fetch(url);
    const text = await r.text();
    const prefix = ")]}'";
    const clean = text.startsWith(prefix) ? text.substring(text.indexOf('\\n') + 1) : text;
    return JSON.parse(clean);
}
"""


# ---------------------------------------------------------------------------
# Parse listing.md
# ---------------------------------------------------------------------------

def parse_listing(listing_path):
    """Extract titles, descriptions, and copyright from listing.md."""
    with open(listing_path, encoding="utf-8") as f:
        text = f.read()

    def extract(pattern):
        m = re.search(pattern, text)
        return m.group(1).strip() if m else ""

    return {
        "zh": {
            "title": extract(r'[-–]\s*標題[：:]\s*(.+)'),
            "desc":  extract(r'[-–]\s*說明[：:]\s*(.+)'),
        },
        "en": {
            "title": extract(r'[-–]\s*Title[：:]\s*(.+)'),
            "desc":  extract(r'[-–]\s*Description[：:]\s*(.+)'),
        },
        "ja": {
            "title": extract(r'[-–]\s*タイトル[：:]\s*(.+)'),
            "desc":  extract(r'[-–]\s*説明[：:]\s*(.+)'),
        },
        "copyright": extract(r'(Copyright.+)'),
    }


def load_tags():
    """Load LINE tag ID -> name mapping."""
    if os.path.exists(TAGS_FILE):
        with open(TAGS_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


# ---------------------------------------------------------------------------
# Tag selection based on emotion
# ---------------------------------------------------------------------------

EMOTION_TAG_MAP = {
    "cat": ["2412645"],
    "happy": ["58", "97", "337"],
    "angry": ["99", "110", "188"],
    "sad": ["85", "178", "59"],
    "love": ["89", "292", "205", "74"],
    "excited": ["68", "212", "210"],
    "lazy": ["112", "275", "295"],
    "cry": ["95", "65", "77"],
    "laugh": ["88", "140", "232", "231", "290"],
    "surprise": ["57", "225", "240", "350"],
    "shy": ["235", "171", "220"],
    "please": ["323", "128", "92"],
    "thank": ["327", "326", "158"],
    "sorry": ["100", "352", "130"],
    "bye": ["351", "336", "121"],
    "hello": ["310", "307", "308", "302"],
    "ok": ["313", "316", "346", "280"],
    "no": ["317", "348", "143"],
    "wait": ["2407282", "300", "2407250"],
    "miss": ["2407277", "84", "78"],
    "eat": ["109", "184", "186", "256", "193"],
    "sleep": ["199", "297", "298", "136"],
    "work": ["2407217", "2407223", "2407224", "315"],
    "run": ["131", "122", "123", "134"],
    "hug": ["2407202", "169"],
    "angry_dissatisfied": ["66", "73", "189", "190", "98"],
    "anticipation": ["56", "151"],
    "going_home": ["2407225", "336", "121"],
    "panic": ["202", "209", "139"],
    "anxious": ["93", "135", "170"],
    "where": ["2407248", "166", "125"],
    "still": ["2407273", "2407253"],
    "arrive": ["2407221", "164", "2407258"],
    "exactly": ["246", "282"],
    "never_mind": ["254", "137"],
    "relief": ["2407205", "2407244"],
    "of_course": ["2407259", "2407249"],
    "seriously": ["284", "2407266", "2407264"],
    "shock": ["227", "60", "165"],
}

ZH_EMOTION_TAGS = {
    # v7 friend emotions
    "約嗎": ["cat", "happy", "excited", "hello", "anticipation"],
    "+1": ["cat", "ok", "happy", "excited", "thank"],
    "先走了": ["cat", "bye", "run", "going_home"],
    "等等我": ["cat", "run", "wait", "panic", "anxious"],
    "在哪": ["cat", "surprise", "wait", "where", "still"],
    "到了": ["cat", "ok", "happy", "excited", "arrive"],
    "隨便": ["cat", "lazy", "ok", "exactly", "never_mind"],
    "都可以": ["cat", "ok", "happy", "relief", "of_course"],
    "笑死": ["cat", "laugh", "happy", "excited"],
    "真假": ["cat", "surprise", "seriously", "shock"],
    "不要走": ["cat", "sad", "please", "cry", "miss", "love"],
    "想你們": ["cat", "miss", "sad", "love", "cry"],
    "借我": ["cat", "please", "anxious", "hug"],
    "還我": ["cat", "angry_dissatisfied", "surprise", "wait"],
    "謝啦": ["cat", "thank", "happy", "love", "shy", "hello"],
    "掰掰": ["cat", "bye", "happy", "love", "sad"],
    # v6 couple emotions
    "黏你": ["cat", "love", "hug", "happy", "shy"],
    "討抱": ["cat", "love", "hug", "please", "cry", "sad"],
    "鬧彆扭": ["cat", "angry_dissatisfied", "sad", "love", "shy"],
    "和好": ["cat", "happy", "shy", "love", "hug"],
    "不理你": ["cat", "angry_dissatisfied", "lazy", "sad"],
    "陪我": ["cat", "love", "please", "sad", "miss", "hug"],
    "親親": ["cat", "love", "happy", "shy", "excited", "hug"],
    "你最好了": ["cat", "love", "happy", "excited", "thank"],
    "好喜歡你": ["cat", "love", "shy", "happy", "excited", "hug"],
    "好想你": ["cat", "miss", "love", "sad", "cry"],
    "等你": ["cat", "wait", "sad", "miss", "lazy"],
    "幫我": ["cat", "please", "cry", "sad", "love"],
    "你壞壞": ["cat", "angry_dissatisfied", "love", "shy", "surprise"],
    "人家嘛": ["cat", "please", "shy", "love", "sad", "cry"],
    "撒嬌": ["cat", "love", "shy", "happy", "please", "hug"],
    "嫉妒": ["cat", "angry_dissatisfied", "sad", "love", "surprise"],
    # v5 work emotions
    "早安": ["cat", "hello", "happy", "sleep"],
    "上班去": ["cat", "work", "run", "sad"],
    "打卡": ["cat", "work", "ok", "hello"],
    "開會中": ["cat", "work", "lazy", "sad"],
    "收到": ["cat", "ok", "happy", "work"],
    "好的": ["cat", "ok", "happy", "work"],
    "加班": ["cat", "work", "sad", "cry", "lazy"],
    "救命": ["cat", "cry", "sad", "please", "surprise"],
    "摸魚": ["cat", "lazy", "happy", "work"],
    "午餐": ["cat", "eat", "happy", "work"],
    "好累": ["cat", "lazy", "sad", "sleep", "work"],
    "下班": ["cat", "bye", "happy", "excited", "work"],
    "不想上班": ["cat", "lazy", "sad", "cry", "work", "sleep"],
    "薪水": ["cat", "happy", "excited", "love", "work"],
    "禮拜一": ["cat", "sad", "cry", "work", "lazy"],
    "放假": ["cat", "happy", "excited", "lazy", "sleep"],
    # v4 food emotions
    "好餓": ["cat", "eat", "sad", "cry", "please"],
    "吃什麼": ["cat", "eat", "surprise", "happy"],
    "開動": ["cat", "eat", "happy", "excited"],
    "太好吃": ["cat", "eat", "happy", "excited", "love"],
    "再一口": ["cat", "eat", "please", "love", "happy"],
    "吃飽了": ["cat", "eat", "happy", "lazy", "sleep"],
    "不夠吃": ["cat", "eat", "sad", "cry", "angry_dissatisfied"],
    "是我的": ["cat", "eat", "angry_dissatisfied", "love"],
    "宵夜": ["cat", "eat", "happy", "sleep", "lazy"],
    "減肥": ["cat", "sad", "cry", "eat"],
    "明天再說": ["cat", "lazy", "sleep", "eat", "happy"],
    "外送到了": ["cat", "eat", "happy", "excited", "run"],
    "請客": ["cat", "eat", "happy", "love", "please"],
    "我請你": ["cat", "eat", "happy", "love", "excited"],
    "甜點胃": ["cat", "eat", "happy", "love"],
    "打包": ["cat", "eat", "happy", "run", "ok"],
    # v3 sassy emotions
    "嘻嘻": ["cat", "laugh", "happy"],
    "才怪": ["cat", "laugh", "surprise", "angry_dissatisfied"],
    "干麻": ["cat", "angry_dissatisfied", "surprise", "lazy"],
    "嘴嘴": ["cat", "love", "happy", "shy"],
    "你誰": ["cat", "surprise", "angry_dissatisfied"],
    "回我": ["cat", "angry_dissatisfied", "wait", "please"],
    "哼": ["cat", "angry_dissatisfied", "sad"],
    "吵屁": ["cat", "angry_dissatisfied", "surprise"],
    "略略": ["cat", "laugh", "happy", "shy"],
    "滾": ["cat", "angry_dissatisfied", "bye"],
    "識相": ["cat", "angry_dissatisfied", "happy", "lazy"],
    "欠揍": ["cat", "angry_dissatisfied", "surprise"],
    "切": ["cat", "angry_dissatisfied", "lazy"],
    "煩欸": ["cat", "angry_dissatisfied", "sad", "lazy"],
    "比心": ["cat", "love", "happy", "shy"],
    "才不要": ["cat", "angry_dissatisfied", "surprise"],
    # v8 lazy/chill emotions
    "不想動": ["cat", "lazy", "sleep", "sad"],
    "追劇中": ["cat", "happy", "excited", "lazy"],
    "再一集": ["cat", "excited", "sleep", "happy", "lazy"],
    "WiFi咧": ["cat", "panic", "cry", "surprise", "angry_dissatisfied"],
    "好無聊": ["cat", "lazy", "sad", "sleep"],
    "耍廢中": ["cat", "lazy", "happy", "sleep"],
    "別吵我": ["cat", "angry_dissatisfied", "lazy", "no"],
    "充電中": ["cat", "sleep", "lazy", "happy"],
    "已讀不回": ["cat", "lazy", "no", "shy"],
    "沙發是我的": ["cat", "angry_dissatisfied", "happy", "lazy"],
    "今天就這樣": ["cat", "lazy", "bye", "ok", "happy"],
    "睡到自然醒": ["cat", "sleep", "happy", "lazy"],
    "外面好可怕": ["cat", "cry", "panic", "anxious", "sad"],
    "手機沒電": ["cat", "cry", "sad", "panic", "surprise"],
    "來點零食": ["cat", "eat", "please", "happy", "excited"],
    "明天的事明天說": ["cat", "lazy", "bye", "happy", "sleep"],
}


def get_tags_for_emotion(emotion):
    """Get tag IDs for a given emotion text. Returns up to 9 tags."""
    keywords = ZH_EMOTION_TAGS.get(emotion, ["cat", "happy"])
    tag_ids = []
    for kw in keywords:
        tag_ids.extend(EMOTION_TAG_MAP.get(kw, []))
    seen = set()
    result = []
    for t in tag_ids:
        if t not in seen:
            seen.add(t)
            result.append(t)
    return result[:9]


# ---------------------------------------------------------------------------
# Browser context helper
# ---------------------------------------------------------------------------

def _open_page(pw):
    """Launch browser with saved session, navigate to dashboard, return (browser, page, token)."""
    browser = pw.chromium.launch(headless=True)
    ctx = browser.new_context(storage_state=SESSION_FILE)
    page = ctx.new_page()
    page.goto(LINE_DASHBOARD_URL)
    page.wait_for_load_state("networkidle")
    time.sleep(2)
    token = page.evaluate(JS_GET_XSRF)
    return browser, ctx, page, token


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def do_login():
    """Open browser for manual login, then save session."""
    from playwright.sync_api import sync_playwright
    print("Opening browser — log in to LINE Creators Market, then press Enter.")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        ctx = browser.new_context()
        page = ctx.new_page()
        page.goto(LINE_DASHBOARD_URL)
        input(">> Press Enter after logging in...")
        ctx.storage_state(path=SESSION_FILE)
        browser.close()
    print(f"Session saved to {SESSION_FILE}")


def do_list():
    """List all sticker sets on LINE Creators Market."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser, ctx, page, token = _open_page(p)
        data = page.evaluate(JS_LIST_STICKERS, f"{API_BASE}/api/v2/sticker?page=1")

        print(f"\n{'ID':>10} | {'Status':>25} | Title")
        print("-" * 80)
        for entry in data.get("items", []):
            sid = entry.get("id", "?")
            title = entry.get("title", "?")
            status = entry.get("confirmationStatus", "?")
            print(f"{sid:>10} | {status:>25} | {title}")
        print(f"\nTotal: {len(data.get('items', []))}")

        ctx.storage_state(path=SESSION_FILE)
        browser.close()


def do_submit(sticker_id):
    """Submit a sticker set for review."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser, ctx, page, token = _open_page(p)
        url = f"{API_BASE}/sticker/{sticker_id}/do_request"
        result = page.evaluate(JS_POST_JSON, [url, "{}", token])
        print(f"Submit {sticker_id}: {result['status']}")
        if result["status"] == 200:
            print("Submitted for review!")
        else:
            print(f"Failed: {result.get('body', '')}")
        ctx.storage_state(path=SESSION_FILE)
        browser.close()


def do_tags(theme, version, sticker_id):
    """Update tags for all stickers in a set."""
    from playwright.sync_api import sync_playwright

    prompts_file = config.get_prompts_file(theme, version)
    with open(prompts_file, encoding="utf-8") as f:
        prompts_data = json.load(f)
    tag_name_map = load_tags()

    with sync_playwright() as p:
        browser, ctx, page, token = _open_page(p)
        url = f"{API_BASE}/api/sticker/{sticker_id}/update_taggings"

        for sdef in prompts_data["stickers"]:
            num = f"{sdef['id']:02d}"
            emotion = sdef.get("emotion", "")
            tags = get_tags_for_emotion(emotion)
            names = [tag_name_map.get(t, t) for t in tags]

            body = json.dumps({num: tags})
            result = page.evaluate(JS_POST_JSON, [url, body, token])
            status = result["status"]
            print(f"  #{num} [{emotion}] ({len(tags)}) -> {status} {names}")

        ctx.storage_state(path=SESSION_FILE)
        browser.close()


def do_upload(theme, version, lang, sticker_id=None):
    """Full upload flow: create → set count → upload images → tag → submit."""
    from playwright.sync_api import sync_playwright

    ver_dir = config.get_version_dir(theme, version)
    lang_dir = os.path.join(ver_dir, lang)
    listing_path = os.path.join(lang_dir, "listing.md")

    if not os.path.exists(listing_path):
        print(f"ERROR: listing.md not found: {listing_path}")
        sys.exit(1)
    if not os.path.exists(SESSION_FILE):
        print("ERROR: No session found. Run: python upload_line.py --login")
        sys.exit(1)

    info = parse_listing(listing_path)
    prompts_file = config.get_prompts_file(theme, version)
    with open(prompts_file, encoding="utf-8") as f:
        prompts_data = json.load(f)
    sticker_defs = {s["id"]: s for s in prompts_data.get("stickers", [])}
    tag_name_map = load_tags()

    sticker_files = sorted(glob.glob(os.path.join(lang_dir, "sticker_*.png")))
    main_file = os.path.join(lang_dir, "main.png")
    tab_file = os.path.join(lang_dir, "tab.png")

    print(f"\n{'='*50}")
    print(f"  Upload [{theme}/{version}/{lang}]")
    print(f"  EN: {info['en']['title']}")
    print(f"  JA: {info['ja']['title']}")
    print(f"  ZH: {info['zh']['title']}")
    print(f"  Stickers: {len(sticker_files)}")
    print(f"{'='*50}\n")

    with sync_playwright() as p:
        browser, ctx, page, token = _open_page(p)

        # Step 1: Create or reuse
        if sticker_id:
            print(f"Using existing sticker ID: {sticker_id}")
        else:
            print("Step 1: Creating sticker set...")
            metas = [
                {"language": "en", "title": info["en"]["title"], "description": info["en"]["desc"]},
                {"language": "ja", "title": info["ja"]["title"], "description": info["ja"]["desc"]},
                {"language": "zh-Hant", "title": info["zh"]["title"], "description": info["zh"]["desc"]},
            ]
            body = json.dumps({
                "type": "static",
                "metas": metas,
                "copyright": info["copyright"],
                "categoryIds": ["6", "10"],
                "isShownInShop": True,
                "isJoiningStickerPremium": True,
                "saleAreas": None,
                "isCombinationSticker": True,
                "campaignId": None,
                "isJoiningFreeTrial": True,
                "isJoiningAutoSuggestFreeTrial": True,
                "isAutoRelease": True,
                "isPhotoUsed": False,
                "designUrl": "",
                "noteForReviewers": "",
                "isAiGenerated": True,
            })
            result = page.evaluate(JS_POST_JSON, [f"{API_BASE}/api/v2/sticker", body, token])
            if result["status"] != 200 or not isinstance(result["body"], dict):
                print(f"  ERROR: {result}")
                browser.close()
                sys.exit(1)
            sticker_id = result["body"]["stickerId"]
            print(f"  Created: {sticker_id}")

        # Step 2: Set count
        count = len(sticker_files)
        print(f"Step 2: Setting count to {count}...")
        page.evaluate(JS_POST_FORM, [
            f"{API_BASE}/api/sticker/{sticker_id}/stickers_per_set",
            {"stickers_per_set": str(count)},
            token,
        ])

        # Step 3: Upload images
        print(f"Step 3: Uploading {count + 2} images...")
        upload_url = f"{API_BASE}/api/sticker/{sticker_id}/upload_image"

        for img_path, img_type in [(main_file, "main"), (tab_file, "tab")]:
            if os.path.exists(img_path):
                b64 = base64.b64encode(open(img_path, "rb").read()).decode()
                r = page.evaluate(JS_UPLOAD_IMAGE, [upload_url, b64, os.path.basename(img_path), img_type, token])
                print(f"  {img_type}.png -> {r['status']}")

        for sf in sticker_files:
            name = os.path.basename(sf)
            num = re.search(r'sticker_(\d+)', name).group(1)
            b64 = base64.b64encode(open(sf, "rb").read()).decode()
            r = page.evaluate(JS_UPLOAD_IMAGE, [upload_url, b64, name, num, token])
            print(f"  {name} -> {r['status']}")

        # Step 4: Tag
        print("Step 4: Tagging...")
        tag_url = f"{API_BASE}/api/sticker/{sticker_id}/update_taggings"
        for sf in sticker_files:
            num = re.search(r'sticker_(\d+)', os.path.basename(sf)).group(1)
            sid = int(num)
            emotion = sticker_defs.get(sid, {}).get("emotion", "")
            tags = get_tags_for_emotion(emotion)
            names = [tag_name_map.get(t, t) for t in tags]
            body = json.dumps({num: tags})
            result = page.evaluate(JS_POST_JSON, [tag_url, body, token])
            print(f"  #{num} [{emotion}] ({len(tags)}) -> {result['status']} {names}")

        # Step 5: Submit
        print("Step 5: Submitting...")
        submit_url = f"{API_BASE}/sticker/{sticker_id}/do_request"
        result = page.evaluate(JS_POST_JSON, [submit_url, "{}", token])
        print(f"  Submit: {result['status']}")

        ctx.storage_state(path=SESSION_FILE)

        print(f"\n{'='*50}")
        print(f"  Done! Sticker ID: {sticker_id}")
        print(f"  Status: {'Submitted' if result['status'] == 200 else 'Check manually'}")
        print(f"{'='*50}")

        browser.close()
    return sticker_id


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Upload stickers to LINE Creators Market")
    parser.add_argument("theme", nargs="?", help="Theme name")
    parser.add_argument("version", nargs="?", help="Version string")
    parser.add_argument("--lang", choices=["zh", "ja"], default="zh")
    parser.add_argument("--login", action="store_true", help="Save login session")
    parser.add_argument("--list", action="store_true", help="List all sticker sets")
    parser.add_argument("--sticker-id", type=int, help="Use existing sticker ID")
    parser.add_argument("--tags-only", action="store_true", help="Only update tags (requires --sticker-id)")
    parser.add_argument("--submit", type=int, metavar="ID", help="Submit sticker ID for review")
    args = parser.parse_args()

    if args.login:
        do_login()
    elif args.list:
        do_list()
    elif args.submit:
        do_submit(args.submit)
    elif args.tags_only:
        if not args.sticker_id or not args.theme or not args.version:
            print("ERROR: --tags-only requires --sticker-id, theme, and version")
            sys.exit(1)
        do_tags(args.theme, args.version, args.sticker_id)
    elif args.theme and args.version:
        do_upload(args.theme, args.version, args.lang, sticker_id=args.sticker_id)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
