
/** @type {import("next").NextConfig} */

const nextConfig = {

  reactStrictMode: false,

  webpack(config) {

    config.resolve.fallback = {

      ...config.resolve.fallback,

      canvas: false, fs: false, path: false,

    };

    return config;

  },

};

module.exports = nextConfig;
