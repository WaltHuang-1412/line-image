"""Automated LINE Creators Market sticker upload using Playwright.

Prerequisites:
    pip install playwright
    playwright install chromium

Usage:
    # 第一次：手動登入並儲存 session
    python upload_line.py --login

    # 上架（填資料 + 儲存，ZIP 上傳和 tag 仍需手動）
    python upload_line.py <theme> <version> --lang zh
    python upload_line.py <theme> <version> --lang ja

Example:
    python upload_line.py 圓滾貓的日常 v5 --lang zh
"""
import argparse
import os
import re
import sys

import config

SESSION_FILE = os.path.join(os.path.dirname(__file__), "line_session.json")
LINE_DASHBOARD_URL = "https://creator.line.me/my/7LHIQLNaztCXeJE8/sticker/?status=all&query=&page=1"


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


# ---------------------------------------------------------------------------
# Login helper
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


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------

def upload(theme, version, lang):
    from playwright.sync_api import sync_playwright

    ver_dir = config.get_version_dir(theme, version)
    lang_dir = os.path.join(ver_dir, lang)
    listing_path = os.path.join(lang_dir, "listing.md")
    zip_path = os.path.join(lang_dir, "package", "stickers.zip")

    for path, label in [(listing_path, "listing.md"), (zip_path, "stickers.zip")]:
        if not os.path.exists(path):
            print(f"ERROR: {label} not found: {path}")
            sys.exit(1)
    if not os.path.exists(SESSION_FILE):
        print("ERROR: No session found. Run: python upload_line.py --login")
        sys.exit(1)

    info = parse_listing(listing_path)
    print(f"\nUploading [{theme}/{version}/{lang}]")
    print(f"  EN title : {info['en']['title']}")
    print(f"  JA title : {info['ja']['title']}")
    print(f"  ZH title : {info['zh']['title']}")
    print(f"  Copyright: {info['copyright']}")
    print(f"  ZIP      : {zip_path}\n")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        ctx = browser.new_context(storage_state=SESSION_FILE)
        page = ctx.new_page()

        # --- Navigate to dashboard ---
        print("Opening dashboard...")
        page.goto(LINE_DASHBOARD_URL)
        page.wait_for_load_state("networkidle")

        # --- Close popup if present ---
        try:
            overlay = page.locator("button.background-overlay")
            overlay.wait_for(state="visible", timeout=5000)
            overlay.click()
            overlay.wait_for(state="hidden", timeout=5000)
        except Exception:
            pass

        # --- New sticker pack ---
        page.get_by_role("link", name="新增").click()
        page.get_by_role("link", name="貼圖").click()
        page.wait_for_load_state("networkidle")
        print("New sticker pack page opened.")

        # --- English (default) ---
        page.locator('[data-test="title-en"]').fill(info["en"]["title"])
        page.locator('[data-test="description-en"]').fill(info["en"]["desc"])
        print(f"  Filled EN")

        # --- Add Japanese ---
        page.locator('[data-test="select-language"]').select_option("ja")
        page.locator('[data-test="btn-add-language"]').click()
        page.locator('[data-test="title-ja"]').fill(info["ja"]["title"])
        page.locator('[data-test="description-ja"]').fill(info["ja"]["desc"])
        print(f"  Filled JA")

        # --- Add Chinese Traditional ---
        page.locator('[data-test="select-language"]').select_option("zh-Hant")
        page.locator('[data-test="btn-add-language"]').click()
        page.locator('[data-test="title-zh-Hant"]').fill(info["zh"]["title"])
        page.locator('[data-test="description-zh-Hant"]').fill(info["zh"]["desc"])
        print(f"  Filled ZH")

        # --- Copyright ---
        page.locator('[data-test="copyright"]').fill(info["copyright"])
        print(f"  Filled copyright")

        # --- Auto-publish radio ---
        page.get_by_role("radio", name="自動開始販售").check()

        # --- Save ---
        page.locator("label").filter(has_text="儲存").click()
        page.wait_for_timeout(2000)
        print("\n  Saved. Now upload the ZIP and fill in sticker tags manually.")
        print(f"  ZIP: {zip_path}")

        input("\n>> Press Enter to close browser...")
        browser.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Upload stickers to LINE Creators Market")
    parser.add_argument("theme", nargs="?", help="Theme name")
    parser.add_argument("version", nargs="?", help="Version string")
    parser.add_argument("--lang", choices=["zh", "ja"], default="zh")
    parser.add_argument("--login", action="store_true", help="Save login session")
    args = parser.parse_args()

    if args.login:
        do_login()
        return

    if not args.theme or not args.version:
        parser.print_help()
        sys.exit(1)

    upload(args.theme, args.version, args.lang)


if __name__ == "__main__":
    main()
