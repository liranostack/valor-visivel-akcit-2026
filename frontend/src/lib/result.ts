// Result page (A.04.11): the approved Clarity Map shown as a preview of the journey's final
// deliverable. Only what the session produced is shown; later layers appear as next steps.
import type { Synthesis } from "./journey";

export const READING = "Uma leitura para você conferir";
export const CONTRAST = "O que você conta e o que fica de fora";
export const LEADS = "Para investigar na próxima etapa";
const HIDDEN = new Set([READING, CONTRAST, LEADS, "Lacunas e hipóteses"]);

export interface ResultView {
  reading: string | null;
  contrast: string | null;
  cards: { title: string; text: string }[];
  leads: string[];
  gaps: string[];
}

export const NEXT_STEPS: { name: string; delivers: string }[] = [
  {
    name: "Singularidade",
    delivers: "o que só você faz, comparado e sustentado",
  },
  {
    name: "Tradução",
    delivers: "as palavras de quem compra virando a sua mensagem",
  },
  {
    name: "Sustentação",
    delivers: "as provas e os limites que tornam a promessa cumprível",
  },
  {
    name: "Núcleo Essencial",
    delivers: "sua proposta de valor, o antes e depois e um plano de 7 dias",
  },
];

/** A section that says it has nothing yet is left out of the page. */
export function hasContent(text: string | undefined | null): text is string {
  const clean = (text ?? "").trim();
  return (
    clean.length > 0 &&
    !/^ainda não sabemos/i.test(clean) &&
    !/^nada em aberto/i.test(clean)
  );
}

function bullets(text: string): string[] {
  return text
    .split(/\n+/)
    .map((line) => line.replace(/^\s*([-*•]|\d+[.)])\s*/, "").trim())
    .filter(hasContent);
}

export function resultView(synthesis: Synthesis): ResultView {
  const byTitle = new Map(
    synthesis.sections.map((s) => [s.title, s.markdown.replace(/\*\*/g, "")]),
  );
  const pick = (title: string) => {
    const text = byTitle.get(title);
    return hasContent(text) ? text.trim() : null;
  };
  return {
    reading: pick(READING),
    contrast: pick(CONTRAST),
    cards: synthesis.sections
      .filter((s) => !HIDDEN.has(s.title))
      .map((s) => ({
        title: s.title,
        text: s.markdown.replace(/\*\*/g, "").trim(),
      }))
      .filter((s) => hasContent(s.text)),
    leads: bullets(byTitle.get(LEADS) ?? ""),
    gaps: synthesis.gaps.filter(hasContent),
  };
}
