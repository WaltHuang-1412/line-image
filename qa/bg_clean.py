"""Check if background is fully removed (transparent)."""
import re
from qa import ollama


def check(image_path, emotion, character_desc, character_parts="ears, belly, paws"):
    """Returns (passed: bool, detail: str)."""
    prompt = (
        f'This image should have a fully transparent background. '
        f'Is the background clean? No leftover colored patches or artifacts? '
        f'Answer: CLEAN or DIRTY — one sentence reason.'
    )
    response = ollama.ask(image_path, prompt)
    passed = bool(re.search(r'\bCLEAN\b', response.upper()))
    return passed, response.strip()
