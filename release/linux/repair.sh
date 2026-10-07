#!/bin/bash
# Run this, with Skydive Cutter closed, to install everything again over the top of what is there.
cd "$(dirname "${BASH_SOURCE[0]}")"
/bin/bash ./skydive-cutter.sh --repair
