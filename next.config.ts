import type { NextConfig } from "next";

const pydevApiBaseUrl = process.env.PYDEV_API_BASE_URL?.trim().replace(/\/$/, "");
const pydevRewritePaths = [
  "/api/login",
  "/api/logout",
  "/api/auth",
  "/api/balam",
  "/api/drawing",
] as const;

const nextConfig: NextConfig = {
  async rewrites() {
    if (process.env.NODE_ENV !== "development" || !pydevApiBaseUrl) {
      return [];
    }

    return pydevRewritePaths.map((source) => ({
      source,
      destination: `${pydevApiBaseUrl}${source}`,
    }));
  },
};

export default nextConfig;
