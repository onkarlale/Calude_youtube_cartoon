#!/usr/bin/env python3
"""Generate comedian face candidates (16:9, 1280x720) into out/. Pick ONE and commit it as assets/comedian.png."""
import argparse
import random
from pathlib import Path

import cf_image

PROMPT = (
    "photorealistic photo of a 32 year old Indian man, short black hair, light stubble, checked flannel shirt "
    "over a plain t-shirt, holding a microphone with a yellow foam cover close to his chest, standing on a small "
    "comedy club stage, warm spotlight, red brick wall behind him, face centered in the upper half of the frame, "
    "looking straight at the camera, mouth closed, relaxed neutral expression, both hands visible, sharp focus, "
    "shallow depth of field, 35mm cinematic photo"
)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=20)
    ap.add_argument("--out", default="out")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(exist_ok=True)
    for i in range(a.count):
        seed = random.randint(1, 10**6)
        print(f"face {i + 1}/{a.count} seed={seed}", flush=True)
        im = cf_image.generate(PROMPT, seed=seed)
        if im is None:
            continue
        cf_image.crop_169(im, 1280, 720, y_frac=0.12).save(out / f"face_{i:02d}_seed{seed}.png")
    print("Done. Pick the best (mouth closed, face frontal, no weird hands) and commit it as assets/comedian.png")


if __name__ == "__main__":
    main()
