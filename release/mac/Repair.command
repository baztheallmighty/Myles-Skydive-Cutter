#!/bin/bash
# Double-click this, with Skydive Cutter closed, to install everything again over the top of what is there.
cd "$(dirname "${BASH_SOURCE[0]}")"
/bin/bash ./skydive-cutter.sh --repair
echo
read -n 1 -s -r -p "Press any key to close."
