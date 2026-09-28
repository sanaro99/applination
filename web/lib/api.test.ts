import { afterEach, describe, expect, it, vi } from "vitest";

import { api, ApiError, setUnauthorizedHandler } from "./api";

afterEach(() => {
  vi.unstubAllGlobals();
  setUnauthorizedHandler(null);
});

describe("API errors", () => {
  it("shows a readable gateway error instead of Cloudflare's HTML", async () => {
    const html = "<!DOCTYPE html><html><head><title>502: Bad gateway</title></head><body>Host Error</body></html>";
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(html, {
      status: 502,
      statusText: "Bad Gateway",
      headers: { "Content-Type": "text/html" },
    })));

    const error = await api.listProviderModels("ollama", {}).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 502 });
    expect(String(error)).toContain("temporarily unavailable");
    expect(String(error)).not.toContain("<html");
    expect((error as ApiError).detail).not.toContain("DOCTYPE");
  });

  it("uses the server's JSON detail as the readable error", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({
      detail: "Start your local Ollama worker, then retry.",
    }), { status: 503, headers: { "Content-Type": "application/json" } })));

    const error = await api.listProviderModels("ollama", {}).catch((e: unknown) => e);
    expect(error).toMatchObject({ detail: "Start your local Ollama worker, then retry." });
    expect(String(error)).not.toContain('{"detail":');
  });

  it("shows validation messages without echoing the rejected input", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({
      detail: [{ msg: "Invalid model ID", input: "private-input" }],
    }), { status: 422 })));
    const error = await api.listProviderModels("ollama", {}).catch((e: unknown) => e);
    expect(error).toMatchObject({ status: 422, detail: "Invalid model ID" });
    expect(String(error)).not.toContain("private-input");
  });

  it("still signals an expired session on authenticated requests", async () => {
    const unauthorized = vi.fn();
    setUnauthorizedHandler(unauthorized);
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response('{"detail":"not signed in"}', { status: 401 })));
    await expect(api.listProviderModels("ollama", {})).rejects.toBeInstanceOf(ApiError);
    expect(unauthorized).toHaveBeenCalledOnce();
  });
});
