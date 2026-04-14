"""Check if all body parts are intact after background removal."""
import re
from qa import ollama


def check(image_path, emotion, character_desc, character_parts="ears, belly, paws"):
    """Returns (passed: bool, detail: str)."""
    prompt = (
        f'This is a {character_desc} with transparent background. '
        f'Are all body parts intact ({character_parts})? '
        f'Nothing cut off or eaten by background removal? '
        f'Answer: YES (all intact) or NO — describe what is missing.'
    )
    response = ollama.ask(image_path, prompt)
    passed = not bool(re.search(r'\bNO\b', response.upper().split('.')[0]))
    return passed, response.strip()
