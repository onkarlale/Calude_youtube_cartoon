import os

def env(name, default=""):
    """Like os.environ.get, but an EMPTY value (what GitHub passes for an unset variable) also falls back to the default."""
    value = os.environ.get(name)
    return value.strip() if value and value.strip() else default

# ---- Secrets / keys (set as GitHub Actions secrets) ----
GROQ_API_KEY = env("GROQ_API_KEY")
GROQ_MODEL = env("GROQ_MODEL")  # optional override; empty = auto-pick a working model from your Groq account

CF_ACCOUNT_ID = env("CF_ACCOUNT_ID")   # Cloudflare Workers AI (free FLUX.1 schnell images)
CF_API_TOKEN = env("CF_API_TOKEN")

YT_CLIENT_ID = env("YT_CLIENT_ID")
YT_CLIENT_SECRET = env("YT_CLIENT_SECRET")
YT_REFRESH_TOKEN = env("YT_REFRESH_TOKEN")

# ---- Channel settings (edit these or set as repo Variables) ----
CHANNEL_THEME = env("CHANNEL_THEME", "hilarious clean comedy cartoons with relatable everyday situations, for everyone")
LANGUAGE = env("LANGUAGE", "Hindi (Devanagari script)")
TTS_VOICE = env("TTS_VOICE", "hi-IN-SwaraNeural")   # Hindi: hi-IN-SwaraNeural (female) or hi-IN-MadhurNeural (male)
NUM_SCENES = int(env("NUM_SCENES", "14"))   # more, shorter scenes = faster, funnier cuts
ART_STYLE = env(
    "ART_STYLE",
    "high quality 2D cartoon illustration, clean outlines, soft shading, funny exaggerated expressions, "
    "bright vibrant colors, detailed background, consistent character design",
)

VOICE_A = env("VOICE_A", "hi-IN-MadhurNeural")   # character A: deep, slow
VOICE_B = env("VOICE_B", "hi-IN-SwaraNeural")    # character B: squeaky (pitch-raised)

def voice_for(speaker):
    """(voice, pitch) for narrator / character a / character b"""
    return {"a": (VOICE_A, "-8Hz"), "b": (VOICE_B, "+35Hz")}.get(speaker, (TTS_VOICE, "+0Hz"))

TTS_RATE = env("TTS_RATE", "+6%")   # slightly faster voice = more comic energy (e.g. "+0%", "+10%")

# "long" = 1280x720 YouTube video, "short" = 720x1280 YouTube Short
FORMAT = env("VIDEO_FORMAT", "long").lower()
WIDTH, HEIGHT = (720, 1280) if FORMAT == "short" else (1280, 720)

# private = safe default (also forced by YouTube until your API project passes audit)
PRIVACY = env("UPLOAD_PRIVACY", "public")
MADE_FOR_KIDS = env("MADE_FOR_KIDS", "false").lower() == "true"
CATEGORY_ID = "1"  # Film & Animation
