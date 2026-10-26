#!/usr/bin/env python3
"""Generate audience / stage cutaway images (1920x1080) into out/. Commit the good ones to assets/cutaways/."""
import argparse
import random
from pathlib import Path

import cf_image

BASE = "photorealistic photo, comedy club, warm dim lighting, shallow depth of field, cinematic, no text"
SCENES = [
    "audience seen from behind, rows of people laughing, silhouettes, backs of heads, stage spotlight ahead",
    "wide shot of a small comedy club stage with a stool and a microphone stand, empty, spotlight, brick wall",
    "crowd seen from the side at a distance, people laughing and clapping, blurred faces, bokeh lights",
    "close-up of hands clapping in a dark comedy club, shallow depth of field, blurred background",
    "table with drinks and chai glasses in a comedy club, blurred laughing audience in the background",
    "back of a man's head and shoulders laughing, audience around him, warm stage light in the distance",
    "wide shot from the back of the room towards a brightly lit stage, audience silhouettes in the foreground",
    "group of friends laughing seen from behind at a comedy show, blurred, bokeh",
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=12)
    ap.add_argument("--out", default="out")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(exist_ok=True)
    for i in range(a.count):
        scene = SCENES[i % len(SCENES)]
        seed = random.randint(1, 10**6)
        print(f"cutaway {i + 1}/{a.count}: {scene[:50]}", flush=True)
        im = cf_image.generate(f"{scene}, {BASE}", seed=seed)
        if im is None:
            continue
        cf_image.crop_169(im, 1920, 1080, y_frac=0.5).save(out / f"cut_{i:02d}.png")
    print("Done. Keep only images WITHOUT visible distorted faces; commit them to assets/cutaways/")


if __name__ == "__main__":
    main()
