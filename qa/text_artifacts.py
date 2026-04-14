"""Check for unwanted AI-generated text in the image."""
import re
from qa import ollama


def check(image_path, emotion, character_desc):
    """Returns (passed: bool, detail: str)."""
    prompt = (
        f'Does this image contain any unwanted text, letters, or words? '
        f'Ignore punctuation marks and decorative symbols. '
        f'Answer: NO (clean) or YES:"exact text found".'
    )
    response = ollama.ask(image_path, prompt)
    upper = response.upper()
    if re.search(r'\bYES\b', upper):
        quoted = re.findall(r'"([^"]+)"', response)
        has_real_text = any(
            re.search(r'[a-zA-Z\u3040-\u30ff\u4e00-\u9fff]{2,}', q)
            for q in quoted
        )
        if has_real_text:
            return False, response.strip()
    return True, response.strip()
