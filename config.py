import os

# ---- Secrets / keys (set as GitHub Actions secrets) ----
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_MODEL = os.environ.get("GROQ_MODEL", "")  # optional override; empty = auto-pick a working model from your Groq account

YT_CLIENT_ID = os.environ.get("YT_CLIENT_ID", "")
YT_CLIENT_SECRET = os.environ.get("YT_CLIENT_SECRET", "")
YT_REFRESH_TOKEN = os.environ.get("YT_REFRESH_TOKEN", "")

# ---- Channel settings (edit these or set as repo Variables) ----
CHANNEL_THEME = os.environ.get("CHANNEL_THEME", "short moral bedtime stories for kids with cute animal characters")
LANGUAGE = os.environ.get("LANGUAGE", "English")
TTS_VOICE = os.environ.get("TTS_VOICE", "en-US-AnaNeural")   # run: edge-tts --list-voices
NUM_SCENES = int(os.environ.get("NUM_SCENES", "8"))
ART_STYLE = os.environ.get(
    "ART_STYLE",
    "colorful 2D cartoon illustration, soft shapes, children's storybook style, bright friendly colors",
)

# "long" = 1280x720 YouTube video, "short" = 720x1280 YouTube Short
FORMAT = os.environ.get("VIDEO_FORMAT", "long")
WIDTH, HEIGHT = (1280, 720) if FORMAT == "long" else (720, 1280)

# private = safe default (also forced by YouTube until your API project passes audit)
PRIVACY = os.environ.get("UPLOAD_PRIVACY", "private")
MADE_FOR_KIDS = os.environ.get("MADE_FOR_KIDS", "true").lower() == "true"
CATEGORY_ID = "1"  # Film & Animation
