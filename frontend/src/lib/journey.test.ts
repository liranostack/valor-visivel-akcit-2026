import { describe, expect, it } from "vitest";
import {
  initialJourney,
  reduceJourney,
  stripFactRefs,
  toSynthesis,
} from "./journey";
import type { ServerEvent } from "./protocol";

const run = (events: ServerEvent[]) =>
  events.reduce(
    (s, event) => reduceJourney(s, { kind: "event", event }),
    initialJourney,
  );

describe("journey", () => {
  it("streams tokens and commits the message on message_done", () => {
    const s = run([
      { type: "token", session_id: "s", text: "Olá " },
      { type: "token", session_id: "s", text: "mundo" },
    ]);
    expect(s.streaming).toBe("Olá mundo");
    const done = reduceJourney(s, {
      kind: "event",
      event: {
        type: "message_done",
        session_id: "s",
        message: "Olá mundo",
        turn_seq: 1,
      },
    });
    expect(done.streaming).toBe("");
    expect(done.messages.at(-1)).toEqual({
      role: "assistant",
      text: "Olá mundo",
    });
  });

  it("keeps ABC options until the next answer is sent", () => {
    const s = run([
      {
        type: "message_done",
        session_id: "s",
        message: "?",
        turn_seq: 2,
        abc_options: [{ label: "A", text: "x", references_fact_ids: ["f"] }],
      },
    ]);
    expect(s.abc).toHaveLength(1);
    const sent = reduceJourney(s, { kind: "sent", text: "A) x" });
    expect(sent.abc).toBeNull();
    expect(sent.waiting).toBe(true);
    expect(sent.messages.at(-1)).toEqual({ role: "user", text: "A) x" });
  });

  it("tracks status, layer and onboarding steps", () => {
    const s = run([
      {
        type: "state",
        session_id: "s",
        status: "in_layer",
        active_layer: "clarity",
        layer_index: 1,
      },
      {
        type: "onboarding_step",
        session_id: "s",
        field: "offer",
        question: "O que você oferece?",
        options: [],
        multiple: false,
        free_text: true,
        step: 3,
        total: 10,
      },
    ]);
    expect(s.status).toBe("in_layer");
    expect(s.layerIndex).toBe(1);
    expect(s.step?.field).toBe("offer");
  });

  it("errors stop waiting and show a safe message", () => {
    const s = reduceJourney(
      reduceJourney(initialJourney, { kind: "sent", text: "oi" }),
      {
        kind: "event",
        event: {
          type: "error",
          code: "turn_failed",
          message: "Tive um problema agora.",
        },
      },
    );
    expect(s.waiting).toBe(false);
    expect(s.error).toBe("Tive um problema agora.");
  });
});

describe("synthesis", () => {
  it("never shows fact ids", () => {
    expect(
      stripFactRefs(
        "Você confirma por escrito [fact:ab12cd] o pedido [fact:x9].",
      ),
    ).toBe("Você confirma por escrito o pedido.");
  });

  it("maps the deliverable to ordered sections", () => {
    const syn = toSynthesis(
      {
        content: {
          "O que você faz": "Bolos [fact:f1].",
          "Lacunas e hipóteses": "Nada.",
        },
        gaps: ["Sem relato [fact:f2]"],
        hypotheses: [],
      },
      "clarity",
    );
    expect(syn.sections.map((x) => x.title)).toEqual([
      "O que você faz",
      "Lacunas e hipóteses",
    ]);
    expect(syn.sections[0].markdown).toBe("Bolos.");
    expect(syn.gaps).toEqual(["Sem relato"]);
  });

  it("reads a map sent as bare sections too (adjusted map, 12/11)", () => {
    const syn = toSynthesis(
      { "Uma leitura para você conferir": "Leitura [fact:f1]." },
      "clarity",
    );
    expect(syn.sections).toEqual([
      { title: "Uma leitura para você conferir", markdown: "Leitura." },
    ]);
  });
});
