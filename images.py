import base64, io, time, requests
from PIL import Image, ImageFilter, ImageEnhance
import config

MODEL = "@cf/black-forest-labs/flux-1-schnell"
URL = "https://api.cloudflare.com/client/v4/accounts/{acc}/ai/run/" + MODEL
_SEED_OK = True   # flipped off automatically if the API rejects the seed field


def _compose(img):
    """FLUX returns a square picture. Keep the WHOLE picture sharp in the middle and fill the
    sides (or top/bottom for Shorts) with a blurred, darkened copy, so nothing gets cropped."""
    W, H = config.WIDTH, config.HEIGHT
    scale = max(W / img.width, H / img.height)
    bg = img.resize((int(img.width * scale) + 1, int(img.height * scale) + 1), Image.LANCZOS)
    left, top = (bg.width - W) // 2, (bg.height - H) // 2
    bg = bg.crop((left, top, left + W, top + H)).filter(ImageFilter.GaussianBlur(28))
    bg = ImageEnhance.Brightness(bg).enhance(0.55)
    fit = min(W / img.width, H / img.height)
    fg = img.resize((int(img.width * fit), int(img.height * fit)), Image.LANCZOS)
    lift = int(H * 0.10) if H > W else 0   # Shorts: lift the picture so captions sit below it
    bg.paste(fg, ((W - fg.width) // 2, (H - fg.height) // 2 - lift))
    return bg


def make_image(prompt, path, seed=None):
    global _SEED_OK
    full = f"{prompt}. {config.ART_STYLE}. wide shot, full body, centered, clean simple background, cinematic lighting. no text, no letters, no watermark, no logo"[:2000]
    url = URL.format(acc=config.CF_ACCOUNT_ID)
    headers = {"Authorization": f"Bearer {config.CF_API_TOKEN}"}
    last = "unknown"
    for attempt in range(5):
        try:
            payload = {"prompt": full, "steps": 8}
            if seed is not None and _SEED_OK:
                payload["seed"] = int(seed)   # same seed in every scene = more similar look
            r = requests.post(url, headers=headers, json=payload, timeout=180)
            if r.status_code in (400, 422) and "seed" in payload:
                _SEED_OK = False
                payload.pop("seed")
                r = requests.post(url, headers=headers, json=payload, timeout=180)
            if r.status_code in (401, 403):
                raise SystemExit(f"Cloudflare rejected the token/account ({r.status_code}): {r.text[:300]}\n"
                                 "Check CF_ACCOUNT_ID / CF_API_TOKEN secrets (token needs Workers AI permission).")
            if r.status_code == 200:
                b64 = r.json().get("result", {}).get("image")
                if b64:
                    img = Image.open(io.BytesIO(base64.b64decode(b64))).convert("RGB")
                    if min(img.size) >= 512:
                        _compose(img).save(path, "JPEG", quality=94)
                        return
                    last = f"image too small {img.size}"
                else:
                    last = f"no image in response: {r.text[:200]}"
            else:
                last = f"HTTP {r.status_code}: {r.text[:200]}"
        except SystemExit:
            raise
        except Exception as e:
            last = str(e)
        print(f"   image attempt {attempt+1} failed: {last}")
        time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"Image generation failed after retries ({last}). Nothing was uploaded.")
