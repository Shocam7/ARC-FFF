/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // ── Voice / LiveKit env vars ───────────────────────────────────────────────
  // Set these in Vercel project settings (Environment Variables):
  //
  //   NEXT_PUBLIC_LIVEKIT_URL          wss://your-project.livekit.cloud
  //   NEXT_PUBLIC_TOKEN_SERVER_URL     https://your-token-server.railway.app
  //
  // For local development put them in web/.env.local
};

export default nextConfig;

