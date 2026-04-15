# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

LINE sticker auto-generation pipeline. Generates AI sticker images via ComfyUI, removes backgrounds with SAM, formats to LINE spec, and packages for LINE Creators Market upload.

## Commands

```bash
# Individual steps — 每個指令只做一件事，不會偷跑其他步驟
python main.py generate <theme> [version]          # 生 raw 圖（不含去背）
python main.py generate <theme> [version] --sam     # 生 raw 圖 + SAM 去背（產 _nobg.png）
python main.py nobg <theme> <version>               # 對已有的 raw 圖跑 SAM 去背
python main.py format <theme> <version>             # 去背 + 縮圖 + 文字（LINE 規格）
python main.py package <theme> <version>            # 打包 ZIP

# 重生特定張（只產 raw，不跑 SAM，不跑 format）
python main.py fix <theme> <version> <id> [<id> ...]

# 列出所有主題和版本
python main.py list
```

**`fix` 指令行為：只重生 raw 圖。** 不產 `_nobg.png`，不做 format，不做任何後續步驟。去背、格式化都是獨立指令，要用就自己跑。

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
- **`format_stickers.py`** — Sticker-only format（type="sticker"）。Background removal + LINE spec conversion + text overlay. Adds emotion text with decorative marks, alternating top/bottom position. Outputs 370×320 stickers, 240×240 main, 96×74 tab.
- **`format_emoji.py`** — Emoji-only format（type="emoji"）。Background removal + 縮到 180×180，無邊距，無文字。輸出 180×180 emoji + 96×74 tab（emoji **沒有獨立的 240×240 main**，sticker 才有；表情貼本體即為「主要圖片」）。共用 `format_stickers.py` 的底層 helper（remove_background、optimize_png、_fit_on_canvas）。
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

### Prompt Strengthening for Clean Backgrounds (v8+ learning)

AnimagineXL + ink painting style 必然產生背景紋理/漸層。新版 prompts.json 的 `style_prefix` 和 `negative_prompt` **必須**加以下強化詞，否則背景會糟到過不了 `bg_uniform` QA：

**style_prefix 必備：**
```
solid flat single color background, plain background, no gradient, no shadow, no texture, bright saturated orange background
```

**negative_prompt 必備：**
```
gradient background, textured background, shadow on background, dark background, detailed background
```

單純寫 `light green background` 不夠，v8 實測 15/16 張會失敗。加了強化詞才能穩定產出可去背的圖。

### 背景色選擇原則（v8+ 血淚教訓）

背景色不能跟角色身上或任何裝飾元素同色，否則 SAM/flood fill 會吃掉這些元素。選色前**必須**審一遍 prompts.json 的所有 emotion 裝飾。

**角色色（圓滾貓例）：** 灰身、白臉白肚、粉頰、黑眼珠

**表情裝飾色（要避開）：**
- 白色：sparkles、stars、steam、puffs、ghost、bubbles、ZZZ
- 藍色：tears、sweat drops、teardrops
- 粉/紅：hearts、cheeks、veins
- 黃色：sparkles、stars
- 黑色：ZZZ 外框、dots
- 綠色：stink lines

**v8 實測流程：**
1. `light green` → ink painting 產生紋理，QA 失敗 15/16
2. `cyan` → 跟藍淚水撞色（#02, #04, #07, #12）
3. `bright saturated orange` → 成功（不在任何角色/裝飾色上）

### Ink Painting Style 去背陷阱（v8+）

`ink painting style, brush strokes` 這類畫風**會在角色旁邊產生墨點噴濺**，SAM 會把噴濺當成貓的一部分納入 mask → 去背後有殘留黑塊。

**解法：** outlier 的 per-sticker prompt 加
```
clean outline, no ink splashes, no background artifacts
```
不要全部加（太一致會失去畫風）。只在 nobg QA 失敗時，發現某張有背景噴濺，才加。

### Flood Fill 吃掉同色細節（v8+）

Flood fill 從四角填同色區域。如果角色內部有跟**背景同色的小細節**（例：橘色背景 + 淺橘瞳孔），flood fill 會把這些小細節一起吃掉 → `body_intact` 不一定抓得到（過小被忽略），但視覺上很明顯。

**規避：**
- 第一選擇：用 SAM（semantic 判定，不看顏色）
- Flood fill 只在 SAM 壞掉時用，**且**確認角色內沒有跟背景同色的細節
- 檢查瞳孔色是否跟背景色太接近，避免 pale pupils on similar bg

### bg removal fix loop 策略（v8+）

nobg QA 失敗時，照優先序試：

1. **SAM 原結果** — 保留所有細節，但可能有邊緣殘留
2. **後處理 alpha 閾值**（砍半透明邊）— 只對「半透明暈邊」有用，對不透明色塊殘留無效
3. **重生 raw + 加 `clean outline, no ink splashes`** — 最根本，適用墨點噴濺
4. **flood fill** — 最後手段，只在確定沒有同色細節時用

### bg_uniform QA 判定標準（v8+）

`qa/bg_uniform.py` 的判定邏輯是「去背可行性」，**不是**「完美純色」。容許畫風紋理（ink painting 的筆觸），但會抓真正影響去背的問題：強漸層、暗影、多色塊、vignette。

**為什麼：** ink painting style 永遠有筆觸紋理，如果要求「完美純色」，v8 實測不管怎麼調 prompt 都只有 1/16 能過。改成「可去除」標準後 14/16 通過。

新畫風（watercolor、sketch 等有筆觸的）沿用這個標準。純數位風格（flat vector）可以自訂更嚴格的 check。

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

**Note:** `fix` 只重生 raw 圖。後續步驟（nobg、format）需要自己分別跑。

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
 8. python main.py generate <theme> <version>
    → 只產 raw/sticker_XX.png，不產 nobg
 9. Raw QA（用 Ollama，不用 Claude）：
    → python -c "import qa; qa.run_stage('<theme>', '<version>', 'raw_qa')"
    → checks: semantic, text_artifacts, quality, aesthetics, bg_uniform, bg_color, separation
    → bg_uniform + bg_color + separation 必須通過才能進 Phase 4（不通過 = 去背會爛）
10. 修復循環：
    a. python main.py fix <theme> <version> <失敗的 id>（只重生 raw，不跑 SAM，不跑 format）
    b. 重跑 Raw QA（只跑失敗的張）
    c. 還沒過 → 回到 a（最多 3 次）
    d. 3 次還沒過 → 調整 prompt 再重試
    e. prompt 調整後還沒過 → 停下來報告用戶
11. 風格一致性檢查（跨張比對，見下方「風格一致性」節）
    → 用戶比對 16 張的姿勢/比例/構圖是否統一
    → 找出 outlier（例：頭特大、全身姿、躺平等），調 prompt 重生
12. ★ 用戶確認 Raw

Phase 4: Background Removal
13. python main.py nobg <theme> <version>
    → SAM → flood fill fallback
14. Nobg QA（用 Ollama）：
    → python -c "import qa; qa.run_stage('<theme>', '<version>', 'nobg_qa')"
    → checks: bg_clean, body_intact
15. Fix loop（照優先序，見下方「bg removal fix loop 策略」）：
    a. 先重試 SAM（呼叫 sam_remove_bg 直接，不要重跑 nobg 整體）
    b. 還是 bg_clean FAIL → 重生 raw 加 "clean outline, no ink splashes, no background artifacts"
    c. **不要**隨便用 flood fill 救場，會吃同色細節（如跟背景同色的瞳孔）
15. ★ USER CONFIRMS NOBG

Phase 5: Format (zh)
16. python main.py format <theme> <version> --lang zh
17. Format QA（用 Ollama）：bg_clean, quality
18. ★ USER CONFIRMS ZH

Phase 6: Format (ja)
19. PYTHONIOENCODING=utf-8 python main.py format <theme> <version> --lang ja
20. ja QA
21. ★ USER CONFIRMS JA

Phase 7: Package & Publish
22. python main.py package <theme> <version>
23. Prepare listing.md
24. Commit
25. Upload & submit
```

### Emoji Pipeline (type: "emoji")

```
Phase 3: 生圖
 8. python main.py generate <theme> <version>
    → 只產 raw/sticker_XX.png，不產 nobg
 9. Raw QA（用 Ollama，不用 Claude）：
    → python -c "import qa; qa.run_stage('<theme>', '<version>', 'raw_qa')"
    → checks: semantic, expression, composition, text_artifacts, quality, aesthetics, decorations, bg_uniform, bg_color, separation
    → bg_uniform + bg_color + separation 必須通過才能進 Phase 4（不通過 = 去背會爛）
10. 修復循環：
    a. python main.py fix <theme> <version> <失敗的 id>（只重生 raw，不跑 SAM，不跑 format）
    b. 重跑 Raw QA（只跑失敗的張）：
       → python -c "import qa; qa.run_stage('<theme>', '<version>', 'raw_qa', sticker_ids=[...])"
    c. 還沒過 → 回到 a（最多 3 次）
    d. 3 次還沒過 → 調整 prompt 再重試
    e. prompt 調整後還沒過 → 停下來報告用戶
11. 風格一致性檢查（跨張比對，見下方「風格一致性」節）
    → 用戶比對 16 張的姿勢/比例/構圖是否統一
    → 找出 outlier（例：頭特大、全身姿、躺平等），調 prompt 重生
12. ★ 用戶確認 Raw

Phase 4: Background Removal
12. python main.py nobg <theme> <version>
    → SAM → flood fill fallback
13. Nobg QA（用 Ollama）：
    → python -c "import qa; qa.run_stage('<theme>', '<version>', 'nobg_qa')"
    → checks: bg_clean, body_intact
14. Fix loop: 沒過的重跑去背 → 重跑 Nobg QA
15. ★ USER CONFIRMS NOBG

Phase 5: Format
16. python main.py format <theme> <version>
    → 縮到 180×180，無邊距，無文字
17. Format QA（用 Ollama）：bg_clean, quality
18. ★ USER CONFIRMS FORMAT

Phase 6: Package & Publish
19. python main.py package <theme> <version>
20. Prepare listing.md
21. Commit
22. Upload & submit
```

### 關鍵規則（每次都要遵守，不要再犯）

- **QA 用 Ollama（`qa.run_stage()`），絕對不用 Claude 看圖** — 浪費 token 且不可靠。**例外**：跨張風格一致性（Ollama 做不到）
- **fix 只重生 raw** — 不產 nobg，不做 format，不做任何後續步驟
- **bg_uniform + bg_color + separation 是去背的前置條件** — 這 3 項沒過就不能進 Phase 4，要修到過
- **每個步驟用上面寫的指令** — 不要自己猜指令、加參數、組合步驟
- **背景色不能跟角色/裝飾色撞** — 選色前審所有 emotion prompts，見「背景色選擇原則」
- **nobg 失敗不要先 flood fill** — 會吃同色細節，優先重生 raw 加 "no ink splashes"
- **listing.md 全部用半形** — `:` 不是 `：`、`!` 不是 `！`、`,` 不是 `、`/`，`、(` 不是 `（`、`)` 不是 `）`、`...` 不是 `⋯⋯`、`/` 不是 `／`、`-` 不是 `—`
- **listing.md 必填版權區塊** — 結尾要有 `### 版權\nCopyright (C) <year> Walter Studio`，否則 upload_line.py 抓不到送審會失敗
- **標題不能跟既有作品撞** — 上架前先查 LINE Creators Market；同系列換版要在標題加區別詞（如「表情絵文字」對應 emoji，避開貼圖系列名）

### 風格一致性檢查

Raw QA 是**逐張**判定，**不會抓跨張不一致**（單張看很好，16 張擺一起歪七扭八）。所以 Raw QA 過了之後，必須加一個跨張比對步驟才能進 ★ 用戶確認。

**要一致的維度：**
1. **姿勢（pose）** — 都坐姿？都全身？不要混
2. **頭身比例（head-to-body ratio）** — chibi 通常頭佔 40-50%，其他張比例要差不多
3. **構圖（composition）** — 都正面？都半身？畫面填滿程度要接近
4. **身體形狀（body shape）** — 圓胖？拉長？攤平？不要混
5. **四肢露出程度（limbs）** — 都露爪？都藏腿？不要混

**怎麼比：** 把 16 張同時列出來（Claude 看），找出 outlier。例：v8 發現 #03 頭特大、#04 全身+4腳、#08 攤成橢圓，跟其他 13 張不一致。

**怎麼修：**
1. 先調 style_prefix 加強姿勢限制（如 `seated chibi pose, round chubby seated body, head and upper body visible, paws tucked near body, no legs shown`）
2. 再改 outlier 的 per-sticker prompt（去掉「curled up」「full body」等會讓模型亂發揮的詞）
3. `python main.py fix` 重生 outlier
4. 重跑 Raw QA
5. 再做一次跨張比對

**為什麼這步只能用 Claude 不用 Ollama：** Ollama 逐張判定，沒辦法「同時看 16 張比較」。跨張風格一致性是人類視覺任務，Claude/人類直接比對最有效。

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
├── bg_uniform.py      — 背景是否均勻（去背前置條件）
├── bg_color.py        — 背景是否是 prompts.json 指定的顏色（雙層：像素取樣 + Ollama）
├── separation.py      — 角色是否與背景分離清楚（去背前置條件）
├── bg_clean.py        — 去背後背景是否乾淨（nobg/format QA 用）
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
- **fix 只重生 raw** — 不產 nobg，不做 format。後續步驟（nobg、format）各自獨立跑。
