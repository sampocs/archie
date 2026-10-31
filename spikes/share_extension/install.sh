#!/bin/sh
# Installs the already-built Release app on the first connected iPhone (phone unlocked, cable plugged in)
set -e
cd "$(dirname "$0")"
DEVICE=$(xcrun devicectl list devices | grep iPhone | grep -E "connected|available" | grep -oE "[0-9A-F]{8}-([0-9A-F]{4}-){3}[0-9A-F]{12}" | head -1)
if [ -z "$DEVICE" ]; then
  echo "No available iPhone found. Unlock it, plug it in, and trust this Mac." >&2
  exit 1
fi
xcrun devicectl device install app --device "$DEVICE" ios/build/Build/Products/Release-iphoneos/CarlShareSpike.app
