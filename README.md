# Daily AI Cartoon Story Bot (free, runs on GitHub Actions)

Every day it: writes a new original story (Groq, free tier) -> draws cartoon scenes (Pollinations) ->
records narration (edge-tts) -> renders video with captions (FFmpeg) -> makes a thumbnail ->
uploads to YouTube (YouTube Data API). A `history.json` file stops stories repeating.

## Setup (about 30 minutes, one time)

### 1. Put this repo on GitHub
Create a new **private** repo and upload all these files (keep the `.github/workflows` folder).

### 2. Groq API key (free)
Get a key at https://console.groq.com/keys and add it as the repo secret `GROQ_API_KEY_CLAUDE`.

### 3. YouTube API access
1. https://console.cloud.google.com -> create a project -> enable **YouTube Data API v3**.
2. **OAuth consent screen**: External, add yourself as a test user, then click **Publish app** (set to "In production").
   If you leave it in "Testing", your refresh token expires after 7 days and uploads will stop.
3. **Credentials > Create credentials > OAuth client ID > Desktop app**. Download JSON, rename to `client_secret.json`.
4. On your own computer: `pip install google-auth-oauthlib` then `python get_refresh_token.py`. Log in with the channel's Google account.
5. Add the 3 printed values as secrets: `YOUR_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET`, `YOUTUBE_REFRESH_TOKEN`.

### 4. First run
Repo **Actions** tab -> "Daily cartoon video" -> **Run workflow**. Download the video from the run's Artifacts to check it.
After that it runs automatically every day at 09:00 IST (edit the cron line in `.github/workflows/daily.yml`).

## Settings (repo Settings > Secrets and variables > Actions > Variables, all optional)
| Variable | Default | Meaning |
|---|---|---|
| CHANNEL_THEME | moral bedtime stories, cute animals | what stories to write |
| LANGUAGE | English | story language (also change TTS_VOICE) |
| TTS_VOICE | en-US-AnaNeural | any voice from `edge-tts --list-voices` |
| VIDEO_FORMAT | long | `long` (16:9) or `short` (9:16 Shorts) |
| UPLOAD_PRIVACY | private | `private`, `unlisted` or `public` |
| MADE_FOR_KIDS | true | YouTube requires you to declare this honestly |

## Important things to know
- **Uploads stay private** until your API project passes Google's YouTube API compliance audit
  (search "YouTube API Services audit form"). Until then, publish manually in YouTube Studio or request the audit.
- **Quota**: default 10,000 units/day, one upload costs about 1,600. One video a day is fine.
- **Monetization risk**: fully automated, repetitive AI content can be rejected under YouTube's
  "inauthentic content" policy. Reviewing videos before they go public, and varying characters and story formats, helps.
- **Made for kids** videos have limits (no comments, no personalized ads). Choose the setting that is true for your channel.
- AI voice and visuals are disclosed via `containsSyntheticMedia`.
- Pollinations is a free image service with no SLA. If it fails, the bot falls back to a plain placeholder;
  watch your first runs. You can swap `images.py` for another image API later.
- Background music is optional: drop a track you have the licence for in `assets/music/`.
- `history.json` is committed back by the workflow, so keep Actions write permission enabled.

## Run locally
```
pip install -r requirements.txt   # also install ffmpeg
export GROQ_API_KEY=...
python main.py                    # skips upload if YouTube secrets are not set
```
