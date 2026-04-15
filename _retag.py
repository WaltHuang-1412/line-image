"""Ad-hoc script: re-tag an existing emoji_id with correct tags from ZH_EMOTION_TAGS."""
import json
import sys
import time

from playwright.sync_api import sync_playwright

from upload_line import get_tags_for_emotion, load_tags
from upload_emoji import JS_GET_XSRF, JS_POST_JSON
import config

API_BASE = "https://creator.line.me/my/7LHIQLNaztCXeJE8"
SESSION_FILE = "line_session.json"


def retag(theme, version, emoji_id):
    with open(config.get_prompts_file(theme, version), encoding="utf-8") as f:
        prompts = json.load(f)
    defs = {s["id"]: s for s in prompts["stickers"]}
    name_map = load_tags()

    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        ctx = b.new_context(storage_state=SESSION_FILE)
        page = ctx.new_page()
        page.goto(f"{API_BASE}/emoji/?status=all&query=&page=1")
        page.wait_for_load_state("networkidle")
        time.sleep(2)
        token = page.evaluate(JS_GET_XSRF)

        url = f"{API_BASE}/api/emoji/{emoji_id}/update_taggings"
        for i in sorted(defs.keys()):
            num = f"{i:03d}"
            emotion = defs[i].get("emotion", "")
            tags = get_tags_for_emotion(emotion)
            names = [name_map.get(t, t) for t in tags]
            body = json.dumps({num: tags})
            r = page.evaluate(JS_POST_JSON, [url, body, token])
            print(f"  #{num} [{emotion}] ({len(tags)}) -> {r['status']} {names}")
        ctx.storage_state(path=SESSION_FILE)
        b.close()


if __name__ == "__main__":
    retag(sys.argv[1], sys.argv[2], int(sys.argv[3]))
