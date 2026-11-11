#!/bin/zsh
set -eu
cd -- "${0:A:h}"

if (( $# > 1 )) || [[ ${1:-} != '' && ${1:-} != '--narrated' ]]; then
  print -u2 'Usage: ./Setup.command [--narrated]'
  exit 2
fi

fail() {
  print -u2 -- "$1"
  exit 1
}

full=/opt/homebrew/opt/ffmpeg-full/bin
ffmpeg_cmd=$(command -v ffmpeg || true)
ffprobe_cmd=$(command -v ffprobe || true)
[[ -n "$ffmpeg_cmd" ]] || ffmpeg_cmd="$full/ffmpeg"
[[ -n "$ffprobe_cmd" ]] || ffprobe_cmd="$full/ffprobe"
[[ -x "$ffmpeg_cmd" && -x "$ffprobe_cmd" ]] || fail 'Install FFmpeg with FFprobe and put them on PATH.'
"$ffprobe_cmd" -version >/dev/null
encoders=$("$ffmpeg_cmd" -hide_banner -encoders)
filters=$("$ffmpeg_cmd" -hide_banner -filters)
for encoder in libx264 aac prores_ks; do
  grep -Eq "^[[:space:]]+[^[:space:]]+[[:space:]]+${encoder}[[:space:]]" <<< "$encoders" ||
    fail "FFmpeg on PATH needs the $encoder encoder."
done
grep -Eq '^[[:space:]]+[^[:space:]]+[[:space:]]+loudnorm[[:space:]]' <<< "$filters" ||
  fail 'FFmpeg on PATH needs the loudnorm filter.'

caption_build=''
hdr_build=''
for binary in "$ffmpeg_cmd" "$full/ffmpeg"; do
  [[ -x "$binary" ]] || continue
  build_filters=$("$binary" -hide_banner -filters)
  if [[ -z "$caption_build" ]] && grep -Eq '^[[:space:]]+[^[:space:]]+[[:space:]]+ass[[:space:]]' <<< "$build_filters"; then
    caption_build=$binary
  fi
  if [[ -z "$hdr_build" ]] &&
     grep -Eq '^[[:space:]]+[^[:space:]]+[[:space:]]+zscale[[:space:]]' <<< "$build_filters" &&
     grep -Eq '^[[:space:]]+[^[:space:]]+[[:space:]]+tonemap[[:space:]]' <<< "$build_filters"; then
    hdr_build=$binary
  fi
done
if [[ ${1:-} == '--narrated' && -z "$caption_build" ]]; then
  fail 'Narrated workflows need an FFmpeg build with libass. Install Homebrew ffmpeg-full or put a capable build on PATH.'
fi
if [[ ${1:-} == '--narrated' ]]; then
  scale_options=$("$ffmpeg_cmd" -hide_banner -h filter=scale)
  grep -q 'reset_sar' <<< "$scale_options" ||
    fail 'Landscape output needs an FFmpeg scale filter with reset_sar. Update FFmpeg on PATH.'
fi

if [[ ! -x .venv/bin/python ]]; then
  python_cmd=$(command -v python3.12 || true)
  [[ -n "$python_cmd" ]] || fail 'Install Python 3.12 and put python3.12 on PATH.'
  if command -v uv >/dev/null; then
    uv venv --python "$python_cmd" .venv
  else
    "$python_cmd" -m venv .venv
  fi
fi
.venv/bin/python -c 'import sys; sys.exit(sys.version_info[:2] != (3, 12))' ||
  fail 'The existing .venv must use Python 3.12. Move it aside to create a new one.'
if [[ $(uname -m) == arm64 ]]; then
  .venv/bin/python -c 'import platform, sys; sys.exit(platform.machine() != "arm64")' ||
    fail 'The existing .venv uses an Intel interpreter. Use native ARM64 Python 3.12.'
fi
install_args=(--only-binary :all: --no-deps -r requirements.txt)
if command -v uv >/dev/null; then
  env -u UV_INDEX -u UV_INDEX_URL -u UV_EXTRA_INDEX_URL -u UV_FIND_LINKS uv --no-config pip install --python .venv/bin/python --default-index https://pypi.org/simple "${install_args[@]}"
else
  if ! .venv/bin/python -m pip --version >/dev/null 2>&1; then
    .venv/bin/python -m ensurepip
  fi
  PIP_CONFIG_FILE=/dev/null .venv/bin/python -m pip --isolated install --index-url https://pypi.org/simple "${install_args[@]}"
fi
.venv/bin/python -c 'import numpy; from PIL import Image; Image.new("RGB", (1, 1))'

mkdir -p config catalog review assets/music cache exports feedback
print -- "SDR music reels: $ffmpeg_cmd"
print -- "Narrated captions: ${caption_build:-install an FFmpeg build with libass when needed}"
print -- "HDR input conversion: ${hdr_build:-install an FFmpeg build with zscale and tonemap when needed}"
print 'Ready. See README.md to initialize a local edit.'
