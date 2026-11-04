const { withFinalizedMod } = require("expo/config-plugins");
const fs = require("fs");
const path = require("path");

const CONTROLLER_FILE = "ShareExtensionViewController.swift";
const SCREEN_FRAME = "frame = screenBounds";
const VIEW_FRAME = "frame = view.bounds";

// expo-share-extension sizes the React root view to the whole screen, but iOS presents the extension as a sheet
// that starts below the status bar, so the bottom of the layout (the Cancel button) ends up off screen. Sizing it
// to the controller's own view, with the flexible autoresizing mask the library already sets, keeps it inside the
// sheet. Finalized so it runs after expo-share-extension has written the controller.
function withShareSheetFrame(config) {
  return withFinalizedMod(config, [
    "ios",
    (mod) => {
      const { platformProjectRoot } = mod.modRequest;
      const shareExtensionName = fs
        .readdirSync(platformProjectRoot)
        .find((entry) => entry.endsWith("ShareExtension") && fs.statSync(path.join(platformProjectRoot, entry)).isDirectory());
      if (!shareExtensionName) throw new Error("withShareSheetFrame: share extension target not found");

      const controllerPath = path.join(platformProjectRoot, shareExtensionName, CONTROLLER_FILE);
      const source = fs.readFileSync(controllerPath, "utf8");
      if (!source.includes(SCREEN_FRAME)) throw new Error(`withShareSheetFrame: "${SCREEN_FRAME}" not in ${CONTROLLER_FILE}`);
      fs.writeFileSync(controllerPath, source.replace(SCREEN_FRAME, VIEW_FRAME));
      return mod;
    },
  ]);
}

module.exports = withShareSheetFrame;
