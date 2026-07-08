"""Check if background is fully removed (transparent)."""
import re
from qa import ollama


def check(image_path, emotion, character_desc, character_parts="ears, belly, paws"):
    """Returns (passed: bool, detail: str)."""
    prompt = (
        f'This character was cut out from its original background and is shown '
        f'composited on a plain white canvas. Look for leftover background remnants: '
        f'colored patches, halos, or fringes around the character that do not belong to it. '
        f'A plain white area is NOT a remnant. '
        f'Answer: CLEAN or DIRTY — one sentence reason.'
    )
    response = ollama.ask(image_path, prompt)
    passed = bool(re.search(r'\bCLEAN\b', response.upper()))
    return passed, response.strip()
