import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Static export: no Node server, deployed to S3+CloudFront as a plain SPA.
  // See openspec/changes/kureha-mvp/design.md §2.5 / §20 for the rationale
  // (no SSR, no API routes, no dynamic Server Actions in this app).
  output: "export",
};

export default nextConfig;
