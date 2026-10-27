#!/usr/bin/env bash
# Installs ffmpeg + ffprobe + a Hindi (Devanagari) font WITHOUT relying on the slow apt mirror.
# Primary: static ffmpeg build and Noto font downloaded from GitHub (fast from GitHub runners).
# Backup:  apt-get with hard time limits. Results are cached by the workflow (~/ffbin, ~/.fonts).
set -u
BIN="$HOME/ffbin"
mkdir -p "$BIN" "$HOME/.fonts"
export PATH="$BIN:$PATH"
[ -n "${GITHUB_PATH:-}" ] && echo "$BIN" >> "$GITHUB_PATH"

ffmpeg_ok() {
  command -v ffmpeg >/dev/null 2>&1 && command -v ffprobe >/dev/null 2>&1 \
    && ffmpeg -hide_banner -filters 2>/dev/null | grep -q " subtitles " \
    && ffmpeg -hide_banner -filters 2>/dev/null | grep -q " drawtext "
}
font_ok() { fc-list 2>/dev/null | grep -qi "devanagari"; }

echo "== ffmpeg =="
if ffmpeg_ok; then
  echo "ffmpeg already available: $(command -v ffmpeg)"
else
  for url in \
    "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-linux64-gpl.tar.xz"; do
    echo "downloading $url"
    if curl -fsSL --retry 3 --retry-delay 3 --max-time 300 -o /tmp/ff.tar.xz "$url"; then
      tar -xJf /tmp/ff.tar.xz -C /tmp 2>/dev/null
      src="$(ls -d /tmp/ffmpeg-*linux64-gpl 2>/dev/null | head -1)"
      if [ -n "$src" ] && [ -x "$src/bin/ffmpeg" ]; then
        cp "$src/bin/ffmpeg" "$src/bin/ffprobe" "$BIN/"
      fi
      rm -rf /tmp/ff.tar.xz /tmp/ffmpeg-*linux64-gpl
    fi
    ffmpeg_ok && break
  done
  if ! ffmpeg_ok; then
    echo "static ffmpeg failed; trying apt (time-limited)"
    for i in 1 2; do
      timeout 150 sudo apt-get update -qq -o Acquire::Retries=1 \
        && timeout 240 sudo apt-get install -y -qq --no-install-recommends ffmpeg && break
    done
  fi
fi
if ! ffmpeg_ok; then
  echo "::error::Could not get a working ffmpeg (needs ffprobe, subtitles and drawtext filters)."
  exit 1
fi
ffmpeg -version | head -1

echo "== Hindi font =="
if font_ok; then
  echo "Devanagari font already available"
else
  for name in NotoSansDevanagari-Bold NotoSansDevanagari-Regular; do
    for url in \
      "https://github.com/notofonts/notofonts.github.io/raw/main/fonts/NotoSansDevanagari/full/ttf/$name.ttf" \
      "https://github.com/notofonts/devanagari/raw/main/fonts/NotoSansDevanagari/full/ttf/$name.ttf"; do
      if curl -fsSL --retry 3 --retry-delay 3 --max-time 120 -o "$HOME/.fonts/$name.ttf" "$url" \
         && [ "$(stat -c %s "$HOME/.fonts/$name.ttf")" -gt 50000 ]; then
        echo "got $name"
        break
      fi
      rm -f "$HOME/.fonts/$name.ttf"
    done
  done
  fc-cache -f >/dev/null 2>&1
  if ! font_ok; then
    echo "font download failed; trying apt (time-limited)"
    timeout 150 sudo apt-get update -qq -o Acquire::Retries=1 \
      && timeout 240 sudo apt-get install -y -qq --no-install-recommends fonts-lohit-deva
    fc-cache -f >/dev/null 2>&1
  fi
fi
if ! font_ok; then
  echo "::error::No Devanagari font available, Hindi captions would show empty boxes."
  exit 1
fi
fc-list | grep -i devanagari | head -2

# DejaVu Bold is used for the thumbnail and intro text
if [ ! -f /usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf ]; then
  echo "DejaVu missing; trying apt (time-limited)"
  timeout 150 sudo apt-get install -y -qq --no-install-recommends fonts-dejavu-core || true
fi
echo "system setup OK"
