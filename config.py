import os

def env(name, default=""):
    """Like os.environ.get, but an EMPTY value (what GitHub passes for an unset variable) also falls back to the default."""
    value = os.environ.get(name)
    return value.strip() if value and value.strip() else default

# ---- Secrets / keys (set as GitHub Actions secrets) ----
GROQ_API_KEY = env("GROQ_API_KEY")
GROQ_MODEL = env("GROQ_MODEL")  # optional override; empty = auto-pick a working model from your Groq account

YT_CLIENT_ID = env("YT_CLIENT_ID")
YT_CLIENT_SECRET = env("YT_CLIENT_SECRET")
YT_REFRESH_TOKEN = env("YT_REFRESH_TOKEN")

# ---- Channel settings (edit these or set as repo Variables) ----
CHANNEL_THEME = env("CHANNEL_THEME", "short moral bedtime stories for kids with cute animal characters")
LANGUAGE = env("LANGUAGE", "English")
TTS_VOICE = env("TTS_VOICE", "en-US-AnaNeural")   # run: edge-tts --list-voices
NUM_SCENES = int(env("NUM_SCENES", "8"))
ART_STYLE = env(
    "ART_STYLE",
    "high quality 2D cartoon illustration, clean outlines, soft shading, children's storybook style, "
    "bright friendly colors, detailed background, consistent character design",
)

# "long" = 1280x720 YouTube video, "short" = 720x1280 YouTube Short
FORMAT = env("VIDEO_FORMAT", "long").lower()
WIDTH, HEIGHT = (720, 1280) if FORMAT == "short" else (1280, 720)

# private = safe default (also forced by YouTube until your API project passes audit)
PRIVACY = env("UPLOAD_PRIVACY", "private")
MADE_FOR_KIDS = env("MADE_FOR_KIDS", "true").lower() == "true"
CATEGORY_ID = "1"  # Film & Animation
