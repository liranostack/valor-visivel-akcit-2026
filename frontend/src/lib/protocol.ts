// Mirror of packages/vv-contracts/src/vv_contracts/ws.py (keep in sync).

export type LayerId = "clarity" | "singularity" | "translation" | "sustainment";
export type SessionStatus =
  | "onboarding"
  | "baseline"
  | "in_layer"
  | "layer_review"
  | "pre_core_review"
  | "core_generation"
  | "completed";

export interface AbcOption {
  label: "A" | "B" | "C";
  text: string;
  references_fact_ids: string[];
}

// client -> server
export type ClientMessage =
  | { type: "start_session" }
  | { type: "consent"; session_id: string; accepted: boolean }
  | { type: "onboarding_answer"; session_id: string; field: string; value: string | string[] }
  | { type: "user_message"; session_id: string; text: string }
  | {
      type: "review_action";
      session_id: string;
      target: LayerId | "pre_core";
      intent: "approve" | "adjust" | "doubt";
      notes?: string;
    };

// server -> client
export interface TokenEvent { type: "token"; session_id: string; text: string }
export interface MessageDoneEvent {
  type: "message_done";
  session_id: string;
  message: string;
  turn_seq: number;
  abc_options?: AbcOption[] | null;
}
export interface StateEvent {
  type: "state";
  session_id: string;
  status: SessionStatus;
  active_layer?: LayerId | null;
  layer_index?: number | null;
}
export interface DeliverableEvent {
  type: "deliverable";
  session_id: string;
  kind: "layer_synthesis" | "pre_core" | "core";
  layer_id?: LayerId | null;
  content: Record<string, unknown>;
}
export interface OnboardingStepEvent {
  type: "onboarding_step";
  session_id: string;
  field: string;
  question: string;
  options: string[];
  multiple: boolean;
  free_text: boolean;
  step: number;
  total: number;
}
export interface ProgressEvent { type: "progress"; session_id: string; message: string }
export interface ErrorEvent { type: "error"; session_id?: string | null; code: string; message: string }

export type ServerEvent =
  | TokenEvent
  | MessageDoneEvent
  | StateEvent
  | DeliverableEvent
  | OnboardingStepEvent
  | ProgressEvent
  | ErrorEvent;

const SERVER_TYPES = new Set([
  "token",
  "message_done",
  "state",
  "deliverable",
  "onboarding_step",
  "progress",
  "error"
]);

export function parseServerEvent(raw: string): ServerEvent | null {
  try {
    const data = JSON.parse(raw) as { type?: unknown };
    if (typeof data?.type === "string" && SERVER_TYPES.has(data.type)) return data as ServerEvent;
  } catch {
    /* not JSON (e.g. API Gateway "Forbidden"): ignore */
  }
  return null;
}

/** API Gateway routes by `action`. */
export function encodeClientMessage(msg: ClientMessage): string {
  return JSON.stringify({ action: "sendMessage", ...msg });
}

/** A click on an ABC option sends the option text, never just the letter. */
export function abcAnswer(option: AbcOption): string {
  return `${option.label}) ${option.text}`;
}
