"""Check if the background is uniform enough for clean background removal."""
import re
from qa import ollama


def check(image_path, emotion, character_desc):
    """Returns (passed: bool, detail: str)."""
    prompt = (
        'Look at the BACKGROUND area (not the character). '
        'Is the background mostly one uniform color, making it easy to separate from the character? '
        'Minor texture or graininess from art style is ACCEPTABLE. '
        'These are problems that would FAIL: strong gradients, shadows connecting character to edges, '
        'multiple distinct background colors, dark blobs or shapes in background, vignette effects. '
        'Answer: YES (background is removable) or NO — describe the specific problem.'
    )
    response = ollama.ask(image_path, prompt)
    passed = bool(re.search(r'\bYES\b', response.upper()))
    return passed, response.strip()
