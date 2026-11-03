const { withFinalizedMod, withXcodeProject } = require("expo/config-plugins");
const plist = require("@expo/plist").default;
const fs = require("fs");
const path = require("path");

const KEYCHAIN_GROUPS = ["$(AppIdentifierPrefix)com.sampocs.archie.shared"];
const APP_GROUPS_KEY = "com.apple.security.application-groups";

// Gives the app and the share extension one Keychain access group (so the extension can read the session key)
// and removes the App Group entitlement expo-share-extension adds: the Apple portal has no App Group for the
// extension's App ID, so automatic signing fails with it, and nothing here needs a shared container.
//
// Both .entitlements files are edited in a finalized mod. expo-share-extension adds the App Group from its own
// entitlements mod and writes the extension's file from inside it, and mods run last-registered first, so a
// `withEntitlementsPlist` here (or a dangerous mod, which runs before the file exists) would run too early and
// have its edit undone or find nothing.
function withSharedKeychain(config) {
  return withExtensionDeploymentTarget(withSharedKeychainEntitlements(config));
}

function withSharedKeychainEntitlements(config) {
  return withFinalizedMod(config, [
    "ios",
    (mod) => {
      const { platformProjectRoot, projectName } = mod.modRequest;
      const shareExtensionName = fs
        .readdirSync(platformProjectRoot)
        .find((entry) => entry.endsWith("ShareExtension") && fs.statSync(path.join(platformProjectRoot, entry)).isDirectory());
      if (!shareExtensionName) throw new Error("withSharedKeychain: share extension target not found");

      useSharedKeychain(path.join(platformProjectRoot, projectName, `${projectName}.entitlements`));
      useSharedKeychain(path.join(platformProjectRoot, shareExtensionName, `${shareExtensionName}.entitlements`));
      return mod;
    },
  ]);
}

function useSharedKeychain(entitlementsFile) {
  const entitlements = plist.parse(fs.readFileSync(entitlementsFile, "utf8"));
  entitlements["keychain-access-groups"] = KEYCHAIN_GROUPS;
  delete entitlements[APP_GROUPS_KEY];
  fs.writeFileSync(entitlementsFile, plist.build(entitlements));
}

// expo-share-extension hardcodes iOS 15.1 for the extension, but the pods it links (ExpoDomWebView) need the app's
// 16.4, and the extension's Swift module provider then fails to compile. This mod only sees the extension target
// if it runs after expo-share-extension's, which mods do when the plugin is listed BEFORE it (mods run
// last-listed first), so app.config.ts lists this plugin first.
function withExtensionDeploymentTarget(config) {
  return withXcodeProject(config, (mod) => {
    const configurations = mod.modResults.pbxXCBuildConfigurationSection();
    for (const entry of Object.values(configurations)) {
      const settings = entry.buildSettings;
      if (settings?.INFOPLIST_FILE?.includes("ShareExtension")) settings.IPHONEOS_DEPLOYMENT_TARGET = "16.4";
    }
    return mod;
  });
}

module.exports = withSharedKeychain;
