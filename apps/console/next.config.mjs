/** @type {import('next').NextConfig} */
const API = process.env.NEXUS_API_URL ?? "http://localhost:8000";

const nextConfig = {
  reactStrictMode: true,
  // Proxy the API in development so the browser sees one origin and CORS stays
  // out of the way while you are building.
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API}/:path*` }];
  },
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
        ],
      },
    ];
  },
};

export default nextConfig;
