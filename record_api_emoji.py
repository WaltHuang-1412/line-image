"""Record LINE Creators Market API calls for EMOJI (表情貼) upload flow.

Separate from record_api.py (which records sticker upload). Each product type
has different endpoints/payloads — keep them isolated.

Usage:
    python record_api_emoji.py

Opens browser with your saved session at the LINE Creators Market home.
Manually navigate to the emoji (Sticker Emoji / 表情貼) section, complete the
full upload flow. All API calls are printed and saved to api_log_emoji.json.

Press Enter in the terminal when done to save the log.
"""
import json
import os
from playwright.sync_api import sync_playwright

SESSION_FILE = os.path.join(os.path.dirname(__file__), "line_session.json")
LOG_FILE = os.path.join(os.path.dirname(__file__), "api_log_emoji.json")
# Start at the main dashboard; user manually clicks into emoji section
LINE_DASHBOARD_URL = "https://creator.line.me/my/7LHIQLNaztCXeJE8/"

IGNORE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".woff", ".woff2", ".ttf", ".css", ".js")
IGNORE_PREFIXES = (
    "https://www.google", "https://fonts.", "https://static.", "https://sentry",
    "https://d.line-scdn.net", "https://optout-api", "https://uts-front",
)


def should_record(url: str) -> bool:
    url_lower = url.lower()
    if any(url_lower.endswith(ext) for ext in IGNORE_EXTENSIONS):
        return False
    if any(url_lower.startswith(p) for p in IGNORE_PREFIXES):
        return False
    return True


def run():
    if not os.path.exists(SESSION_FILE):
        print("ERROR: No session found. Run: python upload_line.py --login")
        return

    log = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        ctx = browser.new_context(storage_state=SESSION_FILE)

        def on_request(request):
            if not should_record(request.url):
                return
            entry = {
                "method": request.method,
                "url": request.url,
                "post_data": request.post_data,
            }
            log.append(entry)
            if request.method in ("POST", "PUT", "PATCH", "DELETE"):
                print(f"  >>> [{request.method}] {request.url[:150]}")
                if request.post_data:
                    print(f"      body: {request.post_data[:300]}")
            else:
                print(f"  [{request.method}] {request.url[:150]}")

        def on_response(response):
            if not should_record(response.url):
                return
            if response.request.method not in ("POST", "PUT", "PATCH", "DELETE", "GET"):
                return
            try:
                text = response.text()
                if text.startswith(")]}'"):
                    text = text[text.index("\n") + 1:] if "\n" in text else text[4:]
                body = json.loads(text)
                for entry in reversed(log):
                    if entry["url"] == response.url and "response" not in entry:
                        entry["response_status"] = response.status
                        entry["response"] = body
                        break
                if response.request.method in ("POST", "PUT", "PATCH", "DELETE"):
                    print(f"  <<< {response.status} {json.dumps(body, ensure_ascii=False)[:300]}")
            except Exception:
                pass

        ctx.on("request", on_request)
        ctx.on("response", on_response)

        page = ctx.new_page()
        page.goto(LINE_DASHBOARD_URL)

        print("\n" + "=" * 60)
        print("  Browser opened at LINE Creators Market dashboard.")
        print("  Manually navigate to EMOJI (表情貼/Sticker Emoji) section.")
        print("  Complete the full emoji upload flow.")
        print("  All API calls are being recorded.")
        print("  Press Enter here when done to save the log.")
        print("=" * 60 + "\n")

        input(">> Press Enter to save log and close...")

        ctx.storage_state(path=SESSION_FILE)
        print(f"Session saved to {SESSION_FILE}")

        filtered = [e for e in log if should_record(e["url"])]

        with open(LOG_FILE, "w", encoding="utf-8") as f:
            json.dump(filtered, f, ensure_ascii=False, indent=2)

        print(f"\nSaved {len(filtered)} API calls to {LOG_FILE}")
        print(f"  POST/PUT/PATCH: {sum(1 for e in filtered if e['method'] in ('POST','PUT','PATCH'))}")
        print(f"  GET: {sum(1 for e in filtered if e['method'] == 'GET')}")
        browser.close()


if __name__ == "__main__":
    run()
