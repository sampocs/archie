module.exports = function (api) {
  api.cache(true);
  return {
    presets: ["babel-preset-expo"],
    // Bundles Drizzle's generated .sql migrations into the JS bundle.
    plugins: [["inline-import", { extensions: [".sql"] }]],
  };
};
