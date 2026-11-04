process.env.TZ = "America/New_York"; // Snooze tests rely on a fixed zone with a DST change.

module.exports = {
  preset: "jest-expo",
  testMatch: ["<rootDir>/src/**/*.test.ts"],
};
