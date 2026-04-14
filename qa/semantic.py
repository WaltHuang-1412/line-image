"""Check if the character's expression matches the intended emotion."""
import re
from qa import ollama


def check(image_path, emotion, character_desc):
    """Returns (passed: bool, detail: str)."""
    prompt = (
        f'This is a {character_desc}. '
        f'Intended emotion: "{emotion}". '
        f'Does the character expression clearly convey "{emotion}"? '
        f'Answer: YES or NO — one sentence reason.'
    )
    response = ollama.ask(image_path, prompt)
    passed = bool(re.search(r'\bYES\b', response.upper()))
    return passed, response.strip()
