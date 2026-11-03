#!/usr/bin/env bash
# Builds the Release app against the deployed API and installs it on the first connected iPhone.
# The phone must be unlocked and paired with this Mac (cable, or the same Wi-Fi once paired).
# Usage: scripts/install_ios.sh [api-url]   (defaults to the Railway production domain)
set -euo pipefail

API_URL="${1:-https://archie-production-4856.up.railway.app}"
TEAM_ID="3W3H65F89G"
APP_PATH="ios/build/Build/Products/Release-iphoneos/Archie.app"

cd "$(dirname "$0")/../app"

# Find the phone first, so a missing device fails before a multi-minute build.
DEVICE=$(xcrun devicectl list devices | grep iPhone | grep -E "connected|available" \
  | grep -oE "[0-9A-F]{8}-([0-9A-F]{4}-){3}[0-9A-F]{12}" | head -1 || true)
if [ -z "$DEVICE" ]; then
  echo "No available iPhone found. Unlock it, plug it in, and trust this Mac." >&2
  exit 1
fi

# The API URL is baked into the native project's config at prebuild time (app.config.ts reads it into extra.apiUrl).
EXPO_PUBLIC_API_URL="$API_URL" npx expo prebuild --platform ios --clean

EXPO_PUBLIC_API_URL="$API_URL" xcodebuild \
  -workspace ios/Archie.xcworkspace \
  -scheme Archie \
  -configuration Release \
  -destination "generic/platform=iOS" \
  -derivedDataPath ios/build \
  -allowProvisioningUpdates \
  DEVELOPMENT_TEAM="$TEAM_ID" \
  | tail -20

xcrun devicectl device install app --device "$DEVICE" "$APP_PATH"
echo "Installed Archie (API: $API_URL) on $DEVICE"
