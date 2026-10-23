import time, urllib.parse, requests
from PIL import Image, ImageDraw
import config

def _placeholder(path, text):
    img = Image.new("RGB", (config.WIDTH, config.HEIGHT), (255, 214, 120))
    d = ImageDraw.Draw(img)
    d.ellipse([config.WIDTH*0.3, config.HEIGHT*0.3, config.WIDTH*0.7, config.HEIGHT*0.7], fill=(255, 170, 90))
    img.save(path, "JPEG")

def make_image(prompt, path, seed):
    full = f"{prompt}. {config.ART_STYLE}. no text, no watermark"[:700]
    url = ("https://image.pollinations.ai/prompt/" + urllib.parse.quote(full) +
           f"?width={config.WIDTH}&height={config.HEIGHT}&seed={seed}&nologo=true")
    for attempt in range(4):
        try:
            r = requests.get(url, timeout=180)
            if r.status_code == 200 and r.headers.get("content-type", "").startswith("image"):
                with open(path, "wb") as f:
                    f.write(r.content)
                Image.open(path).convert("RGB").save(path, "JPEG", quality=92)
                return True
            print(f"Image HTTP {r.status_code}, retrying")
        except Exception as e:
            print(f"Image error: {e}")
        time.sleep(6 * (attempt + 1))
    print("Using placeholder image")
    _placeholder(path, prompt)
    return False
