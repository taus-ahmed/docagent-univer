
/** @type {import("next").NextConfig} */

// Part 2.5: security headers on every page. The CSP allows what the app
// actually loads: its own scripts (Next.js inlines some, hence
// 'unsafe-inline'; 'unsafe-eval' only in development for hot reload), Google
// Fonts, images from itself and data:/blob: (charts, page images), and API
// calls to itself and to NEXT_PUBLIC_API_URL. HSTS only for a production build
// served over HTTPS (Vercel terminates TLS); never in development.
const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const DEV = process.env.NODE_ENV !== "production";
const CSP = [
  "default-src 'self'",
  `script-src 'self' 'unsafe-inline'${DEV ? " 'unsafe-eval'" : ""}`,
  "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
  "font-src 'self' https://fonts.gstatic.com data:",
  "img-src 'self' data: blob:",
  `connect-src 'self' ${API}${DEV ? " ws: http://localhost:*" : ""}`,
  "frame-ancestors 'none'",
  "base-uri 'self'",
  "form-action 'self'",
].join("; ");
const SECURITY_HEADERS = [
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Content-Security-Policy", value: CSP },
  ...(DEV ? [] : [{ key: "Strict-Transport-Security", value: "max-age=31536000; includeSubDomains" }]),
];

const nextConfig = {

  async headers() {
    return [{ source: "/:path*", headers: SECURITY_HEADERS }];
  },


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
