import time, urllib.parse, requests
from PIL import Image
import config

MIN_BYTES = 30_000   # tiny files are error images / blanks

def make_image(prompt, path, seed):
    full = f"{prompt}. {config.ART_STYLE}. no text, no letters, no watermark, no logo"[:700]
    url = ("https://image.pollinations.ai/prompt/" + urllib.parse.quote(full) +
           f"?width={config.WIDTH}&height={config.HEIGHT}&seed={seed}&nologo=true&model=flux&enhance=false")
    last = "unknown"
    for attempt in range(6):
        try:
            r = requests.get(url, timeout=240)
            ctype = r.headers.get("content-type", "")
            if r.status_code == 200 and ctype.startswith("image") and len(r.content) >= MIN_BYTES:
                with open(path, "wb") as f:
                    f.write(r.content)
                img = Image.open(path).convert("RGB")
                if min(img.size) >= 512:
                    img.save(path, "JPEG", quality=94)
                    return
                last = f"image too small {img.size}"
            else:
                last = f"HTTP {r.status_code}, {ctype}, {len(r.content)} bytes"
        except Exception as e:
            last = str(e)
        print(f"   image attempt {attempt+1} failed: {last}")
        time.sleep(8 * (attempt + 1))
    raise RuntimeError(f"Image generation failed after retries ({last}). Nothing was uploaded.")
