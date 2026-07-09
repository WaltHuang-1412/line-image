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

JS_PUT_JSON = JS_POST_JSON.replace("method: 'POST'", "method: 'PUT'")

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
    # v8 emoji basic emotions (圓滾貓表情貼)
    "開心": ["cat", "happy", "excited", "laugh"],
    "大笑": ["cat", "laugh", "happy", "excited"],
    "愛心眼": ["cat", "love", "happy", "shy", "hug"],
    "哭哭": ["cat", "cry", "sad", "please"],
    "生氣": ["cat", "angry", "angry_dissatisfied"],
    "驚訝": ["cat", "surprise", "shock"],
    "尷尬": ["cat", "shy", "anxious", "panic"],
    "睡覺": ["cat", "sleep", "lazy"],
    # v9 emoji reaction emotions (圓滾貓表情貼 2)
    "比讚": ["cat", "ok", "happy", "thank"],
    "壞笑": ["cat", "laugh", "happy"],
    "嫌棄": ["cat", "angry_dissatisfied", "no", "exactly"],
    "委屈": ["cat", "sad", "cry", "please", "miss"],
    "翻白眼": ["cat", "angry_dissatisfied", "exactly", "never_mind"],
    "害羞": ["cat", "shy", "love", "happy"],
    "發呆": ["cat", "lazy", "still", "wait"],
    # "哼" already defined in v3 sassy emotions above
    # v8 lazy/chill emotions (legacy sticker pack)
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
    # v10 festival emotions (圓滾貓的節慶日常)
    "新年快樂": ["cat", "happy", "excited", "anticipation", "hello"],
    "恭喜發財": ["cat", "happy", "excited", "thank", "hello"],
    "紅包拿來": ["cat", "please", "happy", "excited", "anticipation"],
    "團圓": ["cat", "happy", "love", "hug", "eat"],
    "聖誕快樂": ["cat", "happy", "excited", "love", "anticipation"],
    "萬聖節": ["cat", "excited", "surprise", "anticipation", "happy"],
    "中秋快樂": ["cat", "happy", "eat", "love", "anticipation"],
    "端午快樂": ["cat", "happy", "eat", "excited", "anticipation"],
    "情人節快樂": ["cat", "love", "happy", "shy", "hug"],
    "母親節快樂": ["cat", "love", "thank", "happy", "hug"],
    "父親節快樂": ["cat", "love", "thank", "happy", "ok"],
    "元宵快樂": ["cat", "happy", "excited", "anticipation", "love"],
    "跨年": ["cat", "happy", "excited", "laugh", "anticipation"],
    "生日快樂": ["cat", "happy", "excited", "love", "anticipation"],
    "感恩節": ["cat", "thank", "happy", "love", "eat"],
    "畢業快樂": ["cat", "happy", "excited", "anticipation", "ok"],
    # v11 home life emotions (圓滾貓的居家日常)
    "賴床": ["cat", "sleep", "lazy", "sad"],
    "刷牙": ["cat", "hello", "sleep", "happy"],
    "喝咖啡": ["cat", "eat", "happy", "lazy"],
    "開冰箱": ["cat", "eat", "happy", "excited", "anticipation"],
    "煮飯": ["cat", "eat", "happy", "work"],
    "洗碗": ["cat", "work", "sad", "lazy"],
    "洗衣服": ["cat", "work", "lazy", "ok"],
    "打掃": ["cat", "work", "ok", "happy"],
    "洗澡": ["cat", "happy", "lazy", "sleep", "relief"],
    "追劇": ["cat", "happy", "excited", "lazy"],
    "看手機": ["cat", "lazy", "happy", "still"],
    "叫外送": ["cat", "eat", "happy", "excited", "anticipation"],
    "不想出門": ["cat", "lazy", "sad", "no", "sleep"],
    "倒垃圾": ["cat", "work", "sad", "lazy"],
    "懶得動": ["cat", "lazy", "sleep", "sad"],
    "冷氣開起來": ["cat", "happy", "excited", "relief"],
    # v12 workout emotions (圓滾貓的運動日常)
    "去健身房": ["cat", "happy", "excited", "run", "anticipation"],
    "舉重":     ["cat", "work", "ok", "excited", "happy"],
    "跑步":     ["cat", "run", "happy", "excited"],
    "呼拉圈":   ["cat", "happy", "excited", "laugh"],
    "游泳":     ["cat", "happy", "excited", "relief"],
    "瑜珈":     ["cat", "happy", "relief", "lazy"],
    "爬山":     ["cat", "run", "happy", "excited", "anticipation"],
    "騎車":     ["cat", "happy", "excited", "run"],
    "打球":     ["cat", "happy", "excited", "ok"],
    "大流汗":   ["cat", "work", "sad", "cry", "panic"],
    "肌肉痠":   ["cat", "sad", "cry", "work", "lazy"],
    "喝蛋白質": ["cat", "eat", "happy", "ok", "excited"],
    "量體重":   ["cat", "anxious", "sad", "surprise", "shock"],
    "今天有練": ["cat", "happy", "excited", "ok", "thank"],
    "拉筋":     ["cat", "work", "ok", "relief", "happy"],
    "翹掉了":   ["cat", "lazy", "sad", "shy", "sleep"],
    # v13 daily-chat emotions (圓滾貓的日常對話) — zh
    "讚啦":     ["cat", "ok", "happy", "excited"],
    "瘋了嗎":   ["cat", "shock", "surprise", "seriously"],
    "認真嗎":   ["cat", "seriously", "surprise", "no"],
    "不會吧":   ["cat", "shock", "surprise", "panic"],
    "拜託啦":   ["cat", "please", "anxious", "sorry"],
    "好啦好啦": ["cat", "ok", "never_mind", "relief"],
    "哇塞":     ["cat", "surprise", "excited", "shock"],
    "厲害":     ["cat", "excited", "happy", "ok"],
    "廢話":     ["cat", "of_course", "exactly", "lazy"],
    "算了":     ["cat", "never_mind", "sad", "relief"],
    "欸欸欸":   ["cat", "hello", "excited", "surprise"],
    "說真的":   ["cat", "seriously", "exactly", "angry_dissatisfied"],
    "懂":       ["cat", "ok", "exactly", "of_course"],
    "超猛":     ["cat", "excited", "happy", "shock"],
    "不行啦":   ["cat", "laugh", "cry", "no"],
    "有夠煩":   ["cat", "angry", "angry_dissatisfied", "no"],
    # v14 Taiwanese-flavor emotions (圓滾貓的台味日常) — zh
    "嘿啊":       ["cat", "ok", "exactly", "happy"],
    "丟啦":       ["cat", "exactly", "of_course", "happy"],
    "賀啦":       ["cat", "ok", "never_mind", "relief"],
    "安捏喔":     ["cat", "surprise", "ok", "still"],
    "嘸災啦":     ["cat", "no", "never_mind", "lazy"],
    "蝦毀":       ["cat", "shock", "surprise", "seriously"],
    "知影啦~":    ["cat", "ok", "angry_dissatisfied", "exactly"],
    "咧無閒":     ["cat", "work", "panic", "anxious"],
    "袂記啊":     ["cat", "sorry", "panic", "shy"],
    "天公伯啊":   ["cat", "shock", "cry", "panic"],
    "夭壽喔":     ["cat", "shock", "surprise", "panic"],
    "代誌大條":   ["cat", "panic", "anxious", "shock"],
    "有夠扯":     ["cat", "surprise", "seriously", "laugh"],
    "太超過":     ["cat", "angry", "angry_dissatisfied", "no"],
    "哭啊":       ["cat", "cry", "sad", "angry_dissatisfied"],
    "GG":         ["cat", "sad", "no", "panic"],
    "哎唷喂啊":   ["cat", "angry_dissatisfied", "sad", "never_mind"],
    "母湯":       ["cat", "no", "angry_dissatisfied", "seriously"],
    "是在哈囉":   ["cat", "seriously", "angry_dissatisfied", "no"],
    "修但幾勒":   ["cat", "wait", "no", "panic"],
    "三八啦":     ["cat", "laugh", "happy", "shy"],
    "阿不就好棒棒": ["cat", "ok", "laugh", "angry_dissatisfied"],
    "免啦":       ["cat", "no", "ok", "relief"],
    "緊來去":     ["cat", "excited", "run", "anticipation", "hello"],
    "馬上到":     ["cat", "run", "wait", "arrive", "panic"],
    "到厝啊":     ["cat", "arrive", "going_home", "relief", "happy"],
    "先來睏":     ["cat", "sleep", "bye", "relief"],
    "歹勢啦":     ["cat", "sorry", "shy"],
    "嘸要緊":     ["cat", "ok", "relief", "happy"],
    "保重蛤":     ["cat", "bye", "love", "thank"],
    "好家在":     ["cat", "relief", "happy", "surprise"],
    "哩馬幫幫忙": ["cat", "please", "angry_dissatisfied", "no"],
    # v15 animated pack fillers (圓滾貓動次動次) — zh
    "嗯嗯":     ["cat", "ok", "exactly", "of_course"],
    "哈哈":     ["cat", "laugh", "happy", "excited"],
    "喔喔":     ["cat", "surprise", "ok", "still"],
    "好喔":     ["cat", "ok", "relief", "never_mind"],
    "沒問題":   ["cat", "ok", "of_course", "thank", "happy"],
    "知道了":   ["cat", "ok", "exactly", "of_course"],
    "對啊":     ["cat", "exactly", "of_course", "happy"],
    "蛤?":      ["cat", "surprise", "shock", "seriously"],
    "好啦":     ["cat", "ok", "never_mind", "relief"],
    "真的喔":   ["cat", "seriously", "surprise", "still"],
    "晚點說":   ["cat", "wait", "work", "anxious"],
    "先這樣":   ["cat", "bye", "ok", "never_mind"],
    # v13 daily-chat emotions — ja (ja/prompts.json)
    "いいね":       ["cat", "ok", "happy", "excited"],
    "マジかよ":     ["cat", "shock", "surprise", "seriously"],
    "本気？":       ["cat", "seriously", "surprise", "no"],
    "うそでしょ":   ["cat", "shock", "surprise", "panic"],
    "お願い":       ["cat", "please", "anxious", "sorry"],
    "はいはい":     ["cat", "ok", "never_mind", "relief"],
    "うわぁ":       ["cat", "surprise", "excited", "shock"],
    "すごい":       ["cat", "excited", "happy", "ok"],
    "当たり前":     ["cat", "of_course", "exactly", "lazy"],
    "もういい":     ["cat", "never_mind", "sad", "relief"],
    "ねえねえ":     ["cat", "hello", "excited", "surprise"],
    "マジで":       ["cat", "seriously", "exactly", "angry_dissatisfied"],
    "わかる":       ["cat", "ok", "exactly", "of_course"],
    "やばい":       ["cat", "excited", "happy", "shock"],
    "もうムリ":     ["cat", "laugh", "cry", "no"],
    "うざい":       ["cat", "angry", "angry_dissatisfied", "no"],
}


def get_tag_keywords(sticker_def):
    """Resolve the tag keyword list for one sticker.

    Preferred source: the sticker's own "tags" list in prompts.json
    (new packs, 2026-07+). Fallback: the legacy ZH_EMOTION_TAGS dict
    (v7-v15 packs, kept for compatibility — do not add new packs there).
    """
    keywords = sticker_def.get("tags")
    if not keywords:
        emotion = sticker_def.get("emotion", "")
        if emotion and emotion not in ZH_EMOTION_TAGS:
            print(f"  ERROR: #{sticker_def.get('id')} [{emotion}] has no \"tags\" in prompts.json "
                  f"and no legacy ZH_EMOTION_TAGS entry — add \"tags\" to prompts.json")
            sys.exit(1)
        keywords = ZH_EMOTION_TAGS.get(emotion, ["cat", "happy"])
    unknown = [k for k in keywords if k not in EMOTION_TAG_MAP]
    if unknown:
        print(f"  ERROR: #{sticker_def.get('id')} unknown tag keyword(s) {unknown} — "
              f"valid keywords are EMOTION_TAG_MAP keys")
        sys.exit(1)
    return keywords


def get_tags_for_emotion(sticker_def):
    """Keyword list -> legacy numeric tag IDs, deduped, max 9."""
    tag_ids = []
    for kw in get_tag_keywords(sticker_def):
        tag_ids.extend(EMOTION_TAG_MAP.get(kw, []))
    seen = set()
    result = []
    for t in tag_ids:
        if t not in seen:
            seen.add(t)
            result.append(t)
    return result[:9]


def load_tag_id_migration():
    """Old numeric tag IDs -> new c-prefixed IDs (LINE cms-next, 2026-06+), matched by English name."""
    v2_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "line_tags_v2.json")
    with open(v2_path, encoding="utf-8") as f:
        catalog = json.load(f)
    en_to_new = {}
    for t in catalog:
        for nl in t.get("name_by_lang", []):
            if nl["language"] == "en":
                en_to_new.setdefault(nl["name"].strip().lower(), t["id"])
    old_names = load_tags()
    return {oid: en_to_new[nm.strip().lower()] for oid, nm in old_names.items()
            if nm.strip().lower() in en_to_new}


def build_tag_payload(stickers):
    """Payload for PUT /api/sticker/{id}/auto_suggest_tags: [{"type":"01","tag_ids":[...]}, ...]"""
    o2n = load_tag_id_migration()
    payload = []
    for s in stickers:
        old_ids = get_tags_for_emotion(s)
        new_ids = [o2n[o] for o in old_ids if o in o2n][:9]
        if not new_ids:
            print(f"  ERROR: no tags resolved for #{s['id']} [{s.get('emotion', '')}] — fix mapping first")
            sys.exit(1)
        payload.append({"type": "%02d" % s["id"], "tag_ids": new_ids})
    return payload


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


def do_cancel(sticker_id):
    """Cancel a submitted sticker set."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser, ctx, page, token = _open_page(p)
        url = f"{API_BASE}/sticker/{sticker_id}/cancel_request"
        result = page.evaluate(JS_POST_JSON, [url, "{}", token])
        print(f"Cancel {sticker_id}: {result['status']}")
        if result["status"] == 200:
            print("Cancelled!")
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
        url = f"{API_BASE}/api/sticker/{sticker_id}/auto_suggest_tags"
        payload = build_tag_payload(prompts_data["stickers"])
        for sdef, entry in zip(prompts_data["stickers"], payload):
            print(f"  #{entry['type']} [{sdef.get('emotion', '')}] ({len(entry['tag_ids'])} tags)")
        result = page.evaluate(JS_PUT_JSON, [url, json.dumps(payload), token])
        ctx.storage_state(path=SESSION_FILE)
        browser.close()
        if result["status"] != 200:
            print(f"\nERROR: tag PUT -> {result['status']}: {str(result['body'])[:200]}")
            sys.exit(1)
        print(f"\nAll tags updated OK (PUT {result['status']}).")


def do_upload(theme, version, lang, sticker_id=None):
    """Full upload flow: create → set count → upload images → tag → submit."""
    from playwright.sync_api import sync_playwright

    ver_dir = config.get_version_dir(theme, version)
    lang_dir = os.path.join(ver_dir, lang)
    listing_path = os.path.join(lang_dir, "listing.md")
    if not os.path.exists(listing_path):
        listing_path = os.path.join(ver_dir, "listing.md")

    if not os.path.exists(listing_path):
        print(f"ERROR: listing.md not found in {lang_dir}/ or {ver_dir}/")
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
            suffix = " (JA)" if lang == "ja" else ""
            metas = [
                {"language": "en",      "title": info["en"]["title"] + suffix, "description": info["en"]["desc"]},
                {"language": "ja",      "title": info["ja"]["title"] + suffix, "description": info["ja"]["desc"]},
                {"language": "zh-Hant", "title": info["zh"]["title"] + suffix, "description": info["zh"]["desc"]},
            ]
            sticker_type = "animation" if prompts_data.get("type") == "animated_sticker" else "static"
            body = json.dumps({
                "type": sticker_type,
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
        upload_failures = []

        def _upload_ok(r, label):
            """HTTP 200 does NOT mean accepted — the body carries success/errors."""
            ok = isinstance(r["body"], dict) and r["body"].get("success", True)
            errs = r["body"].get("errors") if isinstance(r["body"], dict) else None
            print(f"  {label} -> {r['status']}" + ("" if ok else f"  REJECTED: {errs}"))
            if not ok:
                upload_failures.append(label)

        for img_path, img_type in [(main_file, "main"), (tab_file, "tab")]:
            if os.path.exists(img_path):
                b64 = base64.b64encode(open(img_path, "rb").read()).decode()
                r = page.evaluate(JS_UPLOAD_IMAGE, [upload_url, b64, os.path.basename(img_path), img_type, token])
                _upload_ok(r, f"{img_type}.png")

        for sf in sticker_files:
            name = os.path.basename(sf)
            num = re.search(r'sticker_(\d+)', name).group(1)
            b64 = base64.b64encode(open(sf, "rb").read()).decode()
            r = page.evaluate(JS_UPLOAD_IMAGE, [upload_url, b64, name, num, token])
            _upload_ok(r, name)

        if upload_failures:
            ctx.storage_state(path=SESSION_FILE)
            browser.close()
            print(f"\nERROR: {len(upload_failures)} image(s) rejected — NOT submitting: {upload_failures}")
            sys.exit(1)

        # Step 4: Tag (new auto_suggest_tags API, LINE cms-next 2026-06+)
        print("Step 4: Tagging...")
        tag_url = f"{API_BASE}/api/sticker/{sticker_id}/auto_suggest_tags"
        payload = build_tag_payload(prompts_data["stickers"])
        for entry in payload:
            emotion = sticker_defs.get(int(entry["type"]), {}).get("emotion", "")
            print(f"  #{entry['type']} [{emotion}] ({len(entry['tag_ids'])} tags)")
        result = page.evaluate(JS_PUT_JSON, [tag_url, json.dumps(payload), token])
        print(f"  PUT tags -> {result['status']}")
        if result["status"] != 200:
            ctx.storage_state(path=SESSION_FILE)
            browser.close()
            print(f"\nERROR: tagging failed ({result['status']}) — NOT submitting. body: {str(result['body'])[:200]}")
            print(f"After fixing, retag with --tags-only --sticker-id {sticker_id}, then --submit {sticker_id}")
            sys.exit(1)

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
    parser.add_argument("--cancel", type=int, metavar="ID", help="Cancel submitted sticker ID")
    args = parser.parse_args()

    if args.login:
        do_login()
    elif args.list:
        do_list()
    elif args.submit:
        do_submit(args.submit)
    elif args.cancel:
        do_cancel(args.cancel)
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
