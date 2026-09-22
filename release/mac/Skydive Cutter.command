#!/bin/bash
# Double-click this. It opens a Terminal window, installs anything missing the first time, then starts the app.
# The scripts it calls run through bash, so only this file needs to be executable.
cd "$(dirname "${BASH_SOURCE[0]}")"
/bin/bash ./skydive-cutter.sh "$@"
