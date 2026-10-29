OPTIONAL: your own base videos (instead of a still picture).

Put .mp4 / .mov / .webm clips in this folder (GitHub: Add file -> Upload files). Each episode the bot rotates through
all videos here AND all pictures in assets/faces/ and assets/comedian.png, so every day looks different.

Best clips (the lip-sync only changes the mouth, the rest of the footage stays as you filmed it):
  * about 6 to 10 seconds, one person facing the camera, face clearly visible in every frame
  * mouth CLOSED or relaxed (not talking), natural small head/shoulder movement, steady camera, no cuts
  * landscape 16:9, 720p or better, good light, plain or stage background
  * you must have the right to use the footage (your own recording or a free-licence clip)
The bot shrinks the clip automatically. If a clip cannot be shrunk under about 1.5 MB, make it shorter.
To use ONLY the single picture again, set  "base_mode": "single"  in config.json (section "visuals").
