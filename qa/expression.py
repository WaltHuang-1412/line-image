"""Check if the facial expression is exaggerated enough for small emoji display."""
import re
from qa import ollama


def check(image_path, emotion, character_desc):
    """Returns (passed: bool, detail: str)."""
    prompt = (
        f'This is a {character_desc} emoji. '
        f'Is the facial expression exaggerated and clear enough to read at very small size (180px)? '
        f'Answer: STRONG or WEAK — one sentence reason.'
    )
    response = ollama.ask(image_path, prompt)
    passed = bool(re.search(r'\bSTRONG\b', response.upper()))
    return passed, response.strip()
