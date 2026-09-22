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
pip_flags=(--disable-pip-version-check --no-warn-script-location --only-binary=:all: --require-hashes --no-deps)
[ $repair = 1 ] && pip_flags+=(--force-reinstall)
echo "Installing the model libraries from ${requirements}: a large download the first time."
"$python" -m pip install "${pip_flags[@]}" -r "$requirements"
"$python" -m pip check

# --- FFmpeg ------------------------------------------------------------------------------------------------
# osxexperts.net replaces these files in place whenever FFmpeg updates, so there is no fixed checksum to hold them to.
# A newer FFmpeg is fine (the app uses long-standing options only), so setup accepts any copy that runs on this Mac and
# reports at least this version.
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

for tool in ffmpeg ffprobe; do
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
echo "FFmpeg: $(bin/ffmpeg -version 2>&1 | sed -n '1p')"

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

"$python" - "$arch" "$device" <<'PYTHON'
import json, sys, time
arch, device = sys.argv[1], sys.argv[2]
json.dump({'schema_version': 1, 'profile': f'macos-{arch}', 'python': f'.runtime/{arch}/python/bin/python3',
           'device': device, 'installed_at': time.strftime('%Y-%m-%dT%H:%M:%S')},
          open('installation.json', 'w'), indent=1)
PYTHON
"$python" -m pip freeze > "logs/installed-macos-${arch}.txt"

echo
echo "Setup passed. Skydive Cutter opens next."
