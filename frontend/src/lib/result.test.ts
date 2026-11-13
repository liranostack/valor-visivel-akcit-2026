import { describe, expect, it } from "vitest";
import type { Synthesis } from "./journey";
import { CONTRAST, LEADS, READING, hasContent, resultView } from "./result";

const MAP: Synthesis = {
  layerId: "clarity",
  sections: [
    {
      title: READING,
      markdown:
        "Você confere a massa antes de cada fornada. Faz sentido pensar nisso?",
    },
    {
      title: CONTRAST,
      markdown: "Você se apresenta pelos sabores; a conferência fica de fora.",
    },
    { title: "O que você faz", markdown: "Empanadas assadas por encomenda." },
    { title: "Como você faz", markdown: "Ainda não sabemos." },
    {
      title: "O que quem compra percebe, segundo você",
      markdown: "Uma cliente disse que **nunca** chega fria.",
    },
    {
      title: LEADS,
      markdown:
        "- A conferência da massa\n- O horário de entrega\n- Ainda não sabemos.",
    },
    { title: "Lacunas e hipóteses", markdown: "Nada em aberto." },
  ],
  gaps: ["Não sabemos o que outras clientes dizem.", "Ainda não sabemos."],
  hypotheses: [],
};

describe("result page", () => {
  it("puts the reading and the contrast apart from the cards", () => {
    const view = resultView(MAP);
    expect(view.reading).toContain("confere a massa");
    expect(view.contrast).toContain("sabores");
    expect(view.cards.map((c) => c.title)).toEqual([
      "O que você faz",
      "O que quem compra percebe, segundo você",
    ]);
  });

  it("leaves out what the map says it does not know yet", () => {
    const view = resultView(MAP);
    expect(view.cards.some((c) => c.title === "Como você faz")).toBe(false);
    expect(view.leads).toEqual([
      "A conferência da massa",
      "O horário de entrega",
    ]);
    expect(view.gaps).toEqual(["Não sabemos o que outras clientes dizem."]);
  });

  it("drops markdown bold", () => {
    expect(resultView(MAP).cards[1].text).toBe(
      "Uma cliente disse que nunca chega fria.",
    );
  });

  it("a map without a reading has none", () => {
    const view = resultView({ ...MAP, sections: MAP.sections.slice(2) });
    expect(view.reading).toBeNull();
    expect(hasContent("  ")).toBe(false);
  });
});
