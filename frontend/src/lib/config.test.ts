import { describe, expect, it, vi } from "vitest";
import { resolveWsUrl } from "./config";

const okFetch = (body: unknown) =>
  vi.fn(async () => new Response(JSON.stringify(body), { status: 200 })) as unknown as typeof fetch;

describe("resolveWsUrl", () => {
  it("prefers the build-time variable", async () => {
    const fetchFn = okFetch({ wsUrl: "wss://from-config" });
    expect(await resolveWsUrl("wss://from-env", fetchFn)).toBe("wss://from-env");
    expect(fetchFn).not.toHaveBeenCalled();
  });

  it("reads config.json written at deploy time", async () => {
    expect(await resolveWsUrl(undefined, okFetch({ wsUrl: "wss://from-config" }))).toBe(
      "wss://from-config"
    );
  });

  it("returns undefined when there is no config", async () => {
    const missing = vi.fn(async () => new Response("", { status: 404 })) as unknown as typeof fetch;
    expect(await resolveWsUrl(undefined, missing)).toBeUndefined();
  });

  it("ignores a config without a wss url", async () => {
    expect(await resolveWsUrl(undefined, okFetch({ wsUrl: "http://x" }))).toBeUndefined();
  });
});
