import asyncio, os, subprocess, time

def synth(text, path, voice, retries=4):
    import edge_tts
    last = None
    for attempt in range(retries):
        try:
            async def _run():
                await edge_tts.Communicate(text, voice).save(path)
            asyncio.run(_run())
            if os.path.getsize(path) > 1000:
                return
            raise RuntimeError("voice file is empty")
        except Exception as e:
            last = e
            print(f"   voice attempt {attempt+1} failed: {e}")
            time.sleep(4 * (attempt + 1))
    raise RuntimeError(f"Voice generation failed after {retries} tries: {last}")

def duration(path):
    out = subprocess.check_output([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=nw=1:nk=1", path])
    return float(out.strip())
