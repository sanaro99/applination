import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Emit .next/standalone so the Docker image ships a self-contained
  // server.js plus only the node_modules it actually imports.
  output: "standalone",

  // The in-browser inbox classifier (WebLLM) loads a self-hosted wasm + model
  // shards from /public/models. Next's gzip was re-encoding the .wasm (and the
  // binary shards) but stripping Content-Encoding, so the browser handed the
  // still-gzipped bytes straight to WebAssembly.instantiate ("expected magic
  // word 00 61 73 6d, found 1f 8b" — gzip). Serving these assets uncompressed
  // keeps the bytes intact. This is a local single-tenant tool, so turning off
  // HTTP compression app-wide is a non-issue.
  compress: false,
};

export default nextConfig;
