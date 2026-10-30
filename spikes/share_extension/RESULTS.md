# Spike: iOS share extension (2026-10-29)

A bare Expo SDK 54 app with an `expo-share-extension` share sheet. It shows exactly what each app hands over, checks that the extension can reach the network, and saves each share into the main app's list through a deep link.

## Install

1. Unlock the iPhone, plug it in, and trust the Mac if asked.
2. Run `spikes/share_extension/install.sh`.
3. The first time, approve the developer under iPhone Settings → General → VPN & Device Management.

To rebuild after code changes, run this from `ios/`:

```
xcodebuild -workspace CarlShareSpike.xcworkspace -scheme CarlShareSpike -configuration Release \
  -destination "generic/platform=iOS" -derivedDataPath build -allowProvisioningUpdates \
  DEVELOPMENT_TEAM=3W3H65F89G CODE_SIGN_STYLE=Automatic build
```

Running `expo prebuild --clean` regenerates `ios/` and re-adds the App Group entitlement. I removed it by hand because Apple's side doesn't have the group enabled for the extension's App ID, and links and text don't need it. The real app will need the App Group turned on once in Xcode, under the extension target's Signing & Capabilities.

## Test checklist

Share each of these with **Carl Share Spike** (it may be under "More" in the share sheet the first time), note what the sheet shows, then tap **Save to app**:

| Source | What to share | url / text received | Network check | Notes |
|---|---|---|---|---|
| Spotify | a podcast episode | | | |
| Apple Podcasts | an episode | | | |
| X | a post | | | |
| YouTube | a video | | | |
| Safari | an article | | | |
| Safari | selected text | | | |
| A paywalled article (e.g. Bloomberg) | | | | |

Questions this answers:
- Does each app give us a URL, or only text with the link inside it?
- Can the extension fetch pages? This decides whether it can call our backend directly.
- Does "Save to app" open the main app with the record intact?
