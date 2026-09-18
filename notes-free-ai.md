# Free / free-tier AI image options for kids coloring-book LINE ART

Researched and live-tested from this Linux box on **2026-09-17 (IST)**.  
Goal: black outlines on white, ages 3–7, usable from Python, prefer no paid subscription.

Project today: Pollinations (no key) + optional `HF_TOKEN` → FLUX.1-schnell.

---

## Executive recommendation (for this project)

| Rank | Path | Auth | Line-art quality (expected) | Action |
|------|------|------|-----------------------------|--------|
| **1** | **Cloudflare Workers AI** `@cf/black-forest-labs/flux-1-schnell` | Free CF account → Account ID + API token | Best free FLUX path; solid for outlines after postprocess | Prefer if user can create a free CF token |
| **2** | **Pollinations `gen.pollinations.ai` + `model=flux`** | Free key at enter.pollinations.ai (`sk_`) | Much better than anonymous `sana`; still needs postprocess | Prefer if user already uses Pollinations |
| **3** | **Hugging Face Inference Providers** FLUX.1-schnell | Free `HF_TOKEN` + ~$0.10/mo credits | Good when credits last; tiny monthly quota | Keep as optional fallback (update API URL) |
| **4** | Legacy Pollinations `image.pollinations.ai` (no key) | None | **Poor** — only `sana` (DreamShaper LCM), soft grayscale, not real line art | Keep as last-resort only |
| — | Google Gemini / Nano Banana image API | Paid (no image free tier) | N/A for free | Skip |
| — | fal.ai / DeepInfra / most Replicate | Paid or tiny trial | N/A | Skip for free path |
| — | Local FLUX on this box | None | **Not practical** — no NVIDIA GPU; 15 GiB RAM | Skip for batch books |

**Bottom line:** A no-key Pollinations “model upgrade” does **not** work — `?model=flux` on the legacy host silently serves `sana`. For usable line art you need **one free signup key**: either Cloudflare (best daily quota) or Pollinations `sk_` (easiest drop-in), with HF as a small bonus. Keep `postprocess_line_art()` for all providers.

**Keys the user may need to provide (all free signup, no subscription required):**
1. Best: `CLOUDFLARE_ACCOUNT_ID` + `CLOUDFLARE_API_TOKEN`
2. Or: `POLLINATIONS_API_KEY` (`sk_` from https://enter.pollinations.ai/keys)
3. Optional small quota: `HF_TOKEN` (already wired; update endpoint)

---

## What we tested live (no secrets)

### 1) Legacy Pollinations — works without key, but only `sana`

```bash
# Models list (anonymous)
curl -sS 'https://image.pollinations.ai/models'
# → ["sana"]
```

```bash
# Coloring-book prompt — WORKS (HTTP 200), model used = sana
curl -o elephant.jpg \
  'https://image.pollinations.ai/prompt/coloring%20page%20simple%20cute%20cartoon%20elephant%2C%20black%20and%20white%20line%20drawing%2C%20outline%20only%2C%20thick%20black%20outlines%2C%20pure%20white%20background%2C%20NO%20shading?width=768&height=1024&nologo=true&enhance=false&seed=101'
# Response headers: x-auth-status: unauthenticated ; x-model-used: sana
```

```bash
# model=flux does NOT upgrade — silent fallback to sana
curl -D - -o flux_attempt.jpg \
  'https://image.pollinations.ai/prompt/...?model=flux&width=768&height=1024&seed=101' -o /dev/null
# Still: x-model-used: sana  (same bytes as default for same seed)
```

**Rate limits / quirks (observed):**
- Occasional `429` upstream (“Per-user limit of 300 RPM exceeded for lykon/dreamshaper-8-lcm”) surfaced as HTTP 500 JSON.
- `nologo=true` still left a pollinations watermark on samples (anonymous).
- Requested 768×1024; returned ~665×886 JPEG.
- Quality: soft grayscale / 3D shading / black fills — **not** printable kids line art without heavy CV postprocess (and even then shapes can collapse).

**Samples saved:** `output/_ai_path_tests/pollinations_sana_{elephant,rocket,butterfly}.jpg`  
(+ `*_postprocessed.png` via project pipeline).  
`pollinations_flux_param_elephant.jpg` = identical sana fallback (proof that `model=flux` does nothing on legacy).

### 2) New Pollinations gateway — requires key (even for flux / sana / zimage)

```bash
curl -sS 'https://gen.pollinations.ai/image/a%20cat?model=flux&width=512&height=512'
# → HTTP 401
# {"success":false,"error":{"message":"A valid API key is required. Get one at https://enter.pollinations.ai/keys","code":"UNAUTHORIZED",...}}
```

Same 401 for `model=zimage` and `model=sana` without a key.

**Live catalog (2026-09-17)** — official image models relevant here (`GET /image/models`):

| Alias | Canonical | paid_only | Catalog pollen / image | RPM |
|-------|-----------|-----------|------------------------|-----|
| `flux` | `black-forest-labs/flux.1-schnell` | no | **0.002** | 60 |
| `zimage` | `tongyi-mai/z-image-turbo` | no | 0.004 | 60 |
| `sana` | `lykon/dreamshaper-8-lcm` | no | 0.0001 | 300 |

Docs: create free `sk_` at enter.pollinations.ai; free Quest Pollen refills (tier-dependent). Older FAQ text said “flux = always free / ∞”; **live pricing shows 0.002 pollen/image** — budget ~50 pages carefully or use Cloudflare.

**Working curl once user has a free key:**

```bash
curl -o flux_cat.jpg \
  -H "Authorization: Bearer $POLLINATIONS_API_KEY" \
  'https://gen.pollinations.ai/image/coloring%20page%20cute%20cat%2C%20black%20outlines%20only%2C%20white%20background%2C%20no%20shading?model=flux&width=1024&height=1024&seed=42&nologo=true&enhance=false'
# Alternate: ?key=$POLLINATIONS_API_KEY
```

### 3) Hugging Face — no anonymous inference

```bash
# api-inference.huggingface.co — host did not resolve from this box
# router.huggingface.co — HTTP 401 without token
curl -sS -X POST \
  'https://router.huggingface.co/hf-inference/models/black-forest-labs/FLUX.1-schnell' \
  -H 'Content-Type: application/json' \
  -d '{"inputs":"simple cat coloring page line art"}'
# → 401
```

Free account gets ~**$0.10/month** Inference Providers credits. Former serverless FLUX endpoint has been deprecated for some users (forum reports of HTTP 410 mid-2026). Prefer `huggingface_hub.InferenceClient` / router, not `api-inference.huggingface.co`.

### 4) Local GPU on this box

- `nvidia-smi`: **not found** (no NVIDIA GPU).
- ~15 GiB RAM — too tight for FLUX.1-schnell; FastSD-CPU possible but too slow/poor for 50-page books.

---

## Other providers (research, not live-tested without keys)

### Cloudflare Workers AI — **strong free tier**

- **Auth:** free Cloudflare account → Account ID + Workers AI API token (no card required for free allocation).
- **Quota:** **10,000 Neurons/day** free (resets 00:00 UTC).
- **Model:** `@cf/black-forest-labs/flux-1-schnell`
- **Cost math (docs):** ~4.8 neurons / 512×512 tile + ~9.6 neurons / step. Example ~1024² @ 4 steps ≈ tens of neurons → **on the order of ~100–200 images/day**, enough for a 50-page book with retries.
- **Line art:** FLUX follows “outline / coloring page” prompts better than DreamShaper LCM; still run project postprocess.
- **Sample curl:**

```bash
curl -X POST \
  "https://api.cloudflare.com/client/v4/accounts/$CLOUDFLARE_ACCOUNT_ID/ai/run/@cf/black-forest-labs/flux-1-schnell" \
  -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"prompt":"kids coloring page, simple cute elephant, thick black outlines only, pure white fills, white background, no shading, no gray, no color","steps":4}'
# Response JSON includes base64 JPEG in .result.image
```

Python: `requests.post(...); Image.open(BytesIO(base64.b64decode(data["result"]["image"])))`.

### Google Gemini / Nano Banana (Imagen)

- Imagen API deprecated / shut down path (migrate to Nano Banana).
- Pricing: image models list free tier as **“Not available”** — API is paid from first image.
- AI Studio UI may allow free experiments; **not** a free Python batch path. **Skip for free.**

### fal.ai

- No reliable standing free API credits (playground/sandbox ≠ API). Builder grants are invite/region limited. **Skip for free.**

### Replicate

- Occasional one-time “Try for Free” on some models; not a stable free production quota. **Skip as primary.**

### Together AI / DeepInfra

- Together: occasional promo credits; often card / paid for sustained image use.
- DeepInfra: prepaid/paid; FLUX Schnell cheap but not free. **Skip for free.**

### Recraft / Ideogram / Seedream via Pollinations

- Mostly `paid_only: true` on Pollinations catalog. Not free.

---

## Integration steps for `kdp-coloring-book-generator`

### A) Recommended: Cloudflare FLUX (new provider)

1. User creates free CF account → Workers AI token with Run permission → copy Account ID.
2. Add to `.env`:
   ```
   CLOUDFLARE_ACCOUNT_ID=...
   CLOUDFLARE_API_TOKEN=...
   ```
3. In `image_gen.py`, add `generate_cloudflare(...)` POSTing to the URL above; decode base64 JPEG.
4. Set `image.provider: cloudflare` in `config.yaml` (or auto-pick when CF env present).
5. Keep `postprocess_line_art()` on all outputs.
6. Prompt tip: emphasize “flat 2D coloring book line art, open white interiors, thick continuous black outlines, no grayscale shading”.

### B) Drop-in upgrade: Pollinations keyed FLUX

1. User signs up at https://enter.pollinations.ai (GitHub) → Create **Secret** key `sk_`.
2. Add to `.env`:
   ```
   POLLINATIONS_API_KEY=sk_...
   POLLINATIONS_URL=https://gen.pollinations.ai/image
   POLLINATIONS_MODEL=flux
   ```
3. Change `generate_pollinations` to:
   - Base: `https://gen.pollinations.ai/image/{encoded_prompt}`
   - Query: `model=flux&width=&height=&seed=&nologo=true&enhance=false`
   - Header: `Authorization: Bearer {POLLINATIONS_API_KEY}`
4. Fallback chain: keyed flux → legacy anonymous sana → placeholder.
5. Watch pollen balance (`GET /account/balance` with key); 50 pages × 0.002 ≈ **0.1 pollen** if catalog pricing applies — usually covered by Quest refill, but verify.

### C) HF path (already optional) — fix endpoint

Current code posts to deprecated-style:

`https://api-inference.huggingface.co/models/black-forest-labs/FLUX.1-schnell`

Prefer:

```python
from huggingface_hub import InferenceClient
client = InferenceClient(token=hf_token, provider="auto")
image = client.text_to_image(prompt, model="black-forest-labs/FLUX.1-schnell")
```

Or HTTP via `https://router.huggingface.co/...` with Bearer token. Expect only tens of images/month on free credits.

### D) Do **not** rely on

- `?model=flux` on `image.pollinations.ai` (silent sana).
- Gemini image API without billing.
- Local FLUX on this CPU box for full books.

---

## Line-art suitability notes

| Source | Raw output | After `postprocess_line_art` |
|--------|------------|------------------------------|
| Pollinations `sana` (tested) | Soft gray / filled blacks / oval vignettes | Partial outlines; can lose detail (see elephant postprocess) |
| FLUX.1-schnell (CF / Pollinations / HF) | Better structure; still often gray shading | Best free combo for kids pages |
| Dedicated “lineart ControlNet” local | Best fidelity | Needs GPU + ControlNet stack — out of scope for free no-GPU box |

Always keep postprocess; consider optional second pass (e.g. morphological open interiors) if FLUX still leaves gray.

---

## Sample prompts that work better for line art

```
kids coloring book page, ages 3-7, single cute [SUBJECT] centered,
flat 2D cartoon, thick continuous black outlines only,
pure white interior regions to color, pure white background,
NO shading, NO gray, NO gradients, NO hatch, NO solid black fills,
NO watercolor, NO 3d, NO text, NO watermark
```

Negative-style phrases in the positive prompt help more than `enhance=true` (leave enhance off — it drifts toward shaded art).

---

## Test artifacts

Directory: `output/_ai_path_tests/`

| File | Notes |
|------|-------|
| `pollinations_sana_elephant.jpg` | Anonymous sana; shaded, not line art |
| `pollinations_sana_rocket.jpg` | Anonymous sana; incoherent / filled |
| `pollinations_sana_butterfly.jpg` | Anonymous sana; closest to outlines but gray |
| `pollinations_flux_param_elephant.jpg` | Same as elephant — proves `model=flux` fallback |
| `*_postprocessed.png` | Project CV pipeline on the above |

Could **not** generate FLUX comparison images without a key (gen.pollinations.ai → 401). Once a free Pollinations or Cloudflare key is available, regenerate the same three subjects with `model=flux` / Workers AI for a side-by-side.

---

## Checklist for parent agent / user

- [ ] Prefer ask user for **Cloudflare** free Workers AI credentials (best free daily quota + FLUX).
- [ ] Or ask for free **Pollinations `sk_`** and switch base URL to `gen.pollinations.ai` + `model=flux`.
- [ ] Keep optional **HF_TOKEN** but treat as tiny monthly budget; migrate off `api-inference.huggingface.co`.
- [ ] Do not expect anonymous Pollinations to improve via model query params.
- [ ] Always run outline postprocess; evaluate FLUX raw before shipping a full 50-page book.
