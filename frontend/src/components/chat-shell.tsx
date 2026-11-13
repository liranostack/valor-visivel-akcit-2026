"use client";

import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import { resolveWsUrl } from "@/lib/config";
import { initialJourney, LAYER_NAMES, reduceJourney } from "@/lib/journey";
import { abcAnswer, type ClientMessage, type LayerId } from "@/lib/protocol";
import {
  createFullReplayServer,
  createReplayServer,
  loadReplay,
  type ReplayScript,
  replayParams,
} from "@/lib/replay";
import { connect, withAccessCode, type Connection } from "@/lib/ws";
import { OnboardingStep } from "./onboarding-step";
import { ResultPage } from "./result-page";
import { SynthesisCard } from "./synthesis-card";

const WS_URL = process.env.NEXT_PUBLIC_WS_URL;
const MOCK = process.env.NEXT_PUBLIC_WS_MOCK === "1";
const REPLAY = process.env.NEXT_PUBLIC_REPLAY;
// Local run (scripts/local_ws.py): plain ws:// on this machine, no access code.
const LOCAL = !!WS_URL && WS_URL.startsWith("ws://");
const LAYERS: LayerId[] = [
  "clarity",
  "singularity",
  "translation",
  "sustainment",
];
const CODE_KEY = "vv.accessCode";

function savedCode(): string {
  try {
    return window.localStorage.getItem(CODE_KEY) ?? "";
  } catch {
    return "";
  }
}

function saveCode(code: string): void {
  try {
    if (code) window.localStorage.setItem(CODE_KEY, code);
    else window.localStorage.removeItem(CODE_KEY);
  } catch {
    // private window or blocked storage: she types it again next time
  }
}

export function ChatShell() {
  const [state, dispatch] = useReducer(reduceJourney, initialJourney);
  const [started, setStarted] = useState(false);
  const [input, setInput] = useState("");
  const [approvedLayerId, setApprovedLayerId] = useState<LayerId | null>(null);
  const [code, setCode] = useState("");
  const [refused, setRefused] = useState(false);
  const [replay, setReplay] = useState<{ label: string; speed: number } | null>(
    null,
  );
  const [replayMissing, setReplayMissing] = useState(false);
  const [business, setBusiness] = useState<string | null>(null);
  const [baseline, setBaseline] = useState<string | null>(null);
  const [showResult, setShowResult] = useState(false);
  const connection = useRef<Connection | null>(null);
  const listRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    listRef.current?.scrollTo({
      top: listRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [state.messages, state.streaming, state.step, state.abc, state.progress]);

  useEffect(() => () => connection.current?.close(), []);
  useEffect(() => setCode(savedCode()), []);
  useEffect(() => setReplay(replayParams(window.location.search, REPLAY)), []);

  const send = useCallback((msg: ClientMessage, shown: string | null) => {
    dispatch({ kind: "sent", text: shown });
    connection.current?.send(msg);
  }, []);

  const startReplay = async (label: string, speed: number) => {
    const script = await loadReplay(label);
    if (!script) {
      setReplayMissing(true);
      return;
    }
    if ("version" in script && script.version === 2) {
      const server = createFullReplayServer(
        script,
        (event) => {
          dispatch({ kind: "event", event });
          // Her recorded answer waits in the composer: the presenter only presses Enviar.
          if (event.type === "message_done") setInput(server.nextAnswer() ?? "");
        },
        speed,
      );
      connection.current = server;
      setBusiness(script.business ?? null);
      setBaseline(null);
    } else {
      const v1 = script as ReplayScript;
      const server = createReplayServer(
        v1,
        (event) => {
          dispatch({ kind: "event", event });
          // Her recorded answer waits in the composer: the presenter only presses Enviar.
          if (event.type === "message_done") setInput(server.nextAnswer() ?? "");
        },
        speed,
      );
      connection.current = server;
      setBusiness(v1.business ?? null);
      setBaseline(v1.baseline ?? null);
    }
    setStarted(true);
    send({ type: "start_session" }, null);
  };

  const start = async () => {
    if (replay) {
      await startReplay(replay.label, replay.speed);
      return;
    }
    const base = MOCK ? undefined : await resolveWsUrl(WS_URL);
    const url = base ? withAccessCode(base, code) : undefined;
    setRefused(false);
    connection.current = connect({
      url,
      mock: MOCK,
      onEvent: (event) => dispatch({ kind: "event", event }),
      onStatus: (status) => {
        if (status === "closed") dispatch({ kind: "disconnected" });
        if (status === "rejected") {
          dispatch({ kind: "disconnected" });
          saveCode("");
          setRefused(true);
          setStarted(false);
        }
        if (status === "open") saveCode(code);
      },
    });
    setStarted(true);
    send({ type: "start_session" }, null);
  };

  const sid = state.sessionId ?? "";
  const canType =
    !state.waiting &&
    !state.step &&
    (state.status === "in_layer" || state.status === "layer_review");

  const submitText = () => {
    const text = input.trim();
    if (!text || !sid) return;
    send({ type: "user_message", session_id: sid, text }, text);
    setInput("");
  };

  if (!started) {
    return (
      <div className="welcome">
        <h1>Valor Visível</h1>
        <p>
          Uma conversa guiada para você descobrir, com as suas palavras, o que
          faz o seu trabalho ser escolhido, com fatos da sua rotina.
        </p>
        <p className="retention">
          Seus dados ficam só nesta sessão, servem apenas para construir o seu
          material e são apagados em 30 dias.
        </p>
        <form
          className="actions access"
          onSubmit={(e) => {
            e.preventDefault();
            void start();
          }}
        >
          {!MOCK && !LOCAL && !replay && (
            <input
              className="access-code"
              type="password"
              autoComplete="off"
              placeholder="Código de acesso"
              aria-label="Código de acesso"
              value={code}
              onChange={(e) => setCode(e.target.value)}
            />
          )}
          <button
            className="primary"
            type="submit"
            disabled={!MOCK && !LOCAL && !replay && !code.trim()}
          >
            Começar
          </button>
        </form>
        {replayMissing && (
          <p className="small access-error" role="alert">
            Não encontrei a sessão gravada &quot;{replay?.label}&quot;.
          </p>
        )}
        {refused && (
          <p className="small access-error" role="alert">
            Não consegui entrar com esse código. Confira o código de acesso e
            tente de novo.
          </p>
        )}
        {MOCK && <p className="small">Modo demonstração sem servidor.</p>}
      </div>
    );
  }

  if (showResult && state.synthesis) {
    return (
      <ResultPage
        synthesis={state.synthesis}
        business={business}
        baseline={baseline}
        onBack={() => setShowResult(false)}
      />
    );
  }

  return (
    <div className="app-shell">
      <header className="app-topbar">
        <div className="app-topbar-left">
          <strong>Valor Visível</strong>
        </div>
        <div className="app-topbar-right">
          {replay && (
            <span className="topbar-pill replay-pill">Sessão gravada</span>
          )}
          {state.layerIndex && (
            <span className="topbar-pill">
              Camada {state.layerIndex} de 4 ·{" "}
              {LAYER_NAMES[LAYERS[state.layerIndex - 1]]}
            </span>
          )}
        </div>
      </header>

      <main className="chat-layout">
        <section className="chat-primary">
          <div className="content">
            <div className="chat-list" ref={listRef}>
              {state.messages.map((m, i) => (
                <div key={i} className={`msg ${m.role}`}>
                  {m.role === "assistant" ? (
                    <AssistantText text={m.text} />
                  ) : (
                    m.text
                  )}
                </div>
              ))}
              {state.streaming && (
                <div className="msg assistant">{state.streaming}</div>
              )}
              {state.waiting && !state.streaming && (
                <div
                  className="msg assistant typing-indicator"
                  role="status"
                  aria-live="polite"
                >
                  <span className="typing-dots" aria-hidden>
                    <i />
                    <i />
                    <i />
                  </span>
                  <span className="progress-text">
                    {state.progress ?? "Pensando…"}
                  </span>
                </div>
              )}

              {state.step && (
                <OnboardingStep
                  step={state.step}
                  onConsent={(accepted, label) =>
                    send({ type: "consent", session_id: sid, accepted }, label)
                  }
                  onAnswer={(value, shown) => {
                    if (state.step!.field === "baseline")
                      setBaseline(String(value));
                    if (state.step!.field === "offer")
                      setBusiness(String(shown ?? value));
                    send(
                      state.step!.field === "baseline"
                        ? {
                            type: "user_message",
                            session_id: sid,
                            text: String(value),
                          }
                        : {
                            type: "onboarding_answer",
                            session_id: sid,
                            field: state.step!.field,
                            value,
                          },
                      shown,
                    );
                  }}
                />
              )}

              {state.abc && !state.waiting && (
                <div
                  className="choice-panel abc-list"
                  role="group"
                  aria-label="Opções de resposta"
                >
                  {state.abc.map((option) => (
                    <button
                      key={option.label}
                      className="choice"
                      onClick={() =>
                        send(
                          {
                            type: "user_message",
                            session_id: sid,
                            text: abcAnswer(option),
                          },
                          abcAnswer(option),
                        )
                      }
                    >
                      {option.label}) {option.text}
                    </button>
                  ))}
                </div>
              )}
              {state.error && (
                <p className="error-strip" role="alert">
                  {state.error}
                </p>
              )}
            </div>

            <div className="controls chat-composer">
              <div className="composer-row">
                <textarea
                  rows={2}
                  placeholder={
                    canType && state.status === "layer_review"
                      ? "Algo não está fiel? Escreva o que ajustar no mapa…"
                      : canType
                        ? "Conte com exemplos do seu dia a dia…"
                        : state.waiting
                          ? "Aguarde…"
                          : "Responda pelas opções acima"
                  }
                  value={input}
                  disabled={!canType}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !e.shiftKey) {
                      e.preventDefault();
                      submitText();
                    }
                  }}
                  aria-label="Sua resposta"
                />
                <button
                  className="composer-send"
                  onClick={submitText}
                  disabled={!canType || !input.trim()}
                >
                  Enviar
                </button>
              </div>
              <p className="small composer-help">
                Enter envia. Shift + Enter quebra linha.
              </p>
            </div>
          </div>
        </section>

        <aside className="side-panel-cards" aria-label="Sua jornada">
          <div className="card">
            <div className="header">
              <strong>Sua jornada</strong>
            </div>
            <div className="content">
              <ol className="layers">
                {LAYERS.map((layer, i) => {
                  const index = i + 1;
                  const cls =
                    state.layerIndex === index
                      ? "current"
                      : state.layerIndex && index < state.layerIndex
                        ? "done"
                        : "";
                  return (
                    <li key={layer} className={cls}>
                      <span className="dot" aria-hidden />
                      {LAYER_NAMES[layer]}
                    </li>
                  );
                })}
                <li>
                  <span className="dot" aria-hidden />
                  Núcleo Essencial
                </li>
              </ol>
            </div>
          </div>
          {state.synthesis && (
            <SynthesisCard
              synthesis={state.synthesis}
              onShowResult={
                state.synthesis.layerId &&
                state.synthesis.layerId === approvedLayerId
                  ? () => setShowResult(true)
                  : undefined
              }
              onApprove={
                state.status === "layer_review" &&
                state.synthesis.layerId !== approvedLayerId &&
                !state.waiting &&
                state.synthesis.layerId
                  ? () => {
                      setApprovedLayerId(state.synthesis!.layerId);
                      setShowResult(true);
                      window.scrollTo({ top: 0 });
                      send(
                        {
                          type: "review_action",
                          session_id: sid,
                          target: state.synthesis!.layerId!,
                          intent: "approve",
                        },
                        "Está fiel, aprovo o mapa.",
                      );
                    }
                  : undefined
              }
            />
          )}
        </aside>
      </main>
    </div>
  );
}

// vv rhythm: acknowledgment and gap, then the question in bold (A.06.16).
function AssistantText({ text }: { text: string }) {
  const parts = text.split("\n\n");
  const q = parts.findIndex((p) => p.trim().endsWith("?"));
  if (q <= 0) return <>{text}</>;
  return (
    <>
      {parts.map((p, i) => (
        <span key={i}>
          {i > 0 && "\n\n"}
          {i === q ? <strong>{p}</strong> : p}
        </span>
      ))}
    </>
  );
}
