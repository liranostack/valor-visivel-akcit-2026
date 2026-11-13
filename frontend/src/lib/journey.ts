// Pure UI state of a journey, driven by ServerEvents (unit-tested).
import type {
  AbcOption,
  LayerId,
  OnboardingStepEvent,
  ServerEvent,
  SessionStatus,
} from "./protocol";

export interface ChatMessage {
  role: "assistant" | "user";
  text: string;
}

export interface Synthesis {
  layerId: LayerId | null;
  sections: { title: string; markdown: string }[];
  gaps: string[];
  hypotheses: string[];
}

export interface JourneyState {
  sessionId: string | null;
  status: SessionStatus | null;
  layerIndex: number | null;
  messages: ChatMessage[];
  streaming: string;
  waiting: boolean;
  progress: string | null;
  step: OnboardingStepEvent | null;
  abc: AbcOption[] | null;
  synthesis: Synthesis | null;
  error: string | null;
}

export const initialJourney: JourneyState = {
  sessionId: null,
  status: null,
  layerIndex: null,
  messages: [],
  streaming: "",
  waiting: false,
  progress: null,
  step: null,
  abc: null,
  synthesis: null,
  error: null,
};

export const LAYER_NAMES: Record<LayerId, string> = {
  clarity: "Nitidez",
  singularity: "Singularidade",
  translation: "Tradução",
  sustainment: "Sustentação",
};

const FACT_REF = /\s*\[fact:[^\]\s]+\]/g;

/** Fact ids are for traceability, never for her eyes. */
export function stripFactRefs(text: string): string {
  return text
    .replace(FACT_REF, "")
    .replace(/\s+([.,;:!?])/g, "$1")
    .trim();
}

export function toSynthesis(
  content: Record<string, unknown>,
  layerId: LayerId | null,
): Synthesis {
  // The whole Synthesis carries the sections under "content"; accept bare sections as well.
  const nested = content.content;
  const raw = (
    nested && typeof nested === "object" ? nested : content
  ) as Record<string, string>;
  return {
    layerId,
    sections: Object.entries(raw).map(([title, markdown]) => ({
      title,
      markdown: stripFactRefs(String(markdown)),
    })),
    gaps: ((content.gaps as string[] | undefined) ?? []).map(stripFactRefs),
    hypotheses: ((content.hypotheses as string[] | undefined) ?? []).map(
      stripFactRefs,
    ),
  };
}

export type JourneyAction =
  | { kind: "event"; event: ServerEvent }
  | { kind: "sent"; text: string | null }
  | { kind: "disconnected" };

export function reduceJourney(
  state: JourneyState,
  action: JourneyAction,
): JourneyState {
  if (action.kind === "sent") {
    const messages = action.text
      ? [...state.messages, { role: "user" as const, text: action.text }]
      : state.messages;
    return {
      ...state,
      messages,
      waiting: true,
      abc: null,
      step: null,
      error: null,
      progress: null,
    };
  }
  if (action.kind === "disconnected") {
    return { ...state, waiting: false, progress: null };
  }
  const e = action.event;
  switch (e.type) {
    case "token":
      return {
        ...state,
        sessionId: e.session_id,
        streaming: state.streaming + e.text,
        progress: null,
      };
    case "message_done":
      return {
        ...state,
        sessionId: e.session_id,
        messages: [...state.messages, { role: "assistant", text: e.message }],
        streaming: "",
        waiting: false,
        progress: null,
        abc: e.abc_options && e.abc_options.length ? e.abc_options : null,
      };
    case "state":
      return {
        ...state,
        sessionId: e.session_id,
        status: e.status,
        layerIndex: e.layer_index ?? state.layerIndex,
      };
    case "onboarding_step":
      return {
        ...state,
        sessionId: e.session_id,
        step: e,
        waiting: false,
        progress: null,
      };
    case "deliverable":
      return e.kind === "layer_synthesis"
        ? { ...state, synthesis: toSynthesis(e.content, e.layer_id ?? null) }
        : state;
    case "progress":
      return { ...state, progress: e.message };
    case "error":
      return {
        ...state,
        error: e.message,
        waiting: false,
        streaming: "",
        progress: null,
      };
  }
}

/** Text shown for the abc buttons (without the letter prefix in the label). */
export function optionLabel(option: AbcOption): string {
  return `${option.label}) ${option.text}`;
}
