import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Static export: the Python API serves these files, so there is one process,
  // one URL, and no Node required at runtime.
  output: "export",
  trailingSlash: true,
  images: { unoptimized: true },
};

export default nextConfig;
