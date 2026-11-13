/** @type {import('@bacons/apple-targets/app.plugin').Config} */
module.exports = {
  type: "widget",
  name: "widget",
  displayName: "Archie",
  bundleIdentifier: ".widget",
  deploymentTarget: "16.4",
  // Only the shared Keychain group: the Apple portal has no App Group for these App IDs.
  entitlements: {
    "keychain-access-groups": ["$(AppIdentifierPrefix)com.sampocs.archie.shared"],
  },
};
