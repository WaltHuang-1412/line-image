"""Check overall image quality score."""
import re
from qa import ollama


def check(image_path, emotion, character_desc, min_score=4):
    """Returns (passed: bool, detail: str)."""
    prompt = (
        f'Rate this {character_desc} image quality from 1 to 5. '
        f'Answer: QUALITY: <score> — one sentence reason.'
    )
    response = ollama.ask(image_path, prompt)
    m = re.search(r'QUALITY:\s*([1-5])', response.upper())
    if m:
        score = int(m.group(1))
        return score >= min_score, response.strip()
    return True, response.strip()
