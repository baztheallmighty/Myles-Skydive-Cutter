#!/bin/bash
# The only thing you run. Checks what this folder has, installs anything missing, then opens the app.
#
#   ./skydive-cutter.sh                 open the app
#   ./skydive-cutter.sh --review        open it on the Review tab
#   ./skydive-cutter.sh --repair        install everything again
#   ./skydive-cutter.sh --check-only    say what is missing and stop
#   ./skydive-cutter.sh --cpu           install for the processor rather than the GPU
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$root"
arch="$(uname -m)"
python=".runtime/$arch/python/bin/python3"
open_review=0
repair=0
check_only=0
skip_check=0
setup_flags=()
for argument in "$@"; do
  case "$argument" in
    --review) open_review=1 ;;
    --repair) repair=1 ;;
    --check-only) check_only=1 ;;
    --skip-check) skip_check=1 ;;
    --cpu) setup_flags+=(--cpu) ;;
    *) echo "Unknown option: ${argument}"; exit 2 ;;
  esac
done

# A folder unzipped from a download is quarantined, which stops the scripts running. Clear our own folder only.
xattr -dr com.apple.quarantine "$root" 2>/dev/null || true
# Some unzip tools drop the permission bits. This script is run through bash by the .command files, so it can put
# them back for everything else.
chmod +x ./*.command ./*.sh 2>/dev/null || true

missing=()
check_install() {
  missing=()
  if [ ! -f installation.json ]; then missing+=("the app runtime"); return; fi
  if [ ! -x "$python" ]; then missing+=("the app runtime"); return; fi
  local site
  site="$("$python" -c 'import site;print(site.getsitepackages()[0])' 2>/dev/null || true)"
  for package in torch torchvision PySide6 numpy librosa soundfile sklearn ultralytics; do
    # A library is a folder for most packages, a single .py file for a few (soundfile).
    if [ ! -e "$site/$package" ] && [ ! -e "$site/$package.py" ]; then missing+=("the $package library"); fi
  done
  for tool in ffmpeg ffprobe; do
    [ -x "bin/$tool" ] || missing+=("FFmpeg")
  done
  [ -f yolo11n.pt ] || missing+=("the person detection model")
  # Name and size only, never a checksum: this runs on every start and must not read gigabytes.
  while IFS='|' read -r file bytes; do
    [ -z "$file" ] && continue
    if [ ! -f "cutter_v4/models/$file" ] || [ "$(stat -f%z "cutter_v4/models/$file")" != "$bytes" ]; then
      missing+=("the $file model")
    fi
  done < <("$python" -c "
import json
models = json.load(open('cutter_v4/models/MODELS.json'))['models']
for entry in models.values():
    print(entry['file'] + '|' + str(entry['bytes']))
" 2>/dev/null || true)
}

check_install
if [ $check_only = 1 ]; then
  if [ ${#missing[@]} -eq 0 ]; then echo "Everything this app needs is installed."; exit 0; fi
  echo "Missing:"
  printf '  - %s\n' "${missing[@]}"
  exit 1
fi

if [ $repair = 1 ] || { [ $skip_check = 0 ] && [ ${#missing[@]} -gt 0 ]; }; then
  if [ ${#missing[@]} -gt 0 ] && [ $repair = 0 ]; then
    echo
    echo "Skydive Cutter needs a few things before it can start:"
    printf '  - %s\n' "${missing[@]}"
    echo "Installing them now. This is a one-time download; leave this window open."
  fi
  /bin/bash ./setup.sh "${setup_flags[@]+"${setup_flags[@]}"}" $([ $repair = 1 ] && echo --repair || true)
  check_install
  if [ ${#missing[@]} -gt 0 ]; then
    echo "Setup finished but these are still missing: ${missing[*]}"
    echo "Run ./setup.sh --repair, or look in the logs folder."
    exit 1
  fi
fi

mkdir -p cache/torch cache/ultralytics cache/matplotlib cache/numba logs
export TORCH_HOME="$root/cache/torch"
export YOLO_CONFIG_DIR="$root/cache/ultralytics"
export MPLCONFIGDIR="$root/cache/matplotlib"
export NUMBA_CACHE_DIR="$root/cache/numba"
export PYTHONDONTWRITEBYTECODE=1
stamp="$(date +%Y%m%d_%H%M%S)"
arguments=(-s -B -m app.main)
[ $open_review = 1 ] && arguments+=(--review)
# nohup and no terminal input: closing this Terminal window must not close the app with it.
nohup "$python" "${arguments[@]}" </dev/null >"logs/app-${stamp}.out.log" 2>"logs/app-${stamp}.err.log" &
echo "Skydive Cutter started. You can close this window. If no window appears, see logs/app-${stamp}.err.log"
