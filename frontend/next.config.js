/** @type {import("next").NextConfig} */
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
    // Alias opentype.js module path that Univer expects
    config.resolve.alias = {
      ...config.resolve.alias,
      "opentype.js/dist/opentype.module.js": require.resolve("opentype.js"),
    };
    return config;
  },
};
module.exports = nextConfig;