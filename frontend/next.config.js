/** @type {import("next").NextConfig} */
const webpack = require("webpack");

const nextConfig = {
  reactStrictMode: false,
  transpilePackages: [
    "@univerjs/preset-sheets-core",
    "@univerjs/presets",
    "@univerjs/core",
    "@univerjs/design",
    "@univerjs/docs",
    "@univerjs/docs-ui",
    "@univerjs/engine-formula",
    "@univerjs/engine-render",
    "@univerjs/sheets",
    "@univerjs/sheets-formula",
    "@univerjs/sheets-formula-ui",
    "@univerjs/sheets-numfmt",
    "@univerjs/sheets-numfmt-ui",
    "@univerjs/sheets-ui",
    "@univerjs/ui",
    "@univerjs/icons",
    "@univerjs/network",
    "@univerjs/rpc",
  ],
  webpack(config) {
    config.resolve.fallback = {
      ...config.resolve.fallback,
      canvas: false, fs: false, path: false,
    };
    config.plugins.push(
      new webpack.NormalModuleReplacementPlugin(
        /opentype\.js\/dist\/opentype\.module\.js/,
        require.resolve("opentype.js/dist/opentype.mjs")
      )
    );
    return config;
  },
};

module.exports = nextConfig;