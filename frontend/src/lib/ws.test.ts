import { describe, expect, it, vi } from "vitest";
import { abcAnswer, encodeClientMessage, parseServerEvent } from "./protocol";
import { connect, withAccessCode } from "./ws";

class FakeSocket {
  readyState = 0;
  sent: string[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((m: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  send(data: string) {
    this.sent.push(data);
  }
  close() {
    this.onclose?.();
  }
  open() {
    this.readyState = 1;
    this.onopen?.();
  }
}

describe("protocol", () => {
  it("adds the API Gateway action", () => {
    expect(JSON.parse(encodeClientMessage({ type: "start_session" }))).toEqual({
      action: "sendMessage",
      type: "start_session",
    });
  });

  it("an ABC click sends the option text, not just the letter", () => {
    expect(
      abcAnswer({
        label: "B",
        text: "Ela provou o bolo.",
        references_fact_ids: ["f"],
      }),
    ).toBe("B) Ela provou o bolo.");
  });

  it("ignores non-protocol frames such as API Gateway Forbidden", () => {
    expect(parseServerEvent('{"message":"Forbidden"}')).toBeNull();
    expect(parseServerEvent("not json")).toBeNull();
    expect(
      parseServerEvent('{"type":"progress","session_id":"s","message":"…"}')
        ?.type,
    ).toBe("progress");
  });
});

describe("live connection", () => {
  it("queues messages until open and delivers events", () => {
    const sockets: FakeSocket[] = [];
    const events: unknown[] = [];
    const conn = connect({
      url: "wss://x",
      onEvent: (e) => events.push(e),
      socketFactory: () => {
        const s = new FakeSocket();
        sockets.push(s);
        return s as unknown as WebSocket;
      },
    });
    conn.send({ type: "start_session" });
    expect(sockets[0].sent).toEqual([]);
    sockets[0].open();
    expect(sockets[0].sent).toHaveLength(1);
    sockets[0].onmessage?.({
      data: '{"type":"state","session_id":"s","status":"onboarding"}',
    });
    expect(events).toHaveLength(1);
  });

  it("reconnects after an unexpected close, but not after close()", () => {
    vi.useFakeTimers();
    const sockets: FakeSocket[] = [];
    const conn = connect({
      url: "wss://x",
      onEvent: () => {},
      socketFactory: () => {
        const s = new FakeSocket();
        sockets.push(s);
        return s as unknown as WebSocket;
      },
    });
    sockets[0].open();
    sockets[0].onclose?.();
    vi.advanceTimersByTime(1000);
    expect(sockets).toHaveLength(2);
    conn.close();
    vi.advanceTimersByTime(10000);
    expect(sockets).toHaveLength(2);
    vi.useRealTimers();
  });

  it("a socket closed before ever opening is a refusal: no retries (A.04.10)", () => {
    const sockets: FakeSocket[] = [];
    const statuses: string[] = [];
    connect({
      url: "wss://x",
      onEvent: () => {},
      onStatus: (s) => statuses.push(s),
      socketFactory: () => {
        const s = new FakeSocket();
        sockets.push(s);
        return s as unknown as WebSocket;
      },
    });
    sockets[0].close();
    expect(statuses).toEqual(["connecting", "rejected"]);
    expect(sockets).toHaveLength(1);
  });
});

describe("access code", () => {
  it("goes in the query string, encoded", () => {
    expect(withAccessCode("wss://x/prod", "akcit 26")).toBe(
      "wss://x/prod?code=akcit%2026",
    );
    expect(withAccessCode("wss://x/prod", "")).toBe("wss://x/prod");
  });
});
