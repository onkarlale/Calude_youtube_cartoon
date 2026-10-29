# Kaggle GPU kernel (script type). Runs on Kaggle, NOT on GitHub.
#
# 1. Hindi TTS for each segment -> voice.wav + timings.json   (tts_lib, embedded below)
# 2. MuseTalk 1.5 lip-sync on base_idle.mp4, in ~35 s chunks   -> talking.mp4
#
# kaggle_run.py replaces __PAYLOAD_B64__ with the script, config and tts_lib source.
# Everything big (venv, MuseTalk clone, weights) lives in /tmp so it is NOT downloaded as output.
# Only these files are left in /kaggle/working: voice.wav, timings.json, talking.mp4, run_id.txt

import base64
import glob
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

RENDER_VERSION = 8
BASE_B64 = "__BASE_B64__"   # the day's base picture/video, filled in by scripts/kaggle_run.py
T0 = time.time()


def log(m):
    print(f"[{time.time() - T0:6.0f}s] {m}", flush=True)


def run(cmd, cwd=None, env=None, check=True):
    log("$ " + (cmd if isinstance(cmd, str) else " ".join(map(str, cmd))))
    r = subprocess.run(cmd, cwd=cwd, env=env, shell=isinstance(cmd, str))
    if check and r.returncode != 0:
        raise SystemExit(f"COMMAND FAILED ({r.returncode}): {cmd}")
    return r.returncode


log(f"render.py version {RENDER_VERSION}")
PAYLOAD = json.loads(base64.b64decode("__PAYLOAD_B64__"))
SCRIPT, CFG, RUN_ID = PAYLOAD["script"], PAYLOAD["config"], PAYLOAD["run_id"]
VW, VH = CFG.get("video_size", [1280, 720])      # size of the lip-sync video (vertical for Shorts)

WORK = Path("/kaggle/working")
JOB = Path("/tmp/job")
JOB.mkdir(parents=True, exist_ok=True)
(JOB / "tts_lib.py").write_text(PAYLOAD["tts_lib"], encoding="utf-8")

# ------------------------------------------------------------------ 0. internet check (fail fast)
import socket  # noqa: E402

try:
    socket.setdefaulttimeout(8)
    socket.gethostbyname("pypi.org")
    log("internet: OK")
except OSError:
    raise SystemExit(
        "NO INTERNET in this Kaggle notebook. Verify your phone number at kaggle.com/settings "
        "(Phone Verification), then make sure Internet is ON in the notebook's Session options, and run again.")

# ------------------------------------------------------------------ 1. voice
run([sys.executable, "-m", "pip", "install", "-q", "edge-tts", "gTTS", "uv"])
sys.path.insert(0, str(JOB))
import tts_lib  # noqa: E402

timings = tts_lib.synthesize_capped(SCRIPT, JOB / "tts", CFG, CFG.get("max_total"))
shutil.copy(JOB / "tts" / "voice.wav", WORK / "voice.wav")
shutil.copy(JOB / "tts" / "timings.json", WORK / "timings.json")
TOTAL = timings["total"]
log(f"voice ready: {TOTAL:.1f}s")

# ------------------------------------------------------------------ 2. MuseTalk
# The idle loop is built right here from the face image sent inside the payload (no Kaggle dataset needed).
IDLE = str(JOB / "base_idle.mp4")
if PAYLOAD.get("base_kind") == "video":
    (JOB / "base_src.mp4").write_bytes(base64.b64decode(BASE_B64))
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(JOB / "base_src.mp4"), "-an", "-vf",
         f"scale={VW}:{VH}:force_original_aspect_ratio=increase,crop={VW}:{VH},fps=25,format=yuv420p",
         "-t", "14", "-c:v", "libx264", "-crf", "16", "-pix_fmt", "yuv420p", IDLE])
else:
    (JOB / "comedian.png").write_bytes(base64.b64decode(BASE_B64))
    run(["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-framerate", "25", "-i", str(JOB / "comedian.png"),
         "-vf", f"scale=trunc({VW}*1.1/2)*2:trunc({VH}*1.1/2)*2:flags=lanczos,"
                f"crop={VW}:{VH}:x='(iw-ow)/2+{VW * 0.011:.1f}*sin(2*PI*t/7)':y='(ih-oh)/2+{VH * 0.011:.1f}*sin(2*PI*t/3.5)',format=yuv420p",
         "-t", "14", "-c:v", "libx264", "-crf", "16", "-pix_fmt", "yuv420p", IDLE])
log(f"idle video built: {IDLE}")

ROOTDIR = Path("/tmp/mt")
MT = ROOTDIR / "MuseTalk"
VENV = ROOTDIR / "venv"
PY = str(VENV / "bin" / "python")
MMCV_URL = "https://download.openmmlab.com/mmcv/dist/cu118/torch2.0.0/index.html"


def uvp(*args, check=True):
    return run(["uv", "pip", "install", "--python", PY, *args], check=check)


def setup_env():
    ROOTDIR.mkdir(parents=True, exist_ok=True)
    run(["git", "clone", "--depth", "1", "https://github.com/TMElyralab/MuseTalk.git", str(MT)])
    run(["uv", "venv", str(VENV), "--python", "3.10"])
    uvp("torch==2.0.1", "torchvision==0.15.2", "torchaudio==2.0.2", "--index-url", "https://download.pytorch.org/whl/cu118")
    uvp("-r", str(MT / "requirements.txt"))
    uvp("pip", "setuptools<70", "wheel", "cython", "numpy<2", check=False)
    uvp("mmengine")
    uvp("--find-links", MMCV_URL, "--only-binary", "mmcv", "mmcv==2.0.1")
    uvp("mmdet==3.1.0")
    # mmpose depends on chumpy, which cannot be built here and is only used for 3D body models (not by MuseTalk).
    # So: install mmpose without dependencies, add its real dependencies by hand, and drop in a tiny chumpy stand-in.
    uvp("--no-deps", "mmpose==1.1.0")
    uvp("json_tricks", "munkres", "scipy", "matplotlib", "pillow", check=False)
    uvp("xtcocotools", check=False)
    site = subprocess.check_output([PY, "-c", "import site; print(site.getsitepackages()[0])"], text=True).strip()
    stub = Path(site) / "chumpy"
    stub.mkdir(exist_ok=True)
    (stub / "__init__.py").write_text("# stand-in: real chumpy cannot be built here and is not needed for 2D pose.\n", encoding="utf-8")
    log(f"chumpy stand-in written to {stub}")
    uvp("gdown", "huggingface_hub[cli]", check=False)
    run([PY, "-c", "import torch, mmcv, mmpose, mmdet; print('torch', torch.__version__, 'cuda', torch.cuda.is_available())"])


def get_weights():
    """Download every MuseTalk weight file ourselves (the repo's download_weights.sh uses tools that no longer work)."""
    models = MT / "models"
    models.mkdir(parents=True, exist_ok=True)
    cached = [Path(p).parent for p in glob.glob("/kaggle/input/**/musetalkV15", recursive=True)]
    if cached:
        log(f"copying cached weights from {cached[0]}")
        shutil.copytree(cached[0], models, dirs_exist_ok=True)
    else:
        run([sys.executable, "-m", "pip", "install", "-q", "huggingface_hub", "gdown"])
        from huggingface_hub import hf_hub_download

        def hf(repo, filename, sub=None):
            target = models / sub if sub else models
            target.mkdir(parents=True, exist_ok=True)
            for attempt in range(3):
                try:
                    p = hf_hub_download(repo_id=repo, filename=filename, local_dir=str(target))
                    log(f"downloaded {repo}/{filename} -> {p}")
                    return
                except Exception as e:  # noqa: BLE001
                    log(f"download {repo}/{filename} failed (try {attempt + 1}): {e}")
                    time.sleep(5)
            raise SystemExit(f"Could not download {repo}/{filename}")

        hf("TMElyralab/MuseTalk", "musetalkV15/unet.pth")
        hf("TMElyralab/MuseTalk", "musetalkV15/musetalk.json")
        hf("stabilityai/sd-vae-ft-mse", "config.json", "sd-vae")
        hf("stabilityai/sd-vae-ft-mse", "diffusion_pytorch_model.bin", "sd-vae")
        for f in ("config.json", "pytorch_model.bin", "preprocessor_config.json"):
            hf("openai/whisper-tiny", f, "whisper")
        hf("yzd-v/DWPose", "dw-ll_ucoco_384.pth", "dwpose")

        fp = models / "face-parse-bisent"
        fp.mkdir(parents=True, exist_ok=True)
        import urllib.request
        urllib.request.urlretrieve("https://download.pytorch.org/models/resnet18-5c106cde.pth", str(fp / "resnet18-5c106cde.pth"))
        target = fp / "79999_iter.pth"
        try:
            import gdown
            gdown.download(id="154JgKpzCPW82qINcVieuPH3fZ2e0P812", output=str(target), quiet=False)
        except Exception as e:  # noqa: BLE001
            log(f"gdown failed: {e}")
        if not target.exists() or target.stat().st_size < 1_000_000:
            log("trying Hugging Face mirror for face-parse model")
            try:
                hf("ManyOtherFunctions/face-parse-bisent", "79999_iter.pth", "face-parse-bisent")
            except SystemExit:
                pass
    need = [
        "musetalkV15/unet.pth", "musetalkV15/musetalk.json", "dwpose/dw-ll_ucoco_384.pth",
        "face-parse-bisent/79999_iter.pth", "face-parse-bisent/resnet18-5c106cde.pth",
        "sd-vae/config.json", "sd-vae/diffusion_pytorch_model.bin",
        "whisper/config.json", "whisper/pytorch_model.bin",
    ]
    def ok(n):
        f = models / n
        floor = 1_000_000 if f.suffix in (".pth", ".bin") else 2   # big model files must be big, small configs just non-empty
        return f.exists() and f.stat().st_size >= floor

    missing = [n for n in need if not ok(n)]
    if missing:
        raise SystemExit(f"MuseTalk weights missing after download: {missing}")
    log("all MuseTalk weights present")


def make_chunks(max_len=36.0):
    """Greedy chunks on segment boundaries so every chunk is <= max_len seconds."""
    edges = [round(s["end"] + s["pause"], 3) for s in timings["segments"]]
    chunks, start, last_ok = [], 0.0, 0.0
    for e in edges:
        if e - start > max_len and last_ok > start:
            chunks.append((start, last_ok))
            start = last_ok
        last_ok = e
    chunks.append((start, TOTAL))  # last chunk also carries the tail silence
    return chunks


setup_env()
get_weights()

CH = JOB / "chunks"
CH.mkdir(exist_ok=True)
chunks = make_chunks()
log(f"{len(chunks)} chunks: " + ", ".join(f"{a:.0f}-{b:.0f}s" for a, b in chunks))
yaml_lines = []
for i, (a, b) in enumerate(chunks):
    wav = CH / f"chunk{i:03d}.wav"
    run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{a:.3f}", "-t", f"{b - a:.3f}", "-i", str(WORK / "voice.wav"),
         "-ar", "16000", "-ac", "1", str(wav)])
    yaml_lines.append(f'task_{i}:\n  video_path: "{IDLE}"\n  audio_path: "{wav}"\n')
yaml_path = JOB / "tasks.yaml"
yaml_path.write_text("\n".join(yaml_lines), encoding="utf-8")

env = {**os.environ, "PATH": f"{VENV}/bin:" + os.environ["PATH"], "PYTHONPATH": str(MT)}
RES = JOB / "result"
run([PY, "-m", "scripts.inference", "--inference_config", str(yaml_path), "--result_dir", str(RES),
     "--unet_model_path", "models/musetalkV15/unet.pth", "--unet_config", "models/musetalkV15/musetalk.json",
     "--version", "v15", "--fps", "25", "--batch_size", "8", "--use_float16"], cwd=str(MT), env=env)

parts = []
for i, (a, b) in enumerate(chunks):
    found = [p for p in glob.glob(str(RES / "**" / f"*chunk{i:03d}*.mp4"), recursive=True) if "temp" not in Path(p).name]
    if not found:
        raise SystemExit(f"MuseTalk produced no output for chunk {i}")
    part = JOB / f"part{i:03d}.mp4"
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", found[0], "-t", f"{b - a:.3f}", "-an",
         "-vf", f"fps=25,scale={VW}:{VH}", "-c:v", "libx264", "-crf", "17", "-preset", "fast", "-pix_fmt", "yuv420p", str(part)])
    parts.append(part)

lst = JOB / "concat.txt"
lst.write_text("".join(f"file '{p}'\n" for p in parts), encoding="utf-8")
run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(WORK / "talking.mp4")])
(WORK / "run_id.txt").write_text(RUN_ID, encoding="utf-8")
log("DONE. talking.mp4 written.")
