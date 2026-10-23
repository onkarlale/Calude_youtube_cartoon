import textwrap
from PIL import Image, ImageDraw, ImageFont

FONTS = ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
         "/Library/Fonts/Arial Bold.ttf", "C:/Windows/Fonts/arialbd.ttf"]

def _font(size):
    for p in FONTS:
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            continue
    return ImageFont.load_default()

def make(first_image, title, out):
    img = Image.open(first_image).convert("RGB")
    tw, th = 1280, 720
    scale = max(tw / img.width, th / img.height)
    img = img.resize((int(img.width * scale), int(img.height * scale)))
    l, t = (img.width - tw) // 2, (img.height - th) // 2
    img = img.crop((l, t, l + tw, t + th))
    d = ImageDraw.Draw(img)
    font = _font(84)
    lines = textwrap.wrap(title, width=18)[:3]
    y = th - 60 - len(lines) * 100
    for line in lines:
        d.text((50, y), line, font=font, fill="white", stroke_width=8, stroke_fill="black")
        y += 100
    img.save(out, "JPEG", quality=90)
    return out
