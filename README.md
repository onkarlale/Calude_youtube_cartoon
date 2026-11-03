# Automated Hindi AI Stand-up Comedy Channel (100% free tools, 100% GitHub Actions)

Every day at 08:00 IST, GitHub Actions: picks a topic -> Gemini writes a 2-3 minute Hinglish set (draft, punch-up, then a tough-audience rewrite) ->
Kaggle's free GPU makes the lip-synced talking head (MuseTalk) -> FFmpeg adds audience cutaways, laugh track,
captions, intro/outro -> uploads to YouTube. If the GPU step fails twice, a simpler voice+image video is published.

**You do nothing by hand.** On the very first run the workflow creates Raj's face and the audience images with your
Cloudflare key and commits them to the repo, so Raj looks the same in every episode.

## Setup
1. Upload everything in this folder (including `.github`) to your GitHub repo (replace old files; delete the old
   `.github/workflows/assets.yml` if it is still there).
2. Settings -> Actions -> General -> Workflow permissions -> **Read and write**.
3. Secrets needed (Settings -> Secrets and variables -> Actions):
   `GEMINI_API_KEY` (a free key from Google AI Studio; `GROQ_API_KEY_CLAUDE` is now only an optional backup), `CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_API_TOKEN`, `KAGGLE_USERNAME`,
   `KAGGLE_KEY` (the `key` value from kaggle.json; if Kaggle gave you a new-style token starting with `KGAT_`, save it as
   `KAGGLE_API_TOKEN` instead), `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET`, `YOUTUBE_REFRESH_TOKEN`.
   `YOUR_CLIENT_ID` is not used. The YouTube client ID/secret must be the same ones used to create the refresh token.
4. Google Cloud -> OAuth consent screen -> **Publishing status = In production** (else the refresh token dies in 7 days).
5. Kaggle: your account must be phone-verified (GPU + internet in notebooks).

## Run
Actions -> **daily-comedy-video** -> Run workflow.
- First run: tick **smoke_test** (short built-in script, uploads private). Expect 25 to 40 minutes because MuseTalk installs on Kaggle.
- Then run it normally. After that the 08:00 IST schedule makes a new episode every day.
- `skip_lipsync` = build the simple fallback video without Kaggle. `no_upload` = build only. `new_face` = make Raj a new face.
- Every run keeps `final.mp4` as an artifact for 7 days (run page -> Artifacts).

Keep `"privacy": "private"` in `config.json` for the first week, then change to `"public"`. YouTube may force
uploads from unaudited API projects to stay private; then publish from Studio.

## What changed in this update
1. **Better jokes.** The writer now works like a writers' room: it pitches 14 candidate bits (each with the "obvious" joke it must avoid),
   a tough-audience pass scores them, and only the best bits (max 2 per joke mechanism) become the set. Then the usual punch-up
   and TWO tough-audience rewrites. A different comic voice each night (`deadpan`, `escalating panic`, ...), stock clichés
   (Sharma ji, shaadi kab, EMI, good-morning groups ...) are limited, formula openers ("... ne meri zindagi barbaad kar di") are rejected,
   news headlines are used far less often (`topic.news_ratio`, default 0.2) and `data/evergreen_topics.txt` has 45 fresher topics.
   Switches in `config.json` -> `script`: `joke_bank`, `bank_size`, `bank_pick`, `crowd_rounds`.
2. **Only the mouth moves.** `visuals.only_mouth_moves: true` (default): the picture is a perfectly still frame (no sway, zoom, camera cuts,
   audience cut-aways, flicker or blinking LIVE badge); the Kaggle step lip-syncs only the mouth, and the final encode uses a still-picture
   setting so the frame does not "breathe". Set it to `false` to get the old busy look back.
3. **A different comedian every episode.** Every `assets/bodies/comedian_*.png` is used once, in random order, then a new random order
   (never the same one twice in a row; any number of pictures works: 12, 20, 50). Add more `comedian_XX.png` files and they join the rotation
   automatically. If the folder has no `comedian_*` files, every picture in it is used. A woman on stage gets a woman's voice via
   `voice.by_image` in `config.json` (e.g. `"comedian_01.png": "hi-IN-SwaraNeural"`; add one line per picture that needs a different voice).

## Files
```
.github/workflows/daily.yml   the only workflow
scripts/bootstrap_assets.py   auto-creates face + cutaways on first run
assets/character.md           comedian "bible" (Raj; edit if you like, keep the rules)
config.json                   channel name, voice, privacy, Kaggle names
kernel/render.py              GPU job that runs on Kaggle (voice + lip-sync)
used_topics.json              topics already used (the bot commits this)
```

## If the Kaggle step fails
The run log prints every Kaggle status line. Open kaggle.com -> Code -> Your Work -> comedy-render for the full log.
Send me the log lines and I will patch `kernel/render.py`.

## Visual variety (new)
- **Rotating faces:** on the first run the bot also creates extra faces in `assets/faces/` (different outfits and stage
  backgrounds, `visuals.face_pool` in `config.json`). Each episode uses the next one, so the picture changes every day.
  The host is generated by AI each time, so his face can differ between pictures. For one fixed host set `"base_mode": "single"`.
- **Your own videos:** drop clips into `assets/base_videos/` (see the README.txt there). They join the daily rotation.
- **Camera cuts:** every episode is edited like a multi-camera special: wide, medium and close-up shots, with close-ups on
  punchlines. Turn off with `"camera_cuts": false`.

## Hashtags and picking pictures
- **Hashtags:** every upload gets hashtags at the end of its description (YouTube shows the first 3 above the title).
  Edit the channel list under `"hashtags"` in `config.json`; topical ones from each episode's tags are added automatically (max 12).
- **Many pictures:** put as many pictures as you like in `assets/` or `assets/faces/` (png/jpg, 16:9 landscape, one face looking at
  the camera, mouth closed). Each episode picks one at random (never the same as yesterday). Pictures without a clear face are skipped.
  Set `"base_pick": "sequential"` in `config.json` to go in order instead of random.

## YouTube Shorts mode (default)
`config.json` has `"format": "shorts"`: every episode is a vertical 1080x1920 video of about 2 to 2.9 minutes, capped at
175 seconds (YouTube treats vertical videos up to 3 minutes as Shorts). The voice is sped up a little automatically if a set runs long.
- **Layout `"stage"` (default):** the comedian sits in a stage panel (face smaller, stage and shoulders visible, a gentle camera
  drift and cuts between wide, medium and close shots). Below him is a live audience panel with moving crowd shots; AI audience
  faces laughing appear during the laughs. The background is a darkened, blurred copy of the stage. Set
  `"layout": "closeup"` under `"shorts"` for the older look where his face fills the whole screen.
- **Built for retention:** a scroll-stopping first line, a laugh every 10 to 12 seconds, big captions, an on-screen hook banner in
  the first 3 seconds, no sign-off, and a last line that calls back to the first so it loops.
- **Audience setting:** `"audience": "teen"` (default) writes for ages 13+ and the whole family: no swearing, no sexual or
  alcohol jokes. `"adult"` allows 18+ humour (innuendo, mild swearing). Hard limits always apply: no hate or slurs, no politics,
  no religion/caste jokes, no real named people. The writer rejects scripts that contain swearing or adult words in teen mode.
- **Hashtags:** up to 14 in the description (`"hashtags"` in `config.json` plus topical ones from each episode), `#Shorts #HindiComedy`
  added to the title (`"title_hashtags"`), and the same words added as search tags. YouTube ignores ALL hashtags if there are more than 15.
- Shorts have no custom thumbnail. Audience pictures: delete any you dislike from `assets/cutaways/`; pictures named `react_XX.png` are the laughing faces.

## The AI writer (Gemini)
- Secret: **`GEMINI_API_KEY`** (Settings -> Secrets and variables -> Actions -> Secrets). Optional repository **variable** `GEMINI_MODELS`
  (same page, Variables tab), a comma-separated list tried in order. Default:
  `gemini-3.8-flash,gemini-3.6-flash,gemini-3.5-flash,gemini-3.5-flash-lite,gemini-2.5-flash`.
  A model that is missing, not allowed for your key, rate-limited or blocked is skipped and the next one is used.
- Three passes: draft, punch-up, then a "tough audience" rewrite that replaces lines that would not get a laugh. A script is
  rejected and rewritten if it sounds like a story, does not talk to the audience, is too long for a Short, or has adult words
  in 13+ mode. `config.json` -> `"script"` has `providers` (default `["gemini","groq"]`), `thinking` and `crowd_test`.
- Movement: the comedian panel has a handheld camera sway and cuts, the laughing audience faces bounce, the crowd sways,
  and a LIVE badge blinks. Real laughter/applause recordings in `assets/sfx/` (names starting `laugh` / `applause`) make it sound much more real.

## Full-screen layout (default) and 18+ jokes
- `"layout": "full"` (in `config.json` under `"shorts"`): the picture fills the whole 1080x1920 screen and the live audience sits at the
  bottom, fading softly into the picture (no bars, no hard lines). Captions sit between them.
  - `"framing": "wide"` (default): Raj in a soft-edged panel that melts into a blurred extension of the same stage (face smaller, shoulders and stage visible).
  - `"framing": "tight"`: Raj's picture fills the whole screen (face large).
  - `"layout": "stage"` = two separate panels with lines, `"closeup"` = vertical face close-up.
- `"audience": "adult"` (default now) = 18+ humour. `"teen"` = family friendly 13+. The hard limits (hate, slurs, politics, religion/caste,
  explicit sex, real people) apply in every mode. Adult content can be age-restricted by YouTube and may get less reach or fewer ads.
- Rendering a full 2.5 minute Short takes a few minutes on the GitHub runner (more panels = more work).
