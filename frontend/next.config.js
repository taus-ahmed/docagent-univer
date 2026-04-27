/** @type {import("next").NextConfig} */
const nextConfig = {
  reactStrictMode: false,
  transpilePackages: ["@fortune-sheet/react", "@fortune-sheet/core"],
  
  async rewrites() {
    const backendUrl = process.env.BACKEND_URL || 
                       process.env.NEXT_PUBLIC_API_URL || 
                       "http://localhost:8000";
    return [
      {
        source: "/api/:path*",
        destination: `${backendUrl}/api/:path*`,
      },
    ];
  },

  webpack(config) {
    config.resolve.fallback = { 
      ...config.resolve.fallback, 
      canvas: false, fs: false, path: false 
    };
    return config;
  },
};

module.exports = nextConfig;