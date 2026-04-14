"""Check if the character fills the canvas properly."""
import re
from qa import ollama


def check(image_path, emotion, character_desc):
    """Returns (passed: bool, detail: str)."""
    prompt = (
        f'Does the character fill most of the image? '
        f'It should not be tiny, off-center, or have too much empty space. '
        f'Answer: GOOD or BAD — one sentence reason.'
    )
    response = ollama.ask(image_path, prompt)
    passed = bool(re.search(r'\bGOOD\b', response.upper()))
    return passed, response.strip()
