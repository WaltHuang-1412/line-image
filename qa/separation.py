"""Check if the character is clearly separated from the background for easy bg removal."""
import re
from qa import ollama


def check(image_path, emotion, character_desc):
    """Returns (passed: bool, detail: str)."""
    prompt = (
        'Check if this character can be easily cut out from the background: '
        '1. Does the character touch or bleed into the image edges? '
        '2. Are there shadows connecting the character to the background? '
        '3. Is the character color clearly different from the background color? '
        'Answer: YES (easy to cut out, clear separation) or NO — describe the problem.'
    )
    response = ollama.ask(image_path, prompt)
    passed = bool(re.search(r'\bYES\b', response.upper()))
    return passed, response.strip()
