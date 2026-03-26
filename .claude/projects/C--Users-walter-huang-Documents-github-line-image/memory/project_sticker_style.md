---
name: sticker_style_decision
description: User chose bold flat C style (indie cartoon, chunky outlines, round shape, flat colors, googly eyes) for the cat sticker pack, using Z-Image-Turbo model
type: project
---

User selected style C (style_bold_flat_c.png) as the preferred art style for future sticker generations.

**Style prompt:** `indie cartoon style, chunky bold black outlines, round simple shapes, flat color fills, big googly eyes, exaggerated mouth expressions, quirky character design, web animation aesthetic, bright cheerful palette`

**Model:** Z-Image-Turbo FP8 (z-image-turbo_fp8_scaled_e4m3fn_KJ.safetensors) with UNETLoader + CLIPLoader (qwen_3_4b, type: qwen_image, device: cpu) + VAELoader (ae.safetensors)

**Why:** User wanted a style similar to Simpsons (bold flat cartoon) but without copyright issues. Style C has the most 辨識度 (distinctiveness) with its round chunky shape and minimal design.

**How to apply:** This style should be used as the base style_prefix for future sticker generations. The workflow needs to use UNETLoader instead of CheckpointLoaderSimple since Z-Image-Turbo is a DiT model, not a traditional SD checkpoint.
