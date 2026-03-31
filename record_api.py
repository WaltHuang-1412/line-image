"""Record LINE Creators Market API calls during manual form submission.

Usage:
    python record_api.py

Opens browser with your saved session. Manually fill in and submit the sticker
form. All API calls are printed and saved to api_log.json for analysis.
"""
import json
import os
from playwright.sync_api import sync_playwright

SESSION_FILE = os.path.join(os.path.dirname(__file__), "line_session.json")
LOG_FILE = os.path.join(os.path.dirname(__file__), "api_log.json")
LINE_DASHBOARD_URL = "https://creator.line.me/my/7LHIQLNaztCXeJE8/sticker/?status=all&query=&page=1"

IGNORE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".woff", ".woff2", ".ttf", ".css")
IGNORE_PREFIXES = ("https://www.google", "https://fonts.", "https://static.", "https://sentry")


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
        page = ctx.new_page()

        def on_request(request):
            entry = {
                "method": request.method,
                "url": request.url,
                "post_data": request.post_data,
            }
            log.append(entry)
            print(f"  [{request.method}] {request.url[:120]}")

        def on_response(response):
            if not should_record(response.url):
                return
            try:
                body = response.json()
                for entry in reversed(log):
                    if entry["url"] == response.url:
                        entry["response"] = body
                        break
                print(f"<<< {response.status} {json.dumps(body, ensure_ascii=False)[:200]}")
            except Exception:
                pass

        def on_websocket(ws):
            print(f"\n[WS OPEN] {ws.url}")
            ws_entry = {"type": "websocket", "url": ws.url, "messages": []}
            log.append(ws_entry)

            def on_send(payload):
                print(f"  [WS SEND] {str(payload)[:200]}")
                ws_entry["messages"].append({"dir": "send", "data": payload})

            def on_recv(payload):
                print(f"  [WS RECV] {str(payload)[:200]}")
                ws_entry["messages"].append({"dir": "recv", "data": payload})

            ws.on("framesent", lambda p: on_send(p))
            ws.on("framereceived", lambda p: on_recv(p))

        page.on("request", on_request)
        page.on("response", on_response)
        page.on("websocket", on_websocket)

        page.goto(LINE_DASHBOARD_URL)
        print("Browser opened. Manually complete the full sticker upload flow.")
        print("All POST/PUT/PATCH requests will be recorded.")
        print("When done, press Enter here to save the log.\n")

        input(">> Press Enter to save log and close...")

        with open(LOG_FILE, "w", encoding="utf-8") as f:
            json.dump(log, f, ensure_ascii=False, indent=2)

        print(f"\nSaved {len(log)} API calls to {LOG_FILE}")
        browser.close()


if __name__ == "__main__":
    run()
