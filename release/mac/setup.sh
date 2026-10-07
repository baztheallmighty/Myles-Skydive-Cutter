#!/bin/bash
# Installs everything Skydive Cutter needs into this folder: Python, the model libraries, the person detector and
# FFmpeg. Nothing is installed anywhere else on the Mac, and deleting this folder removes all of it.
#
#   ./setup.sh              install what is missing
#   ./setup.sh --repair     install it again, over the top (close Skydive Cutter first)
#   ./setup.sh --cpu        use the processor even on a Mac that has a usable GPU
#
# Written for the Bash 3.2 that macOS ships: no associative arrays, and every variable next to text is braced.
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

arch="$(uname -m)"
case "$arch" in
  arm64) ;;
  x86_64) ;;
  *) echo "This package needs an Apple Silicon or Intel Mac (found ${arch})."; exit 1 ;;
esac

# The libraries publish macOS 13 builds and nothing older (OpenCV sets the floor), so say so before downloading.
macos="$(sw_vers -productVersion 2>/dev/null || echo 0)"
if [ "${macos%%.*}" -lt 13 ] 2>/dev/null; then
  echo "Skydive Cutter needs macOS 13 (Ventura) or newer. This Mac has macOS ${macos}."
  echo "Apple menu > System Settings > General > Software Update may offer a newer macOS for this Mac."
  exit 1
fi

mkdir -p .downloads cache logs bin
log="logs/setup-$(date +%Y%m%d-%H%M%S).log"
exec > >(tee -a "$log") 2>&1

echo
echo "Skydive Cutter: $([ $repair = 1 ] && echo 'repairing this install' || echo 'one-time setup')"
echo "Install folder: ${root}"
echo "This Mac: ${arch}, macOS ${macos}"
echo "Downloads Python, the model libraries, the person detector and FFmpeg into this folder."
echo "The person detector is Ultralytics YOLO, licensed under AGPL-3.0 and downloaded from PyPI:"
echo "  https://github.com/ultralytics/ultralytics/blob/main/LICENSE"
echo "No administrator password, no system Python, nothing outside this folder."
echo

# The libraries, pip's copy of their downloads, and room to unpack them. A Mac gets no CUDA build, so this is a
# fraction of Windows' 10 GB. 6 GB is an estimate with margin until an install has been measured (see mac-install.yml).
required_gb=6
free_kb="$(df -Pk "$root" | awk 'NR==2 {print $4}')"
if [ "${free_kb:-0}" -lt $((required_gb * 1024 * 1024)) ]; then
  echo "Please free at least ${required_gb} GB on this drive before setup (about $((free_kb / 1024 / 1024)) GB is free)."
  exit 1
fi

bootstrap_field() {
  # plutil ships with macOS.  /usr/bin/python3 is only an Xcode stub on a clean Mac and opens the developer-tools
  # installer, so it cannot be used to discover the bundled Python download.
  /usr/bin/plutil -extract "$1" raw -o - downloads.json
}

need() {  # need <filename> <sha256> <url> [<url> ...]  -> path; tries each address until one gives the right file
  # Keep declarations separate for the Bash 3.2 supplied with macOS.
  local filename="$1"
  local want="$2"
  shift 2
  local target=".downloads/${filename}"
  if [ -f "$target" ] && [ "$(shasum -a 256 "$target" | cut -d' ' -f1)" = "$want" ]; then
    echo "$target"; return
  fi
  rm -f "$target"
  local url
  for url in "$@"; do
    echo "Downloading ${filename} from ${url%/*}..." >&2
    if curl -fSL --retry 3 --connect-timeout 30 -o "${target}.part" "$url" &&
       [ "$(shasum -a 256 "${target}.part" | cut -d' ' -f1)" = "$want" ]; then
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
runtime=".runtime/${arch}"
python="${runtime}/python/bin/python3"
if [ $repair = 1 ] || [ ! -x "$python" ]; then
  filename="$(bootstrap_field "python.${arch}.filename")"
  sha="$(bootstrap_field "python.${arch}.sha256")"
  python_urls=()
  index=0
  while url="$(bootstrap_field "python.${arch}.urls.${index}" 2>/dev/null)"; do
    python_urls+=("$url")
    index=$((index + 1))
  done
  [ ${#python_urls[@]} -gt 0 ] || { echo "downloads.json lists no address for Python."; exit 1; }
  archive="$(need "$filename" "$sha" "${python_urls[@]}")"
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
# One lock per kind of Mac lists every package with its checksum. Wheels only: building anything from source here
# would need Apple's developer tools, which a clean Mac does not have.
export PIP_CACHE_DIR="${root}/cache/pip"
export PYTHONDONTWRITEBYTECODE=1
device="$(python_field "torch.${arch}.device")"
[ $force_cpu = 1 ] && device="cpu"
requirements=requirements-mac-arm64.txt
if [ "$arch" = x86_64 ]; then requirements=requirements-mac-intel.txt; fi
pip_flags=(--disable-pip-version-check --no-warn-script-location --only-binary=:all: --require-hashes --no-deps
           --index-url https://pypi.org/simple)
[ $repair = 1 ] && pip_flags+=(--force-reinstall)
echo "Installing the model libraries from ${requirements}: a large download the first time."
"$python" -m pip install "${pip_flags[@]}" -r "$requirements"
"$python" -m pip check

# --- FFmpeg ------------------------------------------------------------------------------------------------
# Which FFmpeg a Mac gets, best first:
#   1. the one already in this folder, when it is the right kind for this Mac;
#   2. Homebrew's, when Homebrew is installed and has one: built from FFmpeg's own source, and native on any Mac;
#   3. on Apple Silicon, a native build from ffmpeg.martin-riedl.de, pinned by checksum;
#   4. the Intel build from evermeet.cx, the macOS build site ffmpeg.org links to. An Intel Mac runs it as it is; an
#      Apple Silicon Mac runs it through Rosetta 2, which works but is slower, so it is the last resort there.
# A newer FFmpeg is fine (the app uses long-standing options only), so any copy that runs on this Mac and reports at
# least this version is accepted.
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

native_program() {  # native_program <program>  -> fails only for an Intel program on an Apple Silicon Mac
  if [ "$arch" != arm64 ]; then return 0; fi
  case "$(/usr/bin/file -L "$1" 2>/dev/null)" in
    *arm64*) return 0 ;;
  esac
  return 1
}

capable_ffmpeg() {  # capable_ffmpeg <ffmpeg>  -> succeeds when it has the encoder and the Apple decoder the app uses
  # Read into a variable first: with pipefail, a grep that stops reading early would make a good FFmpeg look bad.
  local encoders
  local decoders
  encoders="$("$1" -hide_banner -encoders 2>/dev/null)" || return 1
  decoders="$("$1" -hide_banner -hwaccels 2>/dev/null)" || return 1
  case "$encoders" in
    *libx264*) ;;
    *) return 1 ;;
  esac
  case "$decoders" in
    *videotoolbox*) return 0 ;;
  esac
  return 1
}

good_pair() {  # good_pair <folder>  -> succeeds when its ffmpeg and ffprobe are both the right kind for this Mac
  usable_tool "$1/ffmpeg" ffmpeg "$ffmpeg_minimum" || return 1
  usable_tool "$1/ffprobe" ffprobe "$ffmpeg_minimum" || return 1
  native_program "$1/ffmpeg" || return 1
  native_program "$1/ffprobe" || return 1
  capable_ffmpeg "$1/ffmpeg"
}

homebrew_folder() {  # prints the folder holding Homebrew's FFmpeg when Homebrew is installed and has a good one
  local prefix
  for prefix in "$(brew --prefix 2>/dev/null || true)" /opt/homebrew /usr/local; do
    if [ -z "$prefix" ] || [ ! -d "${prefix}/Cellar" ]; then continue; fi
    if [ -x "${prefix}/bin/ffmpeg" ] && [ -x "${prefix}/bin/ffprobe" ] && good_pair "${prefix}/bin"; then
      echo "${prefix}/bin"
      return 0
    fi
  done
  return 1
}

native_pair() {  # downloads the native Apple Silicon FFmpeg into .downloads/native; succeeds when both are good
  local tool
  local archive
  local binary
  rm -rf .downloads/native
  mkdir -p .downloads/native
  for tool in ffmpeg ffprobe; do
    # need stops its own subshell when every address fails, which here means "try the next kind", not "stop setup".
    archive="$(need "$(python_field "ffmpeg.native_arm64.${tool}.filename")" \
                    "$(python_field "ffmpeg.native_arm64.${tool}.sha256")" \
                    $(python_field "ffmpeg.native_arm64.${tool}.urls"))" || return 1
    /usr/bin/unzip -q -o "$archive" -d ".downloads/native/${tool}-unpacked" || return 1
    binary="$(find ".downloads/native/${tool}-unpacked" -type f -name "$tool" -print -quit)"
    if [ -z "$binary" ]; then return 1; fi
    chmod +x "$binary"
    xattr -d com.apple.quarantine "$binary" 2>/dev/null || true
    cp "$binary" ".downloads/native/${tool}"
  done
  good_pair .downloads/native
}

rosetta_ready() {
  arch -x86_64 /usr/bin/true 2>/dev/null
}

ffmpeg_from=""
if [ $repair = 0 ] && [ -x bin/ffmpeg ] && [ -x bin/ffprobe ] && good_pair bin; then
  ffmpeg_from="already in this folder"
fi
if [ -z "$ffmpeg_from" ] && brew_bin="$(homebrew_folder)"; then
  # Linked, not copied: Homebrew's FFmpeg loads other Homebrew packages, and stays current when Homebrew updates it.
  # If Homebrew's copy is ever removed the link stops working, and the launcher runs this setup again.
  rm -f bin/ffmpeg bin/ffprobe
  ln -s "${brew_bin}/ffmpeg" bin/ffmpeg
  ln -s "${brew_bin}/ffprobe" bin/ffprobe
  ffmpeg_from="Homebrew, in ${brew_bin}"
fi
if [ -z "$ffmpeg_from" ] && [ "$arch" = arm64 ]; then
  echo "Getting FFmpeg built for Apple Silicon."
  if native_pair; then
    rm -f bin/ffmpeg bin/ffprobe
    cp .downloads/native/ffmpeg bin/ffmpeg
    cp .downloads/native/ffprobe bin/ffprobe
    ffmpeg_from="the Apple Silicon build from ffmpeg.martin-riedl.de"
  else
    echo "The Apple Silicon build of FFmpeg could not be downloaded or does not run here."
    echo "Using the Intel build instead. It works through Apple's Rosetta 2, only more slowly."
  fi
  rm -rf .downloads/native
fi
if [ -z "$ffmpeg_from" ] && [ "$arch" = arm64 ] && ! rosetta_ready; then
  echo "The Intel build of FFmpeg needs Apple's Rosetta 2, and it is not installed yet."
  echo "Install it by pasting this into Terminal and pressing Return (macOS may ask for your password):"
  echo "  softwareupdate --install-rosetta"
  echo "Then run setup again."
  exit 1
fi

for tool in ffmpeg ffprobe; do
  if [ -n "$ffmpeg_from" ]; then break; fi
  if [ $repair = 0 ] && [ -x "bin/${tool}" ] && usable_tool "bin/${tool}" "$tool" "$ffmpeg_minimum"; then continue; fi
  filename="$(python_field "ffmpeg.${arch}.${tool}.filename")"
  urls="$(python_field "ffmpeg.${arch}.${tool}.urls")"
  installed=0
  for url in $urls; do
    archive=".downloads/${filename}"
    rm -f "$archive"
    echo "Downloading ${filename} from ${url%/*}..."
    curl -fSL --retry 3 --connect-timeout 30 -o "${archive}.part" "$url" || { rm -f "${archive}.part"; continue; }
    mv "${archive}.part" "$archive"
    rm -rf ".downloads/${tool}-unpacked"
    mkdir -p ".downloads/${tool}-unpacked"
    /usr/bin/unzip -q -o "$archive" -d ".downloads/${tool}-unpacked" || { rm -f "$archive"; continue; }
    binary="$(find ".downloads/${tool}-unpacked" -type f -name "$tool" -print -quit)"
    [ -n "$binary" ] || { echo "${filename} did not contain ${tool}."; continue; }
    chmod +x "$binary"
    xattr -d com.apple.quarantine "$binary" 2>/dev/null || true
    if usable_tool "$binary" "$tool" "$ffmpeg_minimum"; then
      cp "$binary" "bin/${tool}"
      installed=1
      break
    fi
    echo "That copy of ${tool} does not run on this Mac, or is older than version ${ffmpeg_minimum}."
    rm -f "$archive"
  done
  rm -rf ".downloads/${tool}-unpacked"
  if [ $installed = 0 ]; then
    echo "Could not get a working ${tool} from any source; nothing was installed. Check the internet connection and"
    echo "run setup again."
    exit 1
  fi
done
if [ -z "$ffmpeg_from" ]; then
  ffmpeg_from="the Intel build from evermeet.cx$([ "$arch" = arm64 ] && echo ', through Rosetta 2' || true)"
fi
echo "FFmpeg: $(bin/ffmpeg -version 2>&1 | sed -n '1p')"
echo "FFmpeg is ${ffmpeg_from}."

# --- the person detector's model ------------------------------------------------------------------------------
weights="yolo11n.pt"
want="$(python_field "people.sha256")"
if [ ! -f "$weights" ] || [ "$(shasum -a 256 "$weights" | cut -d' ' -f1)" != "$want" ]; then
  archive="$(need "$weights" "$want" $(python_field "people.urls"))"
  cp "$archive" "$weights"
fi
# Ultralytics sends anonymous usage statistics unless told not to; Skydive Cutter stays offline.
export YOLO_CONFIG_DIR="${root}/cache/ultralytics"
"$python" -c 'from ultralytics import settings; settings.update({"sync": False})' >/dev/null 2>&1 || true

# --- prove it works ------------------------------------------------------------------------------------------
"$python" -s -B verify_install.py --device "$device"

"$python" - "$arch" "$device" "$ffmpeg_from" <<'PYTHON'
import json, sys, time
arch, device, ffmpeg_from = sys.argv[1], sys.argv[2], sys.argv[3]
json.dump({'schema_version': 1, 'profile': f'macos-{arch}', 'python': f'.runtime/{arch}/python/bin/python3',
           'device': device, 'ffmpeg': ffmpeg_from, 'installed_at': time.strftime('%Y-%m-%dT%H:%M:%S')},
          open('installation.json', 'w'), indent=1)
PYTHON
"$python" -m pip freeze > "logs/installed-macos-${arch}.txt"

echo
echo "Setup passed. Skydive Cutter opens next."
