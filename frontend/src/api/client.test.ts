import { afterEach, describe, expect, it, vi } from "vitest";
import { postApi } from "./client";

describe("postApi", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
  });

  it("uses the same-origin API proxy by default", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ status: "ok" }) });
    vi.stubGlobal("fetch", fetchMock);
    await postApi("/health", {});
    expect(fetchMock).toHaveBeenCalledWith("/api/health", expect.objectContaining({ method: "POST" }));
  });

  it("uses the configured Vercel backend origin without a double slash", async () => {
    vi.stubEnv("VITE_API_BASE_URL", "https://api.example.test/");
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) });
    vi.stubGlobal("fetch", fetchMock);
    await postApi("/ask", { query: "test" }, "token");
    expect(fetchMock).toHaveBeenCalledWith("https://api.example.test/ask", expect.objectContaining({ headers: expect.objectContaining({ Authorization: "Bearer token" }) }));
  });

  it("raises an actionable error for failed API requests", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 503 }));
    await expect(postApi("/ask", {})).rejects.toThrow("Request failed (503)");
  });
});
