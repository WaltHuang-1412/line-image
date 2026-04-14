"""Check if the background is a clean uniform solid color (no gradients, artifacts)."""
import re
from qa import ollama


def check(image_path, emotion, character_desc):
    """Returns (passed: bool, detail: str)."""
    prompt = (
        'Look at the BACKGROUND area (not the character). '
        'Is the background a clean, uniform solid color? '
        'No gradients, no shadows, no artifacts, no texture? '
        'Answer: YES (clean solid color) or NO — describe the problem.'
    )
    response = ollama.ask(image_path, prompt)
    passed = bool(re.search(r'\bYES\b', response.upper()))
    return passed, response.strip()
