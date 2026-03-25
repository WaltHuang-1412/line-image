# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

LINE sticker auto-generation pipeline. Generates AI sticker images via ComfyUI, removes backgrounds with SAM, formats to LINE spec, and packages for LINE Creators Market upload.

## Commands

```bash
# Full pipeline (generate → format → package), auto-increments version
python main.py all <theme> [version]

# Individual steps
python main.py generate <theme> [version]
python main.py format <theme> <version>
python main.py package <theme> <version>

# Fix specific stickers by ID (regenerate + re-format)
python main.py fix <theme> <version> <id> [<id> ...]

# List all themes and versions
python main.py list
```

ComfyUI must be running before generate/fix:
```bash
cd ComfyUI && python main.py --listen
```

## Architecture

### Pipeline Flow

```
prompts.json → [GENERATE via ComfyUI] → raw/ → [FORMAT: bg removal + resize + text overlay] → formatted/ → zh/ja/ → [PACKAGE: ZIP] → package/
```

### Key Modules

- **`generate.py`** — ComfyUI API client. Submits `workflow/generate_with_sam.json` with per-sticker prompts. Produces two outputs per sticker: `sticker_XX.png` (with background) and `sticker_XX_nobg.png` (SAM-segmented transparent). Uses IP-Adapter with `v3.png` reference for style consistency. Reads `style_prefix` and `negative_prompt` from prompts.json.
- **`format_stickers.py`** — Background removal + LINE spec conversion + text overlay. Tries SAM nobg first; falls back to flood-fill from corners if SAM ate too much (content ratio < 5%). Adds emotion text with decorative marks, alternating top/bottom position. Outputs 370×320 stickers, 240×240 main, 96×74 tab.
- **`package.py`** — ZIPs formatted stickers with sequential naming (01.png, 02.png...) + metadata.json.
- **`config.py`** — All constants, path helpers, version management. `get_prompts_file()` checks version-level then theme-level prompts.json.

### ComfyUI Integration

The workflow (`workflow/generate_with_sam.json`) is a 10-node DAG:
- AnimagineXL 3.1 checkpoint → IP-Adapter (style lock via reference image) → KSampler → VAEDecode → two save branches:
  - Node 9: raw image with background
  - Node 25: SAM+GroundingDINO segmented → InvertMask → JoinImageWithAlpha → transparent PNG

API pattern: POST `/prompt` → poll `/history/{id}` → GET `/view` to download images. Reference images uploaded via `/upload/image`.

### Output Structure

```
output/{theme}/
├── prompts.json              # Theme-level sticker definitions (fallback)
└── {version}/
    ├── prompts.json          # Version-specific (style_prefix + negative_prompt + stickers)
    ├── listing.md            # LINE Creators Market listing text (ZH/EN/JA)
    ├── raw/                  # sticker_XX.png + sticker_XX_nobg.png
    ├── formatted/            # sticker_XX.png (370×320) + main.png + tab.png (working dir)
    ├── zh/                   # Chinese version final stickers
    ├── ja/                   # Japanese version final stickers
    └── package/              # stickers.zip + metadata.json
```

**Important:** Do not delete `_nobg.png` files — they are needed for clean background removal during format. Without them, format falls back to flood-fill which produces worse results.

### Background Removal Strategy

SAM segments by detecting "cat" via GroundingDINO. When the subject is white/light-colored, SAM may remove body parts along with the background. The fallback flood-fill algorithm seeds from all four image corners and removes connected similar-color regions, preserving the subject regardless of color.

## Models (stored in ComfyUI/models/)

| Path | Model | Purpose |
|------|-------|---------|
| `checkpoints/animagine-xl-3.1.safetensors` | AnimagineXL 3.1 | Image generation (SDXL) |
| `diffusion_models/z-image-turbo_fp8_scaled_e4m3fn_KJ.safetensors` | Z-Image-Turbo FP8 | Alternative model (DiT, 8 steps) |
| `text_encoders/qwen_3_4b.safetensors` | Qwen 3 4B | Text encoder for Z-Image-Turbo |
| `vae/ae.safetensors` | Flux VAE | VAE for Z-Image-Turbo |
| `sams/sam_vit_b_01ec64.pth` | SAM ViT-B | Segment Anything |
| `grounding-dino/groundingdino_swint_ogc.pth` | GroundingDINO | Object detection for SAM |
| `ipadapter/ip-adapter_sdxl_vit-h.safetensors` | IP-Adapter SDXL | Style conditioning |
| `clip_vision/CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors` | CLIP Vision | Vision encoder for IP-Adapter |

## LINE Sticker Specs

- Sticker: 370×320 px, PNG, transparent background, 10px margin, <1MB
- Main image: 240×240 px
- Tab image: 96×74 px
- Allowed counts: 8, 16, 24, 32, or 40 stickers per pack

## prompts.json Format

```json
{
  "title": "Pack Title",
  "description": "Pack description",
  "style_prefix": "prepended to all prompts",
  "negative_prompt": "overrides config.NEGATIVE_PROMPT if set",
  "stickers": [
    {"id": 1, "emotion": "smug", "prompt": "sly smirk, half-closed eyes", "seed": 12345},
    {"id": 2, "emotion": "angry", "prompt": "puffed up, red face"}
  ]
}
```

- `style_prefix` is concatenated with each sticker's `prompt`. `seed` is optional (random if omitted).
- `negative_prompt` overrides `config.NEGATIVE_PROMPT` when set. Always save the actual negative prompt used here to preserve reproducibility.
- `emotion` field is used as text overlay during format step.

### Format Text Overlay

`format_stickers.py` adds Chinese text (from `emotion` field) onto each sticker during formatting:
- Odd sticker IDs: text on top, cat on bottom
- Even sticker IDs: text on bottom, cat on top
- Font: Microsoft JhengHei Bold, with white stroke and drop shadow
- Decorative marks (～, ！, etc.) appended per emotion

### Multi-language Output

```
output/{theme}/{version}/
├── zh/            # Chinese version (text overlay in Chinese)
├── ja/            # Japanese version (text overlay in Japanese)
└── ...
```

Each language folder contains the final formatted stickers ready for packaging. The `formatted/` folder is the working directory used by `format` command.

**Note:** `fix` command's built-in reformat does NOT apply text overlay. Always run `python main.py format` after `fix` to get text.

## Development Workflow

1. **Design style** — Test prompts + IP-Adapter in ComfyUI UI, lock down `v3.png` reference image
2. **Record settings** — Save the working `style_prefix` and `negative_prompt` into prompts.json (extract from PNG metadata if needed: `PIL.Image.open(img).info['prompt']`)
3. **Plan content** — Define 16 emotions + action prompts in prompts.json
4. **Generate** — `python main.py generate <theme> <version>`
5. **Review raw** — Check each raw image for: wrong expression, extra limbs, text artifacts, non-white background
6. **Fix bad ones** — `python main.py fix <theme> <version> <id>` then `python main.py format <theme> <version>`
7. **Review formatted** — Check background removal quality, text overlay, sizing
8. **Copy to language folder** — Copy final formatted/ to zh/ (or ja/ for Japanese)
9. **Package** — `python main.py package <theme> <version>`
10. **Prepare listing** — Write title/description in 3 languages, save to listing.md
