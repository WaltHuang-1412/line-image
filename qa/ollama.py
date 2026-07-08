"""Shared Ollama API client for QA checks."""
import base64
import json
import sys
import urllib.request
import urllib.error

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "gemma3:12b"


def check_running():
    """Verify ollama is running. Exits with error if not."""
    try:
        urllib.request.urlopen("http://localhost:11434/api/tags", timeout=5)
    except Exception:
        print("ERROR: ollama is not running at localhost:11434")
        sys.exit(1)


def ask(image_path, prompt):
    """Send an image + prompt to ollama and return the response text.

    RGBA images are composited onto white first — Ollama vision models
    handle the alpha channel inconsistently and may "see" the RGB values
    hiding under transparent pixels (e.g. leftover orange after flood fill).
    """
    from PIL import Image
    import io
    img = Image.open(image_path)
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        canvas = Image.new("RGBA", img.size, (255, 255, 255, 255))
        canvas.alpha_composite(img)
        buf = io.BytesIO()
        canvas.convert("RGB").save(buf, "PNG")
        img_b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
    else:
        with open(image_path, "rb") as f:
            img_b64 = base64.b64encode(f.read()).decode("utf-8")

    payload = {
        "model": MODEL,
        "prompt": prompt,
        "images": [img_b64],
        "stream": False,
    }

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        OLLAMA_URL,
        data=data,
        headers={"Content-Type": "application/json"},
    )
    resp = urllib.request.urlopen(req, timeout=120)
    result = json.loads(resp.read())
    return result.get("response", "")
