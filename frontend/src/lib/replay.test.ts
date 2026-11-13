import { afterEach, describe, expect, it, vi } from "vitest";
import type { ServerEvent } from "./protocol";
import {
  createReplayServer,
  loadReplay,
  replayParams,
  replayWait,
  type ReplayScript,
} from "./replay";

// Unit-test fixture only; the demo replay comes from scripts/export_session.py --replay.
const SCRIPT: ReplayScript = {
  label: "fixture",
  session_id: "s1",
  business: "Empanadas",
  first_question: "Como foi a última vez?",
  turns: [
    {
      answer: "provo cada sabor",
      reply: "Você prova cada sabor. O que você confere?",
      abc_options: null,
      latency_ms: 4000,
      synthesis: null,
    },
    {
      answer: "a massa",
      reply: "Uma leitura para você conferir: a massa.\n\nEle está fiel?",
      abc_options: null,
      latency_ms: 20000,
      synthesis: {
        content: { "O que você faz": "Confere a massa [fact:f1]." },
        gaps: [],
        hypotheses: [],
      },
    },
  ],
  approved_message: "Mapa aprovado.",
};

afterEach(() => vi.useRealTimers());

function play() {
  vi.useFakeTimers();
  const events: ServerEvent[] = [];
  const conn = createReplayServer(SCRIPT, (e) => events.push(e));
  return {
    events,
    conn,
    done: () => events.filter((e) => e.type === "message_done"),
  };
}

describe("replay", () => {
  it("opens on the recorded first question", () => {
    const { conn, done } = play();
    conn.send({ type: "start_session" });
    vi.runAllTimers();
    expect(done().map((e) => e.type === "message_done" && e.message)).toEqual([
      "Como foi a última vez?",
    ]);
  });

  it("answers each message with the recorded reply after the original wait", () => {
    const { conn, events, done } = play();
    conn.send({ type: "start_session" });
    vi.runAllTimers();
    expect(conn.nextAnswer()).toBe("provo cada sabor");
    conn.send({
      type: "user_message",
      session_id: "s1",
      text: "provo cada sabor",
    });
    vi.advanceTimersByTime(3000);
    expect(done()).toHaveLength(1);
    expect(events.at(-1)?.type).toBe("progress");
    vi.runAllTimers();
    expect(done()).toHaveLength(2);
    expect(conn.nextAnswer()).toBe("a massa");
  });

  it("the closing turn sends the map and opens the review", () => {
    const { conn, events } = play();
    conn.send({ type: "start_session" });
    conn.send({ type: "user_message", session_id: "s1", text: "x" });
    conn.send({ type: "user_message", session_id: "s1", text: "y" });
    vi.runAllTimers();
    const map = events.find((e) => e.type === "deliverable");
    expect(map && map.type === "deliverable" && map.content).toEqual(
      SCRIPT.turns[1].synthesis,
    );
    expect(events.at(-1)).toMatchObject({
      type: "state",
      status: "layer_review",
    });
  });

  it("approving plays the recorded approval", () => {
    const { conn, done } = play();
    conn.send({
      type: "review_action",
      session_id: "s1",
      target: "clarity",
      intent: "approve",
    });
    vi.runAllTimers();
    expect(done().map((e) => e.type === "message_done" && e.message)).toEqual([
      "Mapa aprovado.",
    ]);
    expect(conn.nextAnswer()).toBeNull();
  });

  it("close() stops pending events", () => {
    const { conn, events } = play();
    conn.send({ type: "start_session" });
    conn.close();
    vi.runAllTimers();
    expect(events).toEqual([]);
  });
});

describe("replay params", () => {
  it("reads the label and speed from the URL, build time as fallback", () => {
    expect(replayParams("?replay=pastelaria&speed=2")).toEqual({
      label: "pastelaria",
      speed: 2,
    });
    expect(replayParams("", "demo")).toEqual({ label: "demo", speed: 1 });
    expect(replayParams("")).toBeNull();
    expect(replayParams("?replay=../etc")).toBeNull();
  });

  it("waits are clamped so the stage never stalls", () => {
    expect(replayWait(60000, 1)).toBe(12000);
    expect(replayWait(100, 1)).toBe(800);
    expect(replayWait(8000, 2)).toBe(4000);
  });

  it("a missing or broken file is null", async () => {
    const notFound = (async () =>
      new Response("", { status: 404 })) as typeof fetch;
    const ok = (async () =>
      new Response(JSON.stringify(SCRIPT))) as typeof fetch;
    expect(await loadReplay("x", notFound)).toBeNull();
    const r = await loadReplay("x", ok);
    expect(r && "turns" in r ? r.turns : null).toHaveLength(2);
  });
});
