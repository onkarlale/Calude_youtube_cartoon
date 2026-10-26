# Automated Hindi AI Stand-up Comedy Channel (100% free tools)

Every day at 08:00 IST, GitHub Actions: picks a topic -> Groq writes a 2-3 minute Hinglish set (draft + punch-up) ->
Kaggle's free GPU makes the voice and a lip-synced talking head (MuseTalk) -> FFmpeg adds audience cutaways,
laugh track, captions, intro/outro -> uploads to YouTube. If the GPU step fails twice, a simpler
voice+image video is published instead (it never silently goes dead).

```
.github/workflows/daily.yml   daily cron + manual run (with smoke test)
.github/workflows/assets.yml  one-time helper: makes face / cutaway / idle-loop assets for you
assets/character.md           comedian "bible" (edit it!)
assets/comedian.png           YOU add: the chosen face (1280x720)
assets/cutaways/              YOU add: audience images
assets/sfx/                   optional: real laugh*.mp3 / applause*.mp3 (CC0). Without them a synthetic crowd is used
config.json                   channel name, voice, privacy, Kaggle names
scripts/                      topic, write_script, kaggle_run, edit, upload, run_daily, tts_lib
kernel/render.py              the GPU job that runs on Kaggle
tools/                        asset generators
used_topics.json              topics already used (the bot commits this)
```

## Setup (do in this order)

### 0. Secrets (GitHub repo -> Settings -> Secrets and variables -> Actions)
Required names: `GROQ_API_KEY_CLAUDE`, `KAGGLE_USERNAME`, **`KAGGLE_KEY`**, `CLOUDFLARE_ACCOUNT_ID`,
`CLOUDFLARE_API_TOKEN`, `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET`, `YOUTUBE_REFRESH_TOKEN`.
(`YOUR_CLIENT_ID` is not used; delete it.)
Also: Google Cloud -> OAuth consent screen -> set **Publishing status = In production**, otherwise the YouTube
refresh token expires after 7 days.

### 1. Upload this repo
Unzip, then upload everything (including the `.github` folder) to your GitHub repo.
Settings -> Actions -> General -> Workflow permissions -> **Read and write**.

### 2. Edit `config.json` and `assets/character.md`
Change `channel_name`, and the character if you like. Keep the rules section.

### 3. Make the face (one time)
Actions tab -> **make-assets** -> Run workflow -> `what = face`, count 20.
Open the finished run -> Artifacts -> download **face**. Pick ONE image: frontal, mouth closed, no strange hands.
Upload it to the repo as `assets/comedian.png`. (If the face is cropped badly, run again; each run is random.)

### 4. Make the cutaways (one time)
make-assets -> `what = cutaways`, count 12 -> download **cutaways** -> upload the good ones (no distorted faces)
into `assets/cutaways/`. Aim for 8 or more.

### 5. Make the idle loop and the Kaggle dataset
make-assets -> `what = idle` -> download **idle** (contains `base_idle.mp4`).
On kaggle.com: Datasets -> New Dataset -> upload `base_idle.mp4` -> title **comedy-assets** -> **Private** -> Create.
The dataset slug must match `kaggle.assets_dataset` in `config.json`.
Make sure your Kaggle account is phone-verified (needed for GPU and internet in notebooks).

### 6. Smoke test (important)
Actions -> daily-comedy-video -> Run workflow -> tick **smoke_test**. This uses a short built-in script,
runs the whole chain including Kaggle, and uploads **private**.
The first Kaggle run installs MuseTalk and downloads its weights (about 15 to 25 minutes).
Download the video from the run's Artifacts or open it in YouTube Studio and check lip sync on your phone.

To test without Kaggle: tick `skip_lipsync` as well.

### 7. Go live
Keep `"privacy": "private"` in `config.json` for the first week and review each video in YouTube Studio.
Change it to `"public"` (or `"unlisted"`) when you are happy. Note: YouTube may force uploads from API projects
that have not passed Google's audit to stay private. If so, publish manually from Studio, or apply for the audit.

## If the Kaggle step fails
The run logs print every Kaggle status line. Open the kernel on kaggle.com (Code -> Your Work -> comedy-render)
to see the full log. Typical causes:
- dataset name mismatch (`comedy-assets`), phone not verified, or weekly GPU quota used up;
- a MuseTalk install or weights download problem. After one successful run you can speed up and harden it:
  download `/tmp/mt/MuseTalk/models` as a private dataset, and put its name in `kaggle.weights_dataset`.
Send me the log lines and I will patch `kernel/render.py`.

## Costs
Everything used here has a free tier: GitHub Actions (public repo = unlimited; private = 2000 min/month, this uses
about 40 min/day), Kaggle GPU (about 30 h/week, this uses about 1 h per day), Groq, Cloudflare, Edge-TTS, YouTube API.
Free-tier limits can change; check them occasionally.

## Not included (yet)
Weekly analytics feedback loop (needs an extra YouTube Analytics OAuth scope on your refresh token).
