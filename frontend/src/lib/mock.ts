// Scripted server for development without the backend (NEXT_PUBLIC_WS_MOCK=1).
import type { ClientMessage, ServerEvent } from "./protocol";
import type { Connection } from "./ws";

const SID = "mock-session";

function say(text: string, seq: number, extra: Partial<ServerEvent> = {}): ServerEvent[] {
  const tokens = text.split(" ").map((w, i, all) => ({
    type: "token" as const,
    session_id: SID,
    text: i === all.length - 1 ? w : `${w} `
  }));
  return [...tokens, { type: "message_done", session_id: SID, message: text, turn_seq: seq, ...extra } as ServerEvent];
}

export function createMockServer(onEvent: (e: ServerEvent) => void): Connection {
  let answers = 0;
  const emit = (events: ServerEvent[], delay = 400) =>
    events.forEach((e, i) => setTimeout(() => onEvent(e), delay + i * 30));

  return {
    close() {},
    send(msg: ClientMessage) {
      if (msg.type === "start_session") {
        emit([
          { type: "state", session_id: SID, status: "onboarding" },
          {
            type: "onboarding_step",
            session_id: SID,
            field: "consent",
            question: "Antes de começar: o que você contar fica só nesta sessão e é apagado em 30 dias. Você concorda em seguir?",
            options: ["Concordo e quero começar", "Não concordo"],
            multiple: false,
            free_text: false,
            step: 1,
            total: 1
          }
        ]);
      } else if (msg.type === "consent" || msg.type === "onboarding_answer") {
        emit([
          { type: "state", session_id: SID, status: "in_layer", active_layer: "clarity", layer_index: 1 },
          ...say("Você disse que a dificuldade é “Noivas acham caro”, quando manda o orçamento. Pensa na última vez que isso aconteceu: o que você disse, o que a pessoa respondeu e como terminou?", 1)
        ]);
      } else if (msg.type === "review_action") {
        emit(
          say(
            "Mapa aprovado. Ele fica guardado como a base das próximas partes, que aprofundam o que torna o seu trabalho único e como contar isso para quem compra.",
            4
          )
        );
      } else if (msg.type === "user_message") {
        answers += 1;
        if (answers === 1) {
          emit(
            [
              { type: "progress", session_id: SID, message: "Lendo sua resposta…" },
              ...say("Um casamento de 120 pessoas no sábado retrasado já mostra o tamanho do que você entrega. Falta entender o que acontece antes de a noiva chegar até você.\n\nQuando uma noiva te procura, o que costuma ter acontecido antes disso?", 2, {
                abc_options: [
                  { label: "A", text: "Ela já fechou o salão e o buffet.", references_fact_ids: ["f1"] },
                  { label: "B", text: "Ela provou o bolo num casamento de amiga.", references_fact_ids: ["f1"] },
                  { label: "C", text: "Nenhuma das duas, prefiro explicar do meu jeito.", references_fact_ids: [] }
                ]
              })
            ],
            1200
          );
        } else {
          emit(
            [
              { type: "progress", session_id: SID, message: "Montando a síntese…" },
              {
                type: "deliverable",
                session_id: SID,
                kind: "layer_synthesis",
                layer_id: "clarity",
                content: {
                  content: {
                    "Uma leitura para você conferir":
                      "Quem prova o seu bolo na degustação lembra de um bolo de família, e uma noiva chorou na festa por isso. [fact:f1] Faz sentido pensar no seu trabalho como o bolo que tem a história da família da noiva?",
                    "O que você faz": "Você faz bolos de casamento, da degustação à montagem no salão. [fact:f1]",
                    "Lacunas e hipóteses": "Ainda não sabemos o que as noivas dizem depois da festa."
                  },
                  gaps: ["Percepção de quem compra não mapeada."],
                  hypotheses: []
                }
              },
              { type: "state", session_id: SID, status: "layer_review", active_layer: "clarity", layer_index: 1 },
              ...say(
                "Uma leitura para você conferir: Quem prova o seu bolo na degustação lembra de um bolo de família, e uma noiva chorou na festa por isso. Faz sentido pensar no seu trabalho como o bolo que tem a história da família da noiva?\n\nO mapa completo está ao lado. Ele está fiel ao que você vive, ou tem algo para ajustar?",
                3
              )
            ],
            2000
          );
        }
      }
    }
  };
}
