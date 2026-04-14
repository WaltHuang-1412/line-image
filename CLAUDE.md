# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

LINE sticker auto-generation pipeline. Generates AI sticker images via ComfyUI, removes backgrounds with SAM, formats to LINE spec, and packages for LINE Creators Market upload.

## Commands

```bash
# Individual steps
python main.py generate <theme> [version]          # Generate raw images (no SAM by default)
python main.py generate <theme> [version] --sam     # Generate with SAM bg removal
python main.py nobg <theme> <version>               # SAM bg removal on existing raw images
python main.py format <theme> <version>             # Format to LINE spec
python main.py package <theme> <version>            # Package into ZIP

# Fix specific stickers by ID (regenerate only, no format)
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
    ├── raw/                  # sticker_XX.png + sticker_XX_nobg.png (gitignored)
    ├── formatted/            # Working dir, intermediate output (gitignored from v8 onwards)
    ├── zh/                   # Chinese version final stickers (with text overlay)
    ├── ja/                   # Japanese version final stickers (with text overlay)
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

Each language folder (zh/, ja/) contains the final stickers ready for packaging. The `formatted/` folder is a working directory (gitignored) — not final output.

**Note:** `fix` command's built-in reformat outputs to `formatted/` without text overlay. Always run `python main.py format --lang <lang>` after fix to update the language folders with proper text overlays. Only format the changed stickers when possible, not all 16.

## Execution Modes

### Explore Mode (default)
Triggered by: 測試、看看、試試、比較、給我看、風格、or any exploratory/creative request.
- Do exactly what was asked, nothing more.
- After completing the task, STOP and wait for the user's next instruction.
- Do NOT run QA, checks, status polls, or any follow-up commands.
- Do NOT run background commands to monitor progress after the task completes.

### Pipeline Mode
Triggered by: user explicitly requests a full pipeline step (generate, format, QA, fix, package) or says to run the full flow.
- Follow the Development Workflow and QA Checklist below.
- Advance through QA → fix → re-QA loops as documented.
- Still wait for user confirmation at stage gates (zh → ja → package).

**When in doubt, treat it as Explore Mode.** Only enter Pipeline Mode when the user clearly asks for a pipeline operation.

## Development Workflow

prompts.json 的 `"type"` 欄位決定用哪個流程（`"sticker"` 或 `"emoji"`）。

### Shared: Planning (Phase 1)
1. **Market research** — Search LINE sticker/emoji trends, identify gaps.
2. **Theme discussion** — Propose concepts, get user approval.
3. **Emotion planning** — Plan emotions. Collect all v3+ emotions and ensure zero duplicates. Present for user approval.
4. **LINE rule check** — Cross-check emotions against `line_rule.md`.

### Shared: Style (Phase 2)
5. **Test style** — Generate 2-3 test images, let user compare.
6. **Record settings** — Save `style_prefix` and `negative_prompt` into prompts.json.
7. **Style confirmation** — 判斷條件：
   - 沿用舊風格（style_prefix / IP-Adapter 跟之前版本一樣）→ 自動通過
   - 新風格（新角色、新 style_prefix、第一版）→ ★ USER CONFIRMS STYLE

---

### Sticker Pipeline (type: "sticker")

```
Phase 3: 生圖
 8. 生圖（不含去背）
 9. Raw QA（自動）：語意、文字、品質、美感、背景均勻、角色分離
10. 修復循環：
    a. 沒過的重生（同 prompt，換 seed）
    b. 重跑 Raw QA
    c. 還沒過 → 回到 a（最多 3 次）
    d. 3 次還沒過 → 調整 prompt 再重試
    e. prompt 調整後還沒過 → 停下來報告用戶
11. ★ 用戶確認 Raw

Phase 4: Background Removal
12. nobg (SAM → rembg → flood fill)
13. Nobg QA (auto): bg_clean, body_intact
14. Fix loop: 沒過的重跑去背 → 重跑 Nobg QA
15. ★ USER CONFIRMS NOBG

Phase 5: Format (zh)
16. format --lang zh (加文字 overlay)
17. Format QA (auto): bg_clean, quality
18. ★ USER CONFIRMS ZH

Phase 6: Format (ja)
19. format --lang ja
20. ja QA
21. ★ USER CONFIRMS JA

Phase 7: Package & Publish
22. Package
23. Prepare listing.md
24. Commit
25. Upload & submit
```

### Emoji Pipeline (type: "emoji")

```
Phase 3: 生圖
 8. 生圖（不含去背）
 9. Raw QA（自動）：語意、表情、構圖、文字、品質、美感、裝飾、背景均勻、角色分離
10. 修復循環：
    a. 沒過的重生（同 prompt，換 seed）
    b. 重跑 Raw QA
    c. 還沒過 → 回到 a（最多 3 次）
    d. 3 次還沒過 → 調整 prompt 再重試
    e. prompt 調整後還沒過 → 停下來報告用戶
11. ★ 用戶確認 Raw

Phase 4: Background Removal
12. nobg (SAM → flood fill)
13. Nobg QA (auto): bg_clean, body_intact
14. Fix loop: 沒過的重跑去背 → 重跑 Nobg QA
15. ★ USER CONFIRMS NOBG

Phase 5: Format
16. format (縮到 180×180，無邊距，無文字)
17. Format QA (auto): bg_clean, quality
18. ★ USER CONFIRMS FORMAT

Phase 6: Package & Publish
19. Package
20. Prepare listing.md
21. Commit
22. Upload & submit
```

### ★ USER CONFIRMS 規則

- 標有 ★ 的步驟必須等用戶明確說 OK 才能繼續下一階段
- QA 通過 ≠ 用戶通過。QA 通過只代表可以給用戶看
- **絕對不能跳過 USER CONFIRMS 步驟**
- 用戶確認前不要開始下一階段的任何操作

#### Upload API Details
- Session: `line_session.json` (Playwright browser context, refresh with `--login` if expired)
- Tag mapping: `line_tags.json` (444 tags, scraped from LINE Creators Market tag page)
- CSRF: `X-XSRF-TOKEN` header from `XSRF-TOKEN` cookie
- API prefix: `https://creator.line.me/my/{seller_id}`
- Create: `POST /api/v2/sticker` (JSON: type, metas, copyright, categoryIds, isAiGenerated, etc.)
- Set count: `POST /api/sticker/{id}/stickers_per_set` (FormData)
- Upload image: `POST /api/sticker/{id}/upload_image` (FormData: field name is `image`, not `sticker_image`)
- Tag: `POST /api/sticker/{id}/update_taggings` (JSON: `{"01": ["tag_id_1", ...]}`)
- Submit: `POST /sticker/{id}/do_request`
- Cancel: `POST /sticker/{id}/cancel_request`
- LINE API responses have `)]}'` XSS prefix — strip before JSON parsing.

## QA System

QA 使用模組化架構 `qa/`，每個檢查項目是獨立的 `.py` 檔。用 Ollama gemma3:12b，不用 Claude tokens。

### QA 模組

```
qa/
├── __init__.py        — 流程控制，根據 profile 跑對應 checks
├── ollama.py          — Ollama API 共用
├── semantic.py        — 表情是否匹配 emotion
├── expression.py      — 表情誇張度（emoji）
├── composition.py     — 構圖是否填滿（emoji）
├── text_artifacts.py  — 有沒有亂生文字
├── quality.py         — 品質評分（≥3 才過）
├── aesthetics.py      — 美感評分（≥4 才過）
├── bg_clean.py        — 背景是否乾淨
├── body_intact.py     — 身體是否完整
└── decorations.py     — 裝飾元素有沒有畫出來（emoji）
```

### 使用方式

```python
import qa
failed = qa.run_stage('圓滾貓的日常', 'v8', 'raw_qa')        # 跑 raw QA
failed = qa.run_stage('圓滾貓的日常', 'v8', 'nobg_qa')       # 跑 nobg QA
failed = qa.run_stage('圓滾貓的日常', 'v8', 'raw_qa', sticker_ids=[3, 5])  # 只跑特定張
```

哪個 stage 跑哪些 checks 由 `config.PRODUCT_PROFILES` 定義，根據 prompts.json 的 `type` 自動選擇。

### QA 規則

- **QA 通過 ≠ 用戶通過** — QA 通過只代表可以給用戶看，不代表可以進下一步
- **Fix → re-QA** — 每次 fix 後必須重跑 QA
- **不能跳過 USER CONFIRMS** — 見上方 Pipeline 的 ★ 標記
- **加新 check** — 新增 `qa/xxx.py`，在 `config.PRODUCT_PROFILES` 的對應 list 加名字

### GPU Resource Management

ComfyUI and Ollama gemma3:12b cannot run simultaneously on a single GPU (GTX 1080 Ti 11GB).
- **Before generate/fix**: `ollama stop gemma3:12b` → free GPU → then run ComfyUI.
- **Before QA with 12b**: Stop or ensure ComfyUI is idle, clear queue if stuck (`POST /queue` with `{"clear": true}`).
- **After timeouts**: Always clear ComfyUI queue and `POST /free` before retrying.

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
