// Demo replay (A.04.07): plays back a real recorded session with the same events the live
// server sends, so the screen behaves exactly like the live demo if AWS fails on stage.
// The file comes from scripts/export_session.py --replay (never written by hand) and is served
// from /replays/<label>.json. Open the site with ?replay=<label> (or build with
// NEXT_PUBLIC_REPLAY=<label>); ?speed=2 plays the waits twice as fast.
import type { AbcOption, ClientMessage, ServerEvent } from "./protocol";
import type { Connection } from "./ws";

export interface ReplayTurn {
  answer: string;
  reply: string;
  abc_options: AbcOption[] | null;
  latency_ms: number;
  synthesis: Record<string, unknown> | null;
}

export interface ReplayScript {
  label: string;
  session_id: string;
  business: string | null;
  baseline?: string | null;
  first_question: string;
  turns: ReplayTurn[];
  approved_message: string | null;
}

export interface ReplayConnection extends Connection {
  /** Her recorded answer for the next turn, to prefill the composer (null when none is left). */
  nextAnswer(): string | null;
}

// --- multi-layer (version 2) -----------------------------------------------------------------

import type { LayerId } from "./protocol";

export interface ReplayLayerFull {
  layer_id: LayerId;
  layer_index: number;
  first_question: string;
  turns: Array<{
    answer: string;
    reply: string;
    abc_options: AbcOption[] | null;
    latency_ms: number;
  }>;
  synthesis: Record<string, unknown>;
  approval_reply: string;
}

export interface ReplayScriptFull {
  version: 2;
  label: string;
  session_id: string;
  business: string | null;
  layers: ReplayLayerFull[];
  core: Record<string, unknown> | null;
  core_reply: string | null;
}

const MIN_WAIT_MS = 800;
const MAX_WAIT_MS = 12000;
const APPROVED =
  "Mapa aprovado. Ele fica guardado como a base das próximas partes, que aprofundam o que torna o seu trabalho único e como contar isso para quem compra.";

export function replayParams(
  search: string,
  buildTime?: string,
): { label: string; speed: number } | null {
  const params = new URLSearchParams(search);
  const label = params.get("replay") ?? buildTime ?? "";
  if (!/^[\w-]+$/.test(label)) return null;
  const speed = Number(params.get("speed") ?? "1");
  return { label, speed: Number.isFinite(speed) && speed > 0 ? speed : 1 };
}

export async function loadReplay(
  label: string,
  fetchFn: typeof fetch = fetch,
): Promise<ReplayScript | ReplayScriptFull | null> {
  try {
    const response = await fetchFn(`/replays/${label}.json`, {
      cache: "no-store",
    });
    if (!response.ok) return null;
    const script = await response.json();
    if (script.version === 2 && Array.isArray(script.layers)) {
      return script as ReplayScriptFull;
    }
    return script.first_question && Array.isArray(script.turns)
      ? (script as ReplayScript)
      : null;
  } catch {
    return null;
  }
}

export function replayWait(latencyMs: number, speed: number): number {
  return Math.min(Math.max(latencyMs / speed, MIN_WAIT_MS), MAX_WAIT_MS);
}

function say(
  sid: string,
  text: string,
  seq: number,
  abc: AbcOption[] | null = null,
): ServerEvent[] {
  const words = text.split(" ");
  const tokens: ServerEvent[] = words.map((w, i) => ({
    type: "token",
    session_id: sid,
    text: i === words.length - 1 ? w : `${w} `,
  }));
  return [
    ...tokens,
    {
      type: "message_done",
      session_id: sid,
      message: text,
      turn_seq: seq,
      abc_options: abc,
    },
  ];
}

export function createReplayServer(
  script: ReplayScript,
  onEvent: (event: ServerEvent) => void,
  speed = 1,
): ReplayConnection {
  const sid = script.session_id;
  let next = 0;
  let closed = false;
  const timers: ReturnType<typeof setTimeout>[] = [];
  const later = (ms: number, fn: () => void) =>
    timers.push(setTimeout(() => !closed && fn(), ms));
  const stream = (events: ServerEvent[], at: number) =>
    events.forEach((e, i) => later(at + i * 25, () => onEvent(e)));

  const answer = (seq: number) => {
    const turn = script.turns[next];
    next += 1;
    if (!turn) {
      stream(say(sid, script.approved_message ?? APPROVED, seq), 400);
      return;
    }
    const wait = replayWait(turn.latency_ms, speed);
    const steps = turn.synthesis
      ? ["Lendo sua resposta…", "Montando a síntese desta parte…"]
      : ["Lendo sua resposta…", "Pensando na próxima pergunta…"];
    later(0, () =>
      onEvent({ type: "progress", session_id: sid, message: steps[0] }),
    );
    later(wait / 2, () =>
      onEvent({ type: "progress", session_id: sid, message: steps[1] }),
    );
    const events: ServerEvent[] = [];
    if (turn.synthesis) {
      events.push({
        type: "deliverable",
        session_id: sid,
        kind: "layer_synthesis",
        layer_id: "clarity",
        content: turn.synthesis,
      });
    }
    events.push(...say(sid, turn.reply, seq, turn.abc_options));
    if (turn.synthesis) {
      events.push({
        type: "state",
        session_id: sid,
        status: "layer_review",
        active_layer: "clarity",
        layer_index: 1,
      });
    }
    stream(events, wait);
  };

  let seq = 1;
  return {
    nextAnswer: () => script.turns[next]?.answer ?? null,
    close() {
      closed = true;
      timers.forEach(clearTimeout);
    },
    send(msg: ClientMessage) {
      if (msg.type === "start_session") {
        stream(
          [
            {
              type: "state",
              session_id: sid,
              status: "in_layer",
              active_layer: "clarity",
              layer_index: 1,
            },
            ...say(sid, script.first_question, seq),
          ],
          400,
        );
        return;
      }
      if (msg.type === "user_message") {
        seq += 1;
        answer(seq);
        return;
      }
      if (msg.type === "review_action" && msg.intent === "approve") {
        seq += 1;
        next = script.turns.length;
        stream(say(sid, script.approved_message ?? APPROVED, seq), 600);
      }
    },
  };
}

export function createFullReplayServer(
  script: ReplayScriptFull,
  onEvent: (event: ServerEvent) => void,
  speed = 1,
): ReplayConnection {
  const sid = script.session_id;
  let layerIdx = 0;
  let turnIdx = 0;
  let phase: "chatting" | "review" | "done" = "chatting";
  let seq = 0;
  let closed = false;
  const timers: ReturnType<typeof setTimeout>[] = [];
  const later = (ms: number, fn: () => void) =>
    timers.push(setTimeout(() => !closed && fn(), ms));
  const stream = (events: ServerEvent[], at: number) =>
    events.forEach((e, i) => later(at + i * 25, () => onEvent(e)));

  return {
    nextAnswer: () =>
      script.layers[layerIdx]?.turns[turnIdx]?.answer ?? null,
    close() {
      closed = true;
      timers.forEach(clearTimeout);
    },
    send(msg: ClientMessage) {
      if (msg.type === "start_session") {
        const layer = script.layers[0];
        seq++;
        stream(
          [
            {
              type: "state",
              session_id: sid,
              status: "in_layer",
              active_layer: layer.layer_id,
              layer_index: layer.layer_index,
            },
            ...say(sid, layer.first_question, seq),
          ],
          400,
        );
        return;
      }

      if (msg.type === "user_message" && phase === "chatting") {
        const layer = script.layers[layerIdx];
        const turn = layer?.turns[turnIdx];
        if (!turn) return;
        const isLast = turnIdx === layer.turns.length - 1;
        seq++;
        const wait = replayWait(turn.latency_ms, speed);
        later(0, () =>
          onEvent({
            type: "progress",
            session_id: sid,
            message: isLast
              ? "Montando a síntese desta parte…"
              : "Lendo sua resposta…",
          }),
        );
        const events: ServerEvent[] = [];
        if (isLast) {
          events.push({
            type: "deliverable",
            session_id: sid,
            kind: "layer_synthesis",
            layer_id: layer.layer_id,
            content: layer.synthesis,
          });
        }
        events.push(...say(sid, turn.reply, seq, isLast ? null : turn.abc_options));
        if (isLast) {
          events.push({
            type: "state",
            session_id: sid,
            status: "layer_review",
            active_layer: layer.layer_id,
            layer_index: layer.layer_index,
          });
        }
        stream(events, wait);
        turnIdx++;
        if (isLast) phase = "review";
        return;
      }

      if (
        msg.type === "review_action" &&
        msg.intent === "approve" &&
        phase === "review"
      ) {
        const layer = script.layers[layerIdx];
        seq++;
        layerIdx++;
        turnIdx = 0;

        if (layerIdx >= script.layers.length) {
          const events: ServerEvent[] = [...say(sid, layer.approval_reply, seq)];
          if (script.core) {
            events.push({
              type: "deliverable",
              session_id: sid,
              kind: "core",
              content: script.core,
            });
          }
          if (script.core_reply) {
            seq++;
            events.push(...say(sid, script.core_reply, seq));
          }
          events.push({
            type: "state",
            session_id: sid,
            status: "completed",
            active_layer: layer.layer_id,
            layer_index: layer.layer_index,
          });
          stream(events, 600);
          phase = "done";
        } else {
          const nextLayer = script.layers[layerIdx];
          phase = "chatting";
          seq++;
          stream(
            [
              ...say(sid, layer.approval_reply, seq - 1),
              {
                type: "state",
                session_id: sid,
                status: "in_layer",
                active_layer: nextLayer.layer_id,
                layer_index: nextLayer.layer_index,
              },
              ...say(sid, nextLayer.first_question, seq),
            ],
            600,
          );
        }
      }
    },
  };
}
