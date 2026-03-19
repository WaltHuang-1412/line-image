"""Call ComfyUI API to generate sticker images using generate_with_sam.json workflow."""
import json
import os
import random
import time
import urllib.request
import urllib.parse

import config

SAM_WORKFLOW_FILE = os.path.join(config.BASE_DIR, "workflow", "generate_with_sam.json")


# ---------------------------------------------------------------------------
# Low-level ComfyUI API helpers
# ---------------------------------------------------------------------------

def queue_prompt(prompt_workflow, server_url=config.COMFYUI_URL):
    """Submit a workflow to ComfyUI and return the prompt_id."""
    data = json.dumps({"prompt": prompt_workflow}).encode("utf-8")
    req = urllib.request.Request(
        f"{server_url}/prompt",
        data=data,
        headers={"Content-Type": "application/json"},
    )
    resp = urllib.request.urlopen(req)
    return json.loads(resp.read())["prompt_id"]


def wait_for_completion(prompt_id, server_url=config.COMFYUI_URL, timeout=600):
    """Poll /history until the prompt finishes, then return the history entry."""
    start = time.time()
    while time.time() - start < timeout:
        try:
            resp = urllib.request.urlopen(f"{server_url}/history/{prompt_id}")
            history = json.loads(resp.read())
            if prompt_id in history:
                return history[prompt_id]
        except Exception:
            pass
        time.sleep(3)
    raise TimeoutError(f"Generation timed out after {timeout}s (prompt_id={prompt_id})")


def get_image(filename, subfolder, folder_type, server_url=config.COMFYUI_URL):
    """Download a single image from ComfyUI and return its bytes."""
    params = urllib.parse.urlencode(
        {"filename": filename, "subfolder": subfolder, "type": folder_type}
    )
    resp = urllib.request.urlopen(f"{server_url}/view?{params}")
    return resp.read()


def upload_image(filepath, server_url=config.COMFYUI_URL):
    """Upload a reference image to ComfyUI (for IP-Adapter) and return the server filename."""
    filename = os.path.basename(filepath)
    with open(filepath, "rb") as f:
        image_data = f.read()

    boundary = "----WebKitFormBoundary" + str(random.randint(10**15, 10**16))
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="image"; filename="{filename}"\r\n'
        f"Content-Type: image/png\r\n\r\n"
    ).encode() + image_data + f"\r\n--{boundary}--\r\n".encode()

    req = urllib.request.Request(
        f"{server_url}/upload/image",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    resp = urllib.request.urlopen(req)
    result = json.loads(resp.read())
    return result.get("name", filename)


# ---------------------------------------------------------------------------
# SAM-based generation
# ---------------------------------------------------------------------------

def generate_with_sam(positive_prompt, index, raw_dir, ref_image_name=None, seed=None):
    """Generate one sticker using the generate_with_sam.json workflow.

    The workflow produces two saved images per run:
      - node 9  (filename_prefix "sticker_raw")  - raw generated image with background
      - node 25 (filename_prefix "sticker_nobg") - SAM-segmented transparent PNG

    Both are downloaded and saved to raw_dir:
      sticker_{index:02d}_raw.png
      sticker_{index:02d}_nobg.png

    Returns (raw_path, nobg_path).  Either may be None if the node produced no output.
    """
    with open(SAM_WORKFLOW_FILE, "r", encoding="utf-8") as f:
        workflow = json.load(f)

    # Positive / negative prompts
    workflow["6"]["inputs"]["text"] = positive_prompt
    workflow["7"]["inputs"]["text"] = config.NEGATIVE_PROMPT

    # Sampler settings
    workflow["3"]["inputs"]["seed"] = seed if seed is not None else random.randint(0, 2**32 - 1)
    workflow["3"]["inputs"]["steps"] = config.STEPS
    workflow["3"]["inputs"]["cfg"] = config.CFG_SCALE
    workflow["3"]["inputs"]["sampler_name"] = config.SAMPLER
    workflow["3"]["inputs"]["scheduler"] = config.SCHEDULER

    # Image dimensions
    workflow["5"]["inputs"]["width"] = config.IMAGE_WIDTH
    workflow["5"]["inputs"]["height"] = config.IMAGE_HEIGHT

    # IP-Adapter reference image
    if ref_image_name:
        workflow["12"]["inputs"]["image"] = ref_image_name
    else:
        workflow["12"]["inputs"]["image"] = config.IPADAPTER_REFERENCE_IMAGE

    # File name prefixes for SaveImage nodes
    workflow["9"]["inputs"]["filename_prefix"] = f"sticker_{index:02d}_raw"
    workflow["25"]["inputs"]["filename_prefix"] = f"sticker_{index:02d}_nobg"

    print(f"  [#{index:02d}] Queuing SAM generation...")
    prompt_id = queue_prompt(workflow)

    print(f"  [#{index:02d}] Waiting for completion...")
    history = wait_for_completion(prompt_id)

    outputs = history.get("outputs", {})
    raw_path = None
    nobg_path = None

    # Save raw image (node 9)
    if "9" in outputs and outputs["9"].get("images"):
        img_info = outputs["9"]["images"][0]
        img_data = get_image(img_info["filename"], img_info["subfolder"], img_info["type"])
        raw_path = os.path.join(raw_dir, f"sticker_{index:02d}_raw.png")
        with open(raw_path, "wb") as f:
            f.write(img_data)
        print(f"  [#{index:02d}] Raw saved: {raw_path}")

    # Save SAM nobg image (node 25)
    if "25" in outputs and outputs["25"].get("images"):
        img_info = outputs["25"]["images"][0]
        img_data = get_image(img_info["filename"], img_info["subfolder"], img_info["type"])
        nobg_path = os.path.join(raw_dir, f"sticker_{index:02d}_nobg.png")
        with open(nobg_path, "wb") as f:
            f.write(img_data)
        print(f"  [#{index:02d}] NoBG saved: {nobg_path}")

    return raw_path, nobg_path


# ---------------------------------------------------------------------------
# Batch generation
# ---------------------------------------------------------------------------

def generate_all(theme, version, sticker_ids=None):
    """Generate all (or selected) stickers for a theme/version using the SAM workflow.

    Args:
        theme: Theme name (folder name under output/).
        version: Version string, e.g. "v1".
        sticker_ids: Optional list of 1-based sticker IDs to regenerate. If None,
                     all stickers in prompts.json are generated.
    """
    paths = config.get_paths(theme, version)
    raw_dir = paths["raw"]
    os.makedirs(raw_dir, exist_ok=True)

    prompts_file = config.get_prompts_file(theme, version)
    if not os.path.exists(prompts_file):
        raise FileNotFoundError(f"prompts.json not found: {prompts_file}")

    with open(prompts_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    stickers = data["stickers"]
    style_prefix = data.get("style_prefix", "")

    # Filter to requested sticker IDs if provided
    if sticker_ids:
        stickers = [s for s in stickers if s["id"] in sticker_ids]
        if not stickers:
            print(f"No matching stickers found for IDs: {sticker_ids}")
            return []

    # Ensure reference image is uploaded to ComfyUI
    ref_local = config.REFERENCE_IMAGE
    if os.path.exists(ref_local):
        print(f"\nUploading reference image to ComfyUI: {ref_local}")
        ref_name = upload_image(ref_local)
        print(f"  Uploaded as: {ref_name}")
    else:
        print(f"  Warning: reference image not found at {ref_local}, using workflow default.")
        ref_name = config.IPADAPTER_REFERENCE_IMAGE

    count = len(stickers)
    print(f"\n=== Generating {count} stickers [{theme}/{version}] ===\n")

    results = []
    for sticker in stickers:
        idx = sticker["id"]
        prompt_text = sticker.get("prompt", sticker.get("emotion", ""))
        full_prompt = f"{style_prefix}, {prompt_text}" if style_prefix else prompt_text
        seed = sticker.get("seed")

        raw_path, nobg_path = generate_with_sam(full_prompt, idx, raw_dir, ref_name, seed)
        results.append({"id": idx, "raw": raw_path, "nobg": nobg_path})

    print(f"\nDone! {len(results)} stickers generated in {raw_dir}")
    return results


if __name__ == "__main__":
    import sys
    theme = sys.argv[1] if len(sys.argv) > 1 else "default"
    version = sys.argv[2] if len(sys.argv) > 2 else config.get_next_version(theme)
    generate_all(theme, version)
