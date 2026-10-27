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

T0 = time.time()


def log(m):
    print(f"[{time.time() - T0:6.0f}s] {m}", flush=True)


def run(cmd, cwd=None, env=None, check=True):
    log("$ " + (cmd if isinstance(cmd, str) else " ".join(map(str, cmd))))
    r = subprocess.run(cmd, cwd=cwd, env=env, shell=isinstance(cmd, str))
    if check and r.returncode != 0:
        raise SystemExit(f"COMMAND FAILED ({r.returncode}): {cmd}")
    return r.returncode


PAYLOAD = json.loads(base64.b64decode("__PAYLOAD_B64__"))
SCRIPT, CFG, RUN_ID = PAYLOAD["script"], PAYLOAD["config"], PAYLOAD["run_id"]

WORK = Path("/kaggle/working")
JOB = Path("/tmp/job")
JOB.mkdir(parents=True, exist_ok=True)
(JOB / "tts_lib.py").write_text(PAYLOAD["tts_lib"], encoding="utf-8")

# ------------------------------------------------------------------ 1. voice
run([sys.executable, "-m", "pip", "install", "-q", "edge-tts", "gTTS", "uv"])
sys.path.insert(0, str(JOB))
import tts_lib  # noqa: E402

timings = tts_lib.synthesize(SCRIPT, JOB / "tts", CFG)
shutil.copy(JOB / "tts" / "voice.wav", WORK / "voice.wav")
shutil.copy(JOB / "tts" / "timings.json", WORK / "timings.json")
TOTAL = timings["total"]
log(f"voice ready: {TOTAL:.1f}s")

# ------------------------------------------------------------------ 2. MuseTalk
# The idle loop is built right here from the face image sent inside the payload (no Kaggle dataset needed).
(JOB / "comedian.png").write_bytes(base64.b64decode(PAYLOAD["face_b64"]))
IDLE = str(JOB / "base_idle.mp4")
run(["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-framerate", "25", "-i", str(JOB / "comedian.png"),
     "-vf", "scale=1408:792:flags=lanczos,crop=1280:720:x='64+14*sin(2*PI*t/7)':y='36+8*sin(2*PI*t/3.5)',format=yuv420p",
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
    uvp("setuptools<70", "wheel", "cython", "numpy<2", check=False)
    uvp("--no-build-isolation", "chumpy", check=False)
    uvp("mmengine")
    uvp("--find-links", MMCV_URL, "--only-binary", "mmcv", "mmcv==2.0.1")
    uvp("mmdet==3.1.0")
    if uvp("mmpose==1.1.0", check=False) != 0:
        uvp("--no-build-isolation", "mmpose==1.1.0")
    uvp("gdown", "huggingface_hub[cli]", check=False)
    run([PY, "-c", "import torch, mmcv, mmpose, mmdet; print('torch', torch.__version__, 'cuda', torch.cuda.is_available())"])


def get_weights():
    models = MT / "models"
    cached = [Path(p).parent for p in glob.glob("/kaggle/input/**/musetalkV15", recursive=True)]
    if cached:
        log(f"copying cached weights from {cached[0]}")
        shutil.copytree(cached[0], models, dirs_exist_ok=True)
    else:
        env = {**os.environ, "PATH": f"{VENV}/bin:" + os.environ["PATH"]}
        run("bash download_weights.sh", cwd=str(MT), env=env)
    need = ["musetalkV15/unet.pth", "musetalkV15/musetalk.json", "dwpose", "face-parse-bisent", "sd-vae", "whisper"]
    missing = [n for n in need if not (models / n).exists()]
    if missing:
        raise SystemExit(f"MuseTalk weights missing after download: {missing}")


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
         "-vf", "fps=25,scale=1280:720", "-c:v", "libx264", "-crf", "17", "-preset", "fast", "-pix_fmt", "yuv420p", str(part)])
    parts.append(part)

lst = JOB / "concat.txt"
lst.write_text("".join(f"file '{p}'\n" for p in parts), encoding="utf-8")
run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(WORK / "talking.mp4")])
(WORK / "run_id.txt").write_text(RUN_ID, encoding="utf-8")
log("DONE. talking.mp4 written.")
