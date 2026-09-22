#!/bin/bash
# Opened by Skydive Cutter's "Install" button in a Terminal window of its own, so the download can be watched.
# It fills in what is missing and never reinstalls over the top: the app is running from what is already here.
# The app waits for logs/.install-status, then checks the install again.
cd "$(dirname "${BASH_SOURCE[0]}")"
mkdir -p logs
status="logs/.install-status"
code=0
trap 'echo 129 > "$status"; exit 129' HUP
/bin/bash ./setup.sh || code=$?
echo "$code" > "$status"
echo
if [ "$code" = 0 ]; then
  echo "Done. Skydive Cutter carries on by itself; you can close this window."
else
  echo "Setup stopped (code ${code}). Read the message above, or the newest setup log in the logs folder."
fi
