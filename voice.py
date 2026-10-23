import asyncio, subprocess

def synth(text, path, voice):
    import edge_tts
    async def _run():
        await edge_tts.Communicate(text, voice).save(path)
    asyncio.run(_run())

def duration(path):
    out = subprocess.check_output([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=nw=1:nk=1", path])
    return float(out.strip())
