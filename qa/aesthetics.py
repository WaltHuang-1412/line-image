"""Check if the image is aesthetically pleasing and commercially viable."""
import re
from qa import ollama


def check(image_path, emotion, character_desc, min_score=5):
    """Returns (passed: bool, detail: str)."""
    prompt = (
        f'This is a {character_desc} for a LINE sticker/emoji product. '
        f'As a consumer, would you want to buy this? Is it cute, appealing, and well-drawn? '
        f'Rate aesthetics from 1 to 5 (5 = would definitely buy). '
        f'Answer: AESTHETICS: <score> — one sentence reason.'
    )
    response = ollama.ask(image_path, prompt)
    m = re.search(r'AESTHETICS:\s*([1-5])', response.upper())
    if m:
        score = int(m.group(1))
        return score >= min_score, response.strip()
    return True, response.strip()
