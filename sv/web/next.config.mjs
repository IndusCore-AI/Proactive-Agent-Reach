/** @type {import('next').NextConfig} */
const nextConfig = {
  // Served at induscore.site/sv: the marketing project (ai-native-crm-website)
  // rewrites /sv/* to this project, so every route and asset lives under /sv.
  basePath: '/sv',
  poweredByHeader: false,
  reactStrictMode: true,
  async headers() {
    return [
      {
        source: '/:path*',
        headers: [
          { key: 'X-Content-Type-Options', value: 'nosniff' },
          { key: 'Referrer-Policy', value: 'strict-origin-when-cross-origin' },
          { key: 'Permissions-Policy', value: 'camera=(), microphone=(), geolocation=()' },
        ],
      },
    ];
  },
};

export default nextConfig;
