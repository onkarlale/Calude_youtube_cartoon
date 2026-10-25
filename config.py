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

# ---- Format: "short" = vertical 720x1280 YouTube Short, "long" = 1280x720 video ----
FORMAT = env("VIDEO_FORMAT", "short").lower()
IS_SHORT = FORMAT == "short"
WIDTH, HEIGHT = (720, 1280) if IS_SHORT else (1280, 720)

# ---- Channel settings (edit these or set as repo Variables) ----
CHANNEL_THEME = env("CHANNEL_THEME", "hilarious clean comedy cartoons with relatable everyday situations, for everyone")
LANGUAGE = env("LANGUAGE", "Hindi (Devanagari script)")
TTS_VOICE = env("TTS_VOICE", "hi-IN-SwaraNeural")   # Hindi: hi-IN-SwaraNeural (female) or hi-IN-MadhurNeural (male)
NUM_SCENES = int(env("NUM_SCENES", "10" if IS_SHORT else "14"))   # includes 1 final question scene; Short ~40 s
LINE_WORDS = "6-14" if IS_SHORT else "8-22"                       # words per spoken line
TTS_RATE = env("TTS_RATE", "+12%" if IS_SHORT else "+6%")        # faster voice = more energy

if IS_SHORT:
    FORMAT_RULES = ("This is a YouTube SHORT (vertical, about 35-45 seconds). Scene 1 MUST be a scroll-stopping hook within "
                    "2 seconds: an absurd claim, a shocking question or a chaotic moment, never a slow introduction. "
                    "Something new and funny happens in every scene, no filler.")
else:
    FORMAT_RULES = "This is a full episode of about 2 minutes."

# ---- The two recurring stars: same look in every episode builds fans and keeps the art consistent ----
NAME_A = env("NAME_A", "Bhola")
NAME_B = env("NAME_B", "Tinku")
MAIN_CHARACTERS = env(
    "MAIN_CHARACTERS",
    "Bhola: a chubby round brown bear with a yellow turban, sleepy half-closed eyes and a big belly. "
    "Tinku: a tiny green parrot with huge round glasses and a small red cap.")
CAST_BIO = env(
    "CAST_BIO",
    "Bhola (character a, deep slow voice): lazy, sleepy, loves food, but accidentally gets lucky. "
    "Tinku (character b, squeaky voice): hyper, over-smart, makes grand plans that backfire.")

USE_TRENDS = env("USE_TRENDS", "true").lower() == "true"   # build episodes around today's trending topics
TRENDS_GEO = env("TRENDS_GEO", "IN")

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

# private = safe default (also forced by YouTube until your API project passes audit)
PRIVACY = env("UPLOAD_PRIVACY", "public")
MADE_FOR_KIDS = env("MADE_FOR_KIDS", "false").lower() == "true"
CATEGORY_ID = "1"  # Film & Animation
