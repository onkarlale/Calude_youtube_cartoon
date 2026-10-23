import glob, textwrap
from PIL import Image, ImageDraw, ImageFont

def _font_path():
    patterns = ["/usr/share/fonts/**/NotoSansDevanagari-Bold.ttf",
                "/usr/share/fonts/**/NotoSansDevanagari*Bold*.ttf",
                "/usr/share/fonts/**/NotoSansDevanagari-Regular.ttf",
                "/usr/share/fonts/**/NotoSansDevanagari*.ttf",
                "/usr/share/fonts/**/Lohit-Devanagari.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]
    for p in patterns:
        found = sorted(glob.glob(p, recursive=True))
        if found:
            return found[0]
    return None

def _font(size):
    path = _font_path()
    if path:
        try:
            return ImageFont.truetype(path, size, layout_engine=ImageFont.Layout.RAQM)
        except Exception:
            return ImageFont.truetype(path, size)
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
    lines = textwrap.wrap(title, width=16)[:3]
    y = th - 60 - len(lines) * 110
    for line in lines:
        d.text((50, y), line, font=font, fill="white", stroke_width=8, stroke_fill="black")
        y += 110
    img.save(out, "JPEG", quality=90)
    return out
