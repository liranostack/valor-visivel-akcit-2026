/** @type {import('next').NextConfig} */
// Static export: the app is only a WebSocket client, so it can be hosted on Amplify, on S3 +
// CloudFront or served from a laptop (`npx serve out`) as the demo fallback.
const nextConfig = {
  output: "export",
  images: { unoptimized: true }
};

export default nextConfig;
