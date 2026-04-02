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

ComfyUI must be running before generate/fix (auto-start if not running):
```bash
cd ComfyUI && python main.py --listen    # run in background
```

Ollama must be running before QA:
```bash
ollama serve                              # if not already running
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
  "sam_detect_prompt": "cat",
  "reference_image": "v3.png",
  "ipadapter_weight": 0.5,
  "character_desc": "round chubby grey cat, ink painting style",
  "character_parts": "ears, belly, paws",
  "stickers": [
    {"id": 1, "emotion": "smug", "prompt": "sly smirk, half-closed eyes", "seed": 12345},
    {"id": 2, "emotion": "angry", "prompt": "puffed up, red face"}
  ]
}
```

- `style_prefix` is concatenated with each sticker's `prompt`. `seed` is optional (random if omitted).
- `negative_prompt` overrides `config.NEGATIVE_PROMPT` when set. Always save the actual negative prompt used here to preserve reproducibility.
- `emotion` field is used as text overlay during format step.

### Per-theme Config (all optional, fallback to config.py defaults)

| Field | Default | Purpose |
|-------|---------|---------|
| `sam_detect_prompt` | `"cat"` | GroundingDINO detection word for SAM segmentation (workflow node 22) |
| `reference_image` | `v3.png` | IP-Adapter reference image. Searched in: version dir → theme dir → project root |
| `ipadapter_weight` | `0.5` | IP-Adapter style conditioning strength |
| `character_desc` | `"round chubby grey cat, ink painting style"` | Used in QA prompts to describe the character |
| `character_parts` | `"ears, belly, paws"` | Body parts listed in QA bg-check prompt for cutoff detection |

Old prompts.json files without these fields work unchanged — all fallback to `config.py` constants.

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

1. **Design style** — Test prompts + IP-Adapter in ComfyUI UI, lock down reference image
2. **Record settings** — Save the working `style_prefix` and `negative_prompt` into prompts.json (extract from PNG metadata if needed: `PIL.Image.open(img).info['prompt']`)
3. **Plan content** — Define 16 emotions + action prompts in prompts.json. Check against all v3+ emotions to avoid duplicates.
4. **Generate** — Start ComfyUI if not running, then `python main.py generate <theme> <version>`
5. **Raw QA** — Run full QA checklist on every raw image (see QA Checklist below). Fix failures and re-QA until all pass.
6. **Format zh** — `python main.py format <theme> <version> --lang zh`. Do NOT format to ja/ until zh is confirmed.
7. **zh QA** — Run full QA checklist on zh/ stickers. Fix and re-format until all pass.
8. **User confirms zh** — Wait for explicit user approval before proceeding.
9. **Format ja** — Create `ja/prompts.json` with Japanese emotions, then `python main.py format <theme> <version> --lang ja`
10. **ja QA** — Run full QA checklist on ja/ stickers.
11. **User confirms ja** — Wait for explicit user approval.
12. **Package** — `python main.py package <theme> <version>`
13. **Prepare listing** — Write title/description in 3 languages, save to listing.md

## QA Checklist

Use Ollama (`qa_vision.py` or custom prompts with gemma3:4b) for all image checks. Never use Claude tokens on images.

### Raw QA (every sticker, no exceptions)

| Check | What to look for | Auto-pass criteria |
|-------|------------------|--------------------|
| **Style consistency** | Same character, same art style across all 16 | All match reference |
| **Anatomy** | Extra limbs, fused legs, missing body parts, deformed face | None found |
| **Semantic match** | Expression/pose matches intended emotion | YES (relax for abstract social emotions) |
| **Text artifacts** | AI-generated random text in the image | None found |
| **Quality / Aesthetics** | Clean, appealing, sellable as a commercial sticker | Score >= 3, no ugly/broken |
| **nobg quality** | SAM didn't eat body parts, no holes in subject | Visual check, not just content ratio |

### Formatted / Language QA (every sticker)

| Check | What to look for | Auto-pass criteria |
|-------|------------------|--------------------|
| **Background** | Fully transparent, no leftover color patches or artifacts | CLEAN |
| **Body cutoff** | Cat body parts not clipped at image edges | None cut off |
| **Text overlay** | Label displays correctly, positioned right, doesn't cover cat face | Correct |
| **Background removal** | No remnants from flood-fill or SAM, clean edges | Clean |
| **Overall quality** | Commercial-grade sticker, would you buy it? | Score >= 3 |

### QA Rules

- **Check ALL items** — never skip checks because one category failed. Semantic fail does not excuse skipping anatomy/text/quality.
- **Don't trust numbers alone** — content ratio OK doesn't mean nobg is OK. Visually verify.
- **Ollama PASS is not user PASS** — QA passing means ready for user review, not approved for production.
- **Fix → re-QA → confirm** — every fix must be followed by re-QA of the fixed stickers. Loop until all pass.
- **Don't advance stages without user confirmation** — zh must be user-approved before ja. ja must be user-approved before package.
- **Second-pass flagged items** — when Ollama flags TEXT or CUTOFF, run a focused second check before marking as real failure. Ollama frequently misreports Chinese labels as unwanted text.

### Ollama Known Limitations (gemma3:4b)

- **Semantic check unreliable for non-expression emotions** — social/action concepts (約嗎, +1, 在哪) can't be matched to facial expressions. Expect false negatives; don't skip other checks because of semantic failures.
- **TEXT false positives** — frequently flags intentional Chinese text labels or decorative marks (～！？) as unwanted text. Always do a second-pass confirmation.
- **CUTOFF false positives** — may confuse text overlay areas near edges with body cutoff. Confirm with a focused prompt.
- **Inconsistent response format** — sometimes doesn't follow the requested answer format. Parse defensively and fall back to detailed prompts when structured QA fails.

### Operations Notes

- **Auto-start ComfyUI** — if ComfyUI is not running, start it yourself with `cd ComfyUI && python main.py --listen` (run_in_background). Never ask the user to start it.
- **GPU memory** — after timeouts or multiple generations, free ComfyUI memory with `POST http://127.0.0.1:8188/free` before retrying.
- **Japanese format encoding** — use `PYTHONIOENCODING=utf-8` when running format with `--lang ja` to avoid cp950 encoding errors on Windows.
- **fix command does NOT apply text overlay** — always run `python main.py format <theme> <version> --lang <lang>` after fix to get proper text overlays.
