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
    "table with chai cups and snacks in a comedy club, blurred laughing audience in the background",
    "back of a man's head and shoulders laughing, audience around him, warm stage light in the distance",
    "wide shot from the back of the room towards a brightly lit stage, audience silhouettes in the foreground",
    "group of friends laughing seen from behind at a comedy show, blurred, bokeh",
]


# Reaction shots: real-looking (AI) people with visible faces, laughing at the show.
BASE_REACT = ("family friendly, no alcohol, no bottles, photorealistic candid photo, natural skin texture, sharp focus on the faces, shallow depth of field, "
              "dim comedy club, warm lighting, 35mm photograph, no text, no watermark")
REACTION_SCENES = [
    "close-up of an Indian man in his thirties laughing out loud at a comedy show, eyes crinkled, blurred audience behind him",
    "close-up of an Indian woman laughing and clapping at a comedy club, joyful expression, warm bokeh lights",
    "middle-aged Indian man in a checked shirt laughing hard and wiping a tear, sitting at a table in a comedy club",
    "two young Indian friends laughing together at a comedy show, shoulders up, candid moment",
    "group of four Indian friends at a table laughing hard, popcorn and chai in front of them, comedy club, medium shot",
    "Indian man clapping with his head thrown back laughing, comedy club audience, candid",
    "young Indian woman covering her mouth while laughing, comedy club, candid close-up",
    "middle-aged Indian woman laughing and nudging her husband at a comedy show, candid medium shot",
    "Indian man in a blue shirt pointing at the stage and laughing, audience around him, candid",
    "three Indian colleagues in office clothes laughing together at a comedy night, candid medium shot",
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
