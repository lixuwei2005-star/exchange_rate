/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // No telemetry, no third-party stuff per CLAUDE.md §13.
  poweredByHeader: false,
};

module.exports = nextConfig;
