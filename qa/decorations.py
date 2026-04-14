"""Check if decorative visual elements are present (emoji-specific)."""
import re
from qa import ollama

# Expected decorations per emotion
EXPECTED_DECORATIONS = {
    "開心": "sparkles or stars",
    "大笑": "tears of joy",
    "愛心眼": "floating hearts",
    "哭哭": "big teardrops",
    "生氣": "steam or veins",
    "驚訝": "exclamation marks",
    "尷尬": "sweat drops",
    "睡覺": "ZZZ or snoring bubble",
    "比讚": "thumbs up or sparkle",
    "壞笑": "dark shadow or aura",
    "嫌棄": "stink lines or wavy lines",
    "委屈": "teardrops or trembling lines",
    "翻白眼": "dots or ellipsis",
    "害羞": "blush or steam from cheeks",
    "發呆": "spiral eyes or ghost",
    "哼": "puff of air from nose",
}


def check(image_path, emotion, character_desc):
    """Returns (passed: bool, detail: str)."""
    expected = EXPECTED_DECORATIONS.get(emotion, "decorative elements")
    prompt = (
        f'This emoji shows "{emotion}". '
        f'Can you see any of these decorative elements: {expected}? '
        f'Answer: YES (describe what you see) or NO (not visible).'
    )
    response = ollama.ask(image_path, prompt)
    passed = bool(re.search(r'\bYES\b', response.upper()))
    return passed, response.strip()
