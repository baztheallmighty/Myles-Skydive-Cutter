#!/bin/bash
# Installs everything Skydive Cutter needs into this folder: Python, the model libraries, the person detector and
# FFmpeg. Nothing is installed anywhere else, no root password is asked for, and deleting this folder removes all of it.
#
#   ./setup.sh              install what is missing
#   ./setup.sh --repair     install it again, over the top (close Skydive Cutter first)
#   ./setup.sh --cpu        check the install on the processor even where there is an NVIDIA GPU
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$root"
repair=0
force_cpu=0
for argument in "$@"; do
  case "$argument" in
    --repair) repair=1 ;;
    --cpu) force_cpu=1 ;;
    *) echo "Unknown option: ${argument}"; exit 2 ;;
  esac
done

# The Python build this package runs on. downloads.json says the same, for people reading; a test keeps them equal.
python_filename="cpython-3.12.14-x86_64-unknown-linux-gnu.tar.gz"
python_sha256="936c246dfdbbfa7cb22dd01814a21f582a892689fae96b06071a5e433baffa22"
python_url="https://github.com/astral-sh/python-build-standalone/releases/download/20260901/cpython-3.12.14+20260901-x86_64-unknown-linux-gnu-install_only.tar.gz"

arch="$(uname -m)"
if [ "$arch" != x86_64 ]; then
  echo "This package needs a 64-bit Intel or AMD PC (found ${arch})."
  exit 1
fi

# The libraries are built for the GNU C library 2.28 or newer: Ubuntu 20.04, Debian 10, Fedora 29 and later.
libc="$(getconf GNU_LIBC_VERSION 2>/dev/null | awk '{print $2}')"
libc_minor="${libc#*.}"
if [ -z "$libc" ] || [ "${libc%%.*}" -lt 2 ] || { [ "${libc%%.*}" -eq 2 ] && [ "${libc_minor%%.*}" -lt 28 ]; }; then
  echo "Skydive Cutter needs a Linux with the GNU C library 2.28 or newer (found ${libc:-none})."
  echo "Ubuntu 20.04, Debian 10, Fedora 29 and anything later have it."
  exit 1
fi

for tool in curl tar sha256sum; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    echo "Setup needs the '${tool}' program, which this system does not have. Install it with your package manager"
    echo "(for example: sudo apt install ${tool}), then run setup again."
    exit 1
  fi
done

mkdir -p .downloads cache logs bin
log="logs/setup-$(date +%Y%m%d-%H%M%S).log"
exec > >(tee -a "$log") 2>&1

echo
echo "Skydive Cutter: $([ $repair = 1 ] && echo 'repairing this install' || echo 'one-time setup')"
echo "Install folder: ${root}"
echo "This PC: ${arch}, GNU C library ${libc}"
echo "Downloads Python, the model libraries, the person detector and FFmpeg into this folder."
echo "The person detector is Ultralytics YOLO, licensed under AGPL-3.0 and downloaded from PyPI:"
echo "  https://github.com/ultralytics/ultralytics/blob/main/LICENSE"
echo "No root password, no system Python, nothing outside this folder."
echo

# PyTorch for Linux carries NVIDIA's libraries with it, so one install serves a PC with an NVIDIA card and one
# without. That makes it large. The figure is an estimate with margin for the downloads and for unpacking them.
required_gb=16
free_kb="$(df -Pk "$root" | awk 'NR==2 {print $4}')"
if [ "${free_kb:-0}" -lt $((required_gb * 1024 * 1024)) ]; then
  echo "Please free at least ${required_gb} GB on this drive before setup (about $((free_kb / 1024 / 1024)) GB is free)."
  exit 1
fi

need() {  # need <filename> <sha256> <url> [<url> ...]  -> path; tries each address until one gives the right file
  local filename="$1"
  local want="$2"
  shift 2
  local target=".downloads/${filename}"
  if [ -f "$target" ] && [ "$(sha256sum "$target" | cut -d' ' -f1)" = "$want" ]; then
    echo "$target"; return
  fi
  rm -f "$target"
  local url
  for url in "$@"; do
    echo "Downloading ${filename} from ${url%/*}..." >&2
    if curl -fSL --retry 3 --connect-timeout 30 -o "${target}.part" "$url" &&
       [ "$(sha256sum "${target}.part" | cut -d' ' -f1)" = "$want" ]; then
      mv "${target}.part" "$target"
      echo "$target"
      return
    fi
    rm -f "${target}.part"
    echo "That copy of ${filename} could not be downloaded or did not match its checksum." >&2
  done
  echo "Every source for ${filename} failed. Check the internet connection and run setup again." >&2
  exit 1
}

# --- Python ------------------------------------------------------------------------------------------------
runtime=".runtime"
python="${runtime}/python/bin/python3"
if [ $repair = 1 ] || [ ! -x "$python" ]; then
  archive="$(need "$python_filename" "$python_sha256" "$python_url")"
  rm -rf "$runtime"
  mkdir -p "$runtime"
  tar -xzf "$archive" -C "$runtime"
fi
[ -x "$python" ] || { echo "The Python runtime did not unpack as expected."; exit 1; }
echo "Python: $("$python" -V)"

python_field() {
  "$python" -c '
import json, sys
value = json.load(open("downloads.json"))
for key in sys.argv[1].split("."):
    value = value[int(key)] if isinstance(value, list) else value[key]
print(" ".join(value) if isinstance(value, list) else value)
' "$1"
}

# --- the libraries -----------------------------------------------------------------------------------------
# One lock lists every package with its checksum. Wheels only: nothing is compiled here.
export PIP_CACHE_DIR="${root}/cache/pip"
export PYTHONDONTWRITEBYTECODE=1
requirements=requirements-linux-x86_64.txt
pip_flags=(--disable-pip-version-check --no-warn-script-location --only-binary=:all: --require-hashes --no-deps
           --index-url https://pypi.org/simple)
[ $repair = 1 ] && pip_flags+=(--force-reinstall)
echo "Installing the model libraries from ${requirements}: a large download the first time."
"$python" -m pip install "${pip_flags[@]}" -r "$requirements"
"$python" -m pip check

# --- FFmpeg ------------------------------------------------------------------------------------------------
# Which FFmpeg this PC gets, best first:
#   1. the one already in this folder, when it is good enough;
#   2. the one already installed on this system, when it is new enough and has the x264 encoder;
#   3. the static build from BtbN/FFmpeg-Builds, the Linux build ffmpeg.org links to.
# A newer FFmpeg is fine (the app uses long-standing options only), so any copy that runs and reports at least this
# version is accepted.
ffmpeg_minimum=7

usable_tool() {  # usable_tool <program> <name> <minimum major version>  -> succeeds when it runs and is new enough
  local program="$1"
  local name="$2"
  local minimum="$3"
  local first
  first="$("$program" -version 2>/dev/null | sed -n '1p')" || return 1
  case "$first" in
    "${name} version "*) ;;
    *) return 1 ;;
  esac
  local version="${first#"${name} version "}"
  version="${version#n}"
  local major="${version%%[!0-9]*}"
  # A build from FFmpeg's development branch names a commit instead of a version: accept it, it is newer still.
  [ -z "$major" ] && return 0
  [ "$major" -ge "$minimum" ]
}

capable_ffmpeg() {  # capable_ffmpeg <ffmpeg>  -> succeeds when it has the encoder the app uses
  # Read into a variable first: with pipefail, a grep that stops reading early would make a good FFmpeg look bad.
  local encoders
  encoders="$("$1" -hide_banner -encoders 2>/dev/null)" || return 1
  case "$encoders" in
    *libx264*) return 0 ;;
  esac
  return 1
}

good_pair() {  # good_pair <folder>  -> succeeds when its ffmpeg and ffprobe are both good enough
  usable_tool "$1/ffmpeg" ffmpeg "$ffmpeg_minimum" || return 1
  usable_tool "$1/ffprobe" ffprobe "$ffmpeg_minimum" || return 1
  capable_ffmpeg "$1/ffmpeg"
}

system_folder() {  # prints the folder holding this system's own FFmpeg, when it has a good one
  local found
  found="$(command -v ffmpeg 2>/dev/null)" || return 1
  found="$(dirname "$found")"
  case "$found" in
    "${root}/bin") return 1 ;;
  esac
  if [ -x "${found}/ffprobe" ] && good_pair "$found"; then
    echo "$found"
    return 0
  fi
  return 1
}

ffmpeg_from=""
if [ $repair = 0 ] && [ -x bin/ffmpeg ] && [ -x bin/ffprobe ] && good_pair bin; then
  ffmpeg_from="already in this folder"
fi
if [ -z "$ffmpeg_from" ] && system_bin="$(system_folder)"; then
  # Linked, not copied: it stays current when the system updates it. If it is ever removed the link stops working,
  # and the launcher runs this setup again.
  rm -f bin/ffmpeg bin/ffprobe
  ln -s "${system_bin}/ffmpeg" bin/ffmpeg
  ln -s "${system_bin}/ffprobe" bin/ffprobe
  ffmpeg_from="this system's own, in ${system_bin}"
fi
if [ -z "$ffmpeg_from" ]; then
  filename="$(python_field "ffmpeg.x86_64.filename")"
  urls="$(python_field "ffmpeg.x86_64.urls")"
  for url in $urls; do
    archive=".downloads/${filename}"
    rm -f "$archive"
    echo "Downloading ${filename} from ${url%/*}..."
    curl -fSL --retry 3 --connect-timeout 30 -o "${archive}.part" "$url" || { rm -f "${archive}.part"; continue; }
    mv "${archive}.part" "$archive"
    rm -rf .downloads/ffmpeg-unpacked
    mkdir -p .downloads/ffmpeg-unpacked
    # Python unpacks it: its tar module reads .tar.xz itself, so the system needs no xz program.
    "$python" -c 'import sys, tarfile; tarfile.open(sys.argv[1]).extractall(sys.argv[2], filter="data")' \
      "$archive" .downloads/ffmpeg-unpacked || { rm -f "$archive"; continue; }
    found_ffmpeg="$(find .downloads/ffmpeg-unpacked -type f -name ffmpeg -print -quit)"
    found_ffprobe="$(find .downloads/ffmpeg-unpacked -type f -name ffprobe -print -quit)"
    if [ -z "$found_ffmpeg" ] || [ -z "$found_ffprobe" ]; then
      echo "${filename} did not contain ffmpeg and ffprobe."
      continue
    fi
    chmod +x "$found_ffmpeg" "$found_ffprobe"
    if good_pair "$(dirname "$found_ffmpeg")"; then
      rm -f bin/ffmpeg bin/ffprobe
      cp "$found_ffmpeg" bin/ffmpeg
      cp "$found_ffprobe" bin/ffprobe
      ffmpeg_from="the static build from BtbN/FFmpeg-Builds"
      break
    fi
    echo "That copy of FFmpeg does not run on this PC, or is older than version ${ffmpeg_minimum}."
    rm -f "$archive"
  done
  rm -rf .downloads/ffmpeg-unpacked
fi
if [ -z "$ffmpeg_from" ]; then
  echo "Could not get a working FFmpeg from any source; nothing was installed for it. Check the internet connection"
  echo "and run setup again, or install FFmpeg ${ffmpeg_minimum} or newer with your package manager."
  exit 1
fi
echo "FFmpeg: $(bin/ffmpeg -version 2>&1 | sed -n '1p')"
echo "FFmpeg is ${ffmpeg_from}."

# --- the person detector's model ------------------------------------------------------------------------------
weights="yolo11n.pt"
want="$(python_field "people.sha256")"
if [ ! -f "$weights" ] || [ "$(sha256sum "$weights" | cut -d' ' -f1)" != "$want" ]; then
  archive="$(need "$weights" "$want" $(python_field "people.urls"))"
  cp "$archive" "$weights"
fi
# Ultralytics sends anonymous usage statistics unless told not to.
export YOLO_CONFIG_DIR="${root}/cache/ultralytics"
"$python" -c 'from ultralytics import settings; settings.update({"sync": False})' >/dev/null 2>&1 || true

# --- prove it works ------------------------------------------------------------------------------------------
device="cpu"
if [ $force_cpu = 0 ] && "$python" -c 'import sys, torch; sys.exit(0 if torch.cuda.is_available() else 1)' 2>/dev/null; then
  device="cuda"
fi
echo "Checking the install on: $([ "$device" = cuda ] && echo 'the NVIDIA GPU' || echo 'the processor')"
"$python" -s -B verify_install.py --device "$device"

"$python" - "$arch" "$device" "$ffmpeg_from" <<'PYTHON'
import json, sys, time
arch, device, ffmpeg_from = sys.argv[1], sys.argv[2], sys.argv[3]
json.dump({'schema_version': 1, 'profile': f'linux-{arch}', 'python': '.runtime/python/bin/python3',
           'device': device, 'ffmpeg': ffmpeg_from, 'installed_at': time.strftime('%Y-%m-%dT%H:%M:%S')},
          open('installation.json', 'w'), indent=1)
PYTHON
"$python" -m pip freeze > "logs/installed-linux-${arch}.txt"

# The window itself needs a few system libraries that a desktop Linux normally has and a bare server does not.
missing_libraries=""
for library in libxcb-cursor.so.0 libxkbcommon-x11.so.0 libEGL.so.1 libGL.so.1 libfontconfig.so.1 libdbus-1.so.3; do
  if ! ldconfig -p 2>/dev/null | grep -q "$library"; then missing_libraries="${missing_libraries} ${library}"; fi
done
if [ -n "$missing_libraries" ]; then
  echo
  echo "The app's window may not open: these system libraries were not found:${missing_libraries}"
  echo "On Ubuntu or Debian:  sudo apt install libxcb-cursor0 libxkbcommon-x11-0 libegl1 libgl1 libfontconfig1 libdbus-1-3"
  echo "On Fedora:            sudo dnf install xcb-util-cursor libxkbcommon-x11 mesa-libEGL mesa-libGL fontconfig dbus-libs"
fi

echo
echo "Setup passed. Skydive Cutter opens next."
