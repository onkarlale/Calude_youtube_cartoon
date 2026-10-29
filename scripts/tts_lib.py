#!/usr/bin/env python3
"""Self-contained Hindi TTS + timeline builder.

Used in two places:
  * embedded into the Kaggle kernel (scripts/kaggle_run.py base64-embeds this file)
  * run locally by the pipeline for the no-lip-sync fallback video

Do NOT import anything from the repo here: the file must work on its own.

Output (in --out):
  voice.wav      mono 24 kHz, the whole performance with pauses
  timings.json   {"total": sec, "lead": sec, "tail": sec, "segments": [{i,text,role,start,end,pause,laugh}]}
"""
import argparse
import asyncio
import json
import subprocess
import time
from pathlib import Path

SR = 24000


def _run(cmd):
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"cmd failed: {' '.join(map(str, cmd))}\n{p.stderr[-1500:]}")
    return p.stdout


def duration(path):
    out = _run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "default=nw=1:nk=1", str(path)])
    return float(out.strip())


def make_silence(path, ms):
    _run(["ffmpeg", "-y", "-f", "lavfi", "-i", f"anullsrc=r={SR}:cl=mono",
          "-t", f"{ms / 1000:.3f}", "-c:a", "pcm_s16le", str(path)])


def to_wav_trimmed(src, dst):
    """Convert to 24k mono wav and strip leading/trailing silence so pauses are exact."""
    af = ("silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.04,"
          "areverse,"
          "silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.04,"
          "areverse")
    _run(["ffmpeg", "-y", "-i", str(src), "-af", af, "-ar", str(SR), "-ac", "1",
          "-c:a", "pcm_s16le", str(dst)])


async def _edge(text, voice, rate, pitch, out):
    import edge_tts
    comm = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
    await comm.save(str(out))


def tts_gtts(text, out):
    from gtts import gTTS
    gTTS(text=text, lang="hi").save(str(out))


def synth_segment(text, role, cfg, raw_path):
    v = cfg["voice"]
    rate = v.get("rate", {}).get(role, "+0%")
    pitch = v.get("pitch", "+0Hz")
    last = None
    for attempt in range(3):
        try:
            asyncio.run(_edge(text, v["name"], rate, pitch, raw_path))
            if Path(raw_path).exists() and Path(raw_path).stat().st_size > 500:
                return "edge"
        except Exception as e:  # network / token / service errors
            last = e
        time.sleep(2 * (attempt + 1))
    print(f"[tts] edge-tts failed ({last}); falling back to gTTS", flush=True)
    tts_gtts(text, raw_path)
    return "gtts"


def synthesize(script, outdir, cfg):
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    tmp = outdir / "parts"
    tmp.mkdir(exist_ok=True)
    t = cfg["timing"]

    parts, timeline, engines = [], [], set()
    cursor = 0.0

    def add(path):
        nonlocal cursor
        d = duration(path)
        parts.append(path)
        cursor += d
        return d

    lead = tmp / "lead.wav"
    make_silence(lead, t["lead_ms"])
    add(lead)

    for i, seg in enumerate(script["segments"]):
        raw = tmp / f"s{i:03d}_raw.mp3"
        wav = tmp / f"s{i:03d}.wav"
        engines.add(synth_segment(seg["text"], seg.get("role", "setup"), cfg, raw))
        to_wav_trimmed(raw, wav)
        start = cursor
        add(wav)
        end = cursor
        pause_ms = int(seg.get("pause_after_ms", 300))
        sil = tmp / f"s{i:03d}_pause.wav"
        make_silence(sil, pause_ms)
        add(sil)
        timeline.append({
            "i": i, "text": seg["text"], "role": seg.get("role", "setup"),
            "start": round(start, 3), "end": round(end, 3),
            "pause": round(pause_ms / 1000, 3), "laugh": bool(seg.get("laugh", False)),
        })
        print(f"[tts] {i + 1}/{len(script['segments'])} {end - start:.1f}s", flush=True)

    tail = tmp / "tail.wav"
    make_silence(tail, t["tail_ms"])
    add(tail)

    listfile = tmp / "list.txt"
    listfile.write_text("".join(f"file '{p.resolve()}'\n" for p in parts), encoding="utf-8")
    voice = outdir / "voice.wav"
    _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(listfile),
          "-c:a", "pcm_s16le", str(voice)])

    timings = {"total": round(cursor, 3), "lead": t["lead_ms"] / 1000, "tail": t["tail_ms"] / 1000,
               "engines": sorted(engines), "segments": timeline}
    (outdir / "timings.json").write_text(json.dumps(timings, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[tts] done: total {cursor:.1f}s engines={sorted(engines)}", flush=True)
    return timings


def _bump_rate(rate, pct):
    """'+0%' -> '+10%', '-6%' -> '+4%'"""
    try:
        v = int(str(rate).replace("%", "").replace("+", "")) + pct
    except ValueError:
        v = pct
    return f"{v:+d}%"


def synthesize_capped(script, outdir, cfg, max_total=None):
    """synthesize(), but if the whole set is longer than max_total seconds, redo it 10% then 20% faster."""
    timings = synthesize(script, outdir, cfg)
    if not max_total:
        return timings
    for bump in (10, 20):
        if timings["total"] <= max_total:
            break
        print(f"[tts] {timings['total']:.0f}s is over the {max_total}s limit; redoing {bump}% faster", flush=True)
        cfg2 = json.loads(json.dumps(cfg))
        rates = cfg2["voice"].setdefault("rate", {})
        for role in ("setup", "punch", "aside"):
            rates[role] = _bump_rate(rates.get(role, "+0%"), bump)
        timings = synthesize(script, outdir, cfg2)
    if timings["total"] > max_total:
        print(f"[tts] WARNING: still {timings['total']:.0f}s (limit {max_total}s). YouTube may not treat it as a Short.", flush=True)
    return timings


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--script", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--config", required=True)
    ap.add_argument("--max-total", type=float, default=None)
    a = ap.parse_args()
    synthesize_capped(json.loads(Path(a.script).read_text(encoding="utf-8")), a.out,
                      json.loads(Path(a.config).read_text(encoding="utf-8")), a.max_total)
