import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Static export: no SSR, no API routes, no Server Actions -- deployed as a plain SPA.
  output: "export",
};

export default nextConfig;
