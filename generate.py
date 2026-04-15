"""Call ComfyUI API to generate sticker images using generate_with_sam.json workflow."""
import json
import os
import random
import time
import urllib.request
import urllib.parse

import config

SAM_WORKFLOW_FILE = os.path.join(config.BASE_DIR, "workflow", "generate_with_sam.json")
GENERATE_ONLY_WORKFLOW_FILE = os.path.join(config.BASE_DIR, "workflow", "generate_only.json")
SAM_ONLY_WORKFLOW_FILE = os.path.join(config.BASE_DIR, "workflow", "sam_only.json")


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
# SAM-only background removal
# ---------------------------------------------------------------------------

def sam_remove_bg(raw_path, nobg_output_path, sam_detect_prompt=None):
    """Run SAM background removal on an existing raw image via ComfyUI.

    Uploads the raw image, runs SAM segmentation, downloads the result.
    Returns nobg_output_path on success, None on failure.
    """
    with open(SAM_ONLY_WORKFLOW_FILE, "r", encoding="utf-8") as f:
        workflow = json.load(f)

    # Upload raw image to ComfyUI
    uploaded_name = upload_image(raw_path)
    workflow["1"]["inputs"]["image"] = uploaded_name
    workflow["22"]["inputs"]["prompt"] = sam_detect_prompt or config.SAM_DETECT_PROMPT

    idx_str = os.path.basename(raw_path).replace("sticker_", "").replace(".png", "")
    workflow["25"]["inputs"]["filename_prefix"] = f"sticker_{idx_str}_nobg"

    prompt_id = queue_prompt(workflow)
    history = wait_for_completion(prompt_id)

    outputs = history.get("outputs", {})
    if "25" in outputs and outputs["25"].get("images"):
        img_info = outputs["25"]["images"][0]
        img_data = get_image(img_info["filename"], img_info["subfolder"], img_info["type"])
        with open(nobg_output_path, "wb") as f:
            f.write(img_data)
        return nobg_output_path
    return None


def _check_nobg_quality(raw_path, nobg_path):
    """Check SAM nobg quality. Returns (ok, reason) tuple."""
    from format_stickers import _content_ratio, _has_interior_holes
    from PIL import Image

    nobg_img = Image.open(nobg_path).convert("RGBA")
    ratio = _content_ratio(nobg_img)

    if ratio < config.SAM_CONTENT_RATIO_MIN:
        return False, f"content ratio too low ({ratio:.1%})"

    if _has_interior_holes(nobg_img):
        return False, "interior holes detected"

    # Compare with raw: if SAM lost >5% content vs flood fill, SAM ate body parts
    from format_stickers import flood_fill_remove_bg
    raw_img = Image.open(raw_path).convert("RGBA")
    flood_img = flood_fill_remove_bg(raw_img)
    flood_ratio = _content_ratio(flood_img)

    if flood_ratio > ratio + 0.05:
        return False, f"SAM lost content ({ratio:.1%} vs flood {flood_ratio:.1%})"

    return True, "ok"


def sam_remove_bg_all(theme, version, sticker_ids=None):
    """Run SAM background removal on all (or selected) raw stickers.

    After each SAM run, checks quality (content ratio, holes, body parts).
    Falls back to flood fill if SAM quality is bad.

    Args:
        theme: Theme name.
        version: Version string.
        sticker_ids: Optional list of sticker IDs. If None, process all.
    """
    from format_stickers import flood_fill_remove_bg
    from PIL import Image

    paths = config.get_paths(theme, version)
    raw_dir = paths["raw"]

    prompts_file = config.get_prompts_file(theme, version)
    with open(prompts_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    sam_detect_prompt = data.get("sam_detect_prompt", None)
    stickers = data["stickers"]
    if sticker_ids:
        stickers = [s for s in stickers if s["id"] in sticker_ids]

    print(f"\n=== Background removal: {len(stickers)} stickers [{theme}/{version}] ===\n")

    failed = []
    for s in stickers:
        idx = s["id"]
        raw_path = os.path.join(raw_dir, f"sticker_{idx:02d}.png")
        nobg_path = os.path.join(raw_dir, f"sticker_{idx:02d}_nobg.png")

        if not os.path.exists(raw_path):
            print(f"  [#{idx:02d}] raw not found, skipping")
            continue

        print(f"  [#{idx:02d}] SAM...", end="", flush=True)
        result = sam_remove_bg(raw_path, nobg_path, sam_detect_prompt)
        if not result:
            print(f" SAM FAILED, using flood fill...", end="", flush=True)
            raw_img = Image.open(raw_path).convert("RGBA")
            flood_img = flood_fill_remove_bg(raw_img)
            flood_img.save(nobg_path, "PNG")
            failed.append((idx, "SAM failed → flood fill"))
            print(f" done")
            continue

        # Check quality
        ok, reason = _check_nobg_quality(raw_path, nobg_path)
        if ok:
            print(f" PASS")
        else:
            print(f" FAIL ({reason}), using flood fill...", end="", flush=True)
            raw_img = Image.open(raw_path).convert("RGBA")
            flood_img = flood_fill_remove_bg(raw_img)
            flood_img.save(nobg_path, "PNG")
            failed.append((idx, reason + " → flood fill"))
            print(f" done")

    # Summary
    passed = len(stickers) - len(failed)
    print(f"\n  PASS: {passed}/{len(stickers)}")
    if failed:
        print(f"  Flood fill fallback: {[(f'#{i:02d} {r}') for i, r in failed]}")
    print(f"\nDone!")


# ---------------------------------------------------------------------------
# SAM-based generation
# ---------------------------------------------------------------------------

def generate_one(positive_prompt, index, raw_dir, ref_image_name=None, seed=None, negative_prompt=None, ipadapter_weight=None):
    """Generate one sticker image only (no SAM background removal).

    Uses generate_only.json workflow. Faster than generate_with_sam.
    Returns raw_path (str) or None.
    """
    with open(GENERATE_ONLY_WORKFLOW_FILE, "r", encoding="utf-8") as f:
        workflow = json.load(f)

    workflow["6"]["inputs"]["text"] = positive_prompt
    workflow["7"]["inputs"]["text"] = negative_prompt or config.NEGATIVE_PROMPT
    workflow["3"]["inputs"]["seed"] = seed if seed is not None else random.randint(0, 2**32 - 1)
    workflow["3"]["inputs"]["steps"] = config.STEPS
    workflow["3"]["inputs"]["cfg"] = config.CFG_SCALE
    workflow["3"]["inputs"]["sampler_name"] = config.SAMPLER
    workflow["3"]["inputs"]["scheduler"] = config.SCHEDULER
    workflow["5"]["inputs"]["width"] = config.IMAGE_WIDTH
    workflow["5"]["inputs"]["height"] = config.IMAGE_HEIGHT

    if ref_image_name:
        workflow["12"]["inputs"]["image"] = ref_image_name
    else:
        workflow["12"]["inputs"]["image"] = config.IPADAPTER_REFERENCE_IMAGE

    workflow["13"]["inputs"]["weight"] = ipadapter_weight if ipadapter_weight is not None else config.IPADAPTER_WEIGHT
    workflow["9"]["inputs"]["filename_prefix"] = f"sticker_{index:02d}"

    print(f"  [#{index:02d}] Queuing generation...")
    prompt_id = queue_prompt(workflow)

    print(f"  [#{index:02d}] Waiting for completion...")
    history = wait_for_completion(prompt_id)

    outputs = history.get("outputs", {})
    raw_path = None

    if "9" in outputs and outputs["9"].get("images"):
        img_info = outputs["9"]["images"][0]
        img_data = get_image(img_info["filename"], img_info["subfolder"], img_info["type"])
        raw_path = os.path.join(raw_dir, f"sticker_{index:02d}.png")
        with open(raw_path, "wb") as f:
            f.write(img_data)
        print(f"  [#{index:02d}] Saved: {raw_path}")

    return raw_path


def generate_with_sam(positive_prompt, index, raw_dir, ref_image_name=None, seed=None, negative_prompt=None, sam_detect_prompt=None, ipadapter_weight=None):
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
    workflow["7"]["inputs"]["text"] = negative_prompt or config.NEGATIVE_PROMPT

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

    # IP-Adapter weight
    workflow["13"]["inputs"]["weight"] = ipadapter_weight if ipadapter_weight is not None else config.IPADAPTER_WEIGHT

    # SAM GroundingDINO detect prompt
    workflow["22"]["inputs"]["prompt"] = sam_detect_prompt or config.SAM_DETECT_PROMPT

    # File name prefixes for SaveImage nodes
    workflow["9"]["inputs"]["filename_prefix"] = f"sticker_{index:02d}"
    workflow["25"]["inputs"]["filename_prefix"] = f"sticker_{index:02d}_nobg"

    print(f"  [#{index:02d}] Queuing generation...")
    prompt_id = queue_prompt(workflow)

    print(f"  [#{index:02d}] Waiting for completion...")
    history = wait_for_completion(prompt_id)

    outputs = history.get("outputs", {})
    raw_path = None

    # Save raw image (node 9)
    if "9" in outputs and outputs["9"].get("images"):
        img_info = outputs["9"]["images"][0]
        img_data = get_image(img_info["filename"], img_info["subfolder"], img_info["type"])
        raw_path = os.path.join(raw_dir, f"sticker_{index:02d}.png")
        with open(raw_path, "wb") as f:
            f.write(img_data)
        print(f"  [#{index:02d}] Saved: {raw_path}")

    # Save SAM nobg image (node 25)
    nobg_path = None
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

def generate_all(theme, version, sticker_ids=None, with_sam=True):
    """Generate all (or selected) stickers for a theme/version.

    Args:
        theme: Theme name (folder name under output/).
        version: Version string, e.g. "v1".
        sticker_ids: Optional list of 1-based sticker IDs to regenerate. If None,
                     all stickers in prompts.json are generated.
        with_sam: If True (default), use SAM workflow for generation + bg removal.
                  If False, generate images only (faster, no _nobg files).
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
    negative_prompt = data.get("negative_prompt", None)
    sam_detect_prompt = data.get("sam_detect_prompt", None)
    ipadapter_weight = data.get("ipadapter_weight", None)

    # Filter to requested sticker IDs if provided
    if sticker_ids:
        stickers = [s for s in stickers if s["id"] in sticker_ids]
        if not stickers:
            print(f"No matching stickers found for IDs: {sticker_ids}")
            return []

    # Ensure reference image is uploaded to ComfyUI
    # Per-theme reference image: check prompts.json, then theme dir, then global default
    ref_image_cfg = data.get("reference_image", None)
    if ref_image_cfg:
        # Try as path relative to theme/version dir, then theme dir, then absolute/base dir
        candidates = [
            os.path.join(config.get_version_dir(theme, version), ref_image_cfg),
            os.path.join(config.get_theme_dir(theme), ref_image_cfg),
            os.path.join(config.BASE_DIR, ref_image_cfg),
        ]
        ref_local = next((c for c in candidates if os.path.exists(c)), None)
        if not ref_local:
            print(f"  Warning: reference_image '{ref_image_cfg}' not found, using global default.")
            ref_local = config.REFERENCE_IMAGE
    else:
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

        if with_sam:
            raw_path, nobg_path = generate_with_sam(full_prompt, idx, raw_dir, ref_name, seed, negative_prompt, sam_detect_prompt, ipadapter_weight)
            results.append({"id": idx, "raw": raw_path, "nobg": nobg_path})
        else:
            raw_path = generate_one(full_prompt, idx, raw_dir, ref_name, seed, negative_prompt, ipadapter_weight)
            results.append({"id": idx, "raw": raw_path, "nobg": None})

    print(f"\nDone! {len(results)} stickers generated in {raw_dir}")
    return results


if __name__ == "__main__":
    import sys
    theme = sys.argv[1] if len(sys.argv) > 1 else "default"
    version = sys.argv[2] if len(sys.argv) > 2 else config.get_next_version(theme)
    generate_all(theme, version)
