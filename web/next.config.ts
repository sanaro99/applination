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
  // keeps the bytes intact. This is a small self-hosted app, so turning off
  // HTTP compression app-wide is a non-issue.
  compress: false,

  // Proxy the API through Next so the browser only ever talks to one origin.
  //
  // This is load-bearing for authentication, not a convenience. In dev the page
  // is http://localhost:3000 and the API is http://127.0.0.1:8000 — different
  // origins — and the session cookie is SameSite=Lax, which browsers do not
  // send on cross-site XHR. Without this rewrite every authenticated request
  // from the dev UI arrives anonymous and 401s, while the same build works in
  // production (already same-origin behind Traefik). That difference is
  // miserable to debug, so dev is made same-origin too.
  //
  // API_BASE in web/lib/api.ts defaults to "" to match.
  async rewrites() {
    const target =
      process.env.API_PROXY_TARGET ?? "http://127.0.0.1:8000";
    // Generated documents no longer need a rule of their own: the API's
    // StaticFiles mount at /files is gone, replaced by GET /api/files/... so
    // that every document read is scoped to the requesting user. That is
    // already covered by the /api rule below.
    return [
      { source: "/api/:path*", destination: `${target}/api/:path*` },
    ];
  },
};

export default nextConfig;
