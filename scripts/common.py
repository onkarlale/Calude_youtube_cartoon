"""Shared helpers for the pipeline scripts."""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
BUILD.mkdir(exist_ok=True)


def log(msg):
    print(msg, flush=True)


def load_config():
    return json.loads((ROOT / "config.json").read_text(encoding="utf-8"))


def sh(cmd, cwd=None, check=True):
    """Run a command (list), return stdout. Raise with stderr tail on failure."""
    p = subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if check and p.returncode != 0:
        tail = (p.stderr or "")[-2500:]
        raise RuntimeError(f"Command failed ({p.returncode}): {' '.join(map(str, cmd))}\n{tail}")
    return p.stdout


def fail(msg):
    print(f"ERROR: {msg}", file=sys.stderr, flush=True)
    sys.exit(1)
