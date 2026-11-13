// WebSocket URL: the build-time variable (local dev) or /config.json, written at deploy time by
// the FrontendStack from the ApiStack output, so one build serves any environment.

export async function resolveWsUrl(
  buildTime: string | undefined,
  fetchFn: typeof fetch = fetch
): Promise<string | undefined> {
  if (buildTime) return buildTime;
  try {
    const response = await fetchFn("/config.json", { cache: "no-store" });
    if (!response.ok) return undefined;
    const body = (await response.json()) as { wsUrl?: unknown };
    return typeof body.wsUrl === "string" && body.wsUrl.startsWith("wss://") ? body.wsUrl : undefined;
  } catch {
    return undefined;
  }
}
