"use client";

import type { Synthesis } from "@/lib/journey";
import { NEXT_STEPS, resultView } from "@/lib/result";

export function ResultPage({
  synthesis,
  business,
  baseline,
  onBack,
}: {
  synthesis: Synthesis;
  business: string | null;
  baseline: string | null;
  onBack: () => void;
}) {
  const view = resultView(synthesis);
  const today = new Date().toLocaleDateString("pt-BR", {
    day: "numeric",
    month: "long",
    year: "numeric",
  });

  return (
    <div className="result">
      <header className="result-bar">
        <strong>Valor Visível</strong>
        <div className="result-actions">
          <button className="ghost" onClick={onBack}>
            Voltar à conversa
          </button>
          <button className="primary" onClick={() => window.print()}>
            Salvar em PDF
          </button>
        </div>
      </header>

      <div className="result-main">
        <section className="result-hero">
          <p className="eyebrow">Mapa de Clareza aprovado · {today}</p>
          <h1>{business ?? "O seu negócio"}</h1>
          <p className="result-sub">
            O que a conversa mostrou sobre o seu trabalho, com as suas palavras.
            Cada frase vem do que você contou.
          </p>
          {view.reading && (
            <blockquote className="result-reading">{view.reading}</blockquote>
          )}
        </section>

        {(baseline || view.contrast) && (
          <section className="result-compare" aria-label="Antes e depois">
            <div className="compare-col before">
              <p className="compare-label">Como você se apresenta hoje</p>
              <p className="compare-text">
                {baseline
                  ? `“${baseline}”`
                  : "Você ainda não contou como se apresenta."}
              </p>
            </div>
            <div className="compare-arrow" aria-hidden>
              →
            </div>
            <div className="compare-col after">
              <p className="compare-label">O que a conversa mostrou</p>
              <p className="compare-text">{view.contrast ?? view.reading}</p>
            </div>
          </section>
        )}

        {view.cards.length > 0 && (
          <section className="result-cards">
            {view.cards.map((card) => (
              <article key={card.title} className="result-card">
                <h2>{card.title}</h2>
                <p>{card.text}</p>
              </article>
            ))}
          </section>
        )}

        {(view.leads.length > 0 || view.gaps.length > 0) && (
          <section className="result-open">
            {view.leads.length > 0 && (
              <div>
                <h2>Pistas para aprofundar</h2>
                <ol>
                  {view.leads.map((lead) => (
                    <li key={lead}>{lead}</li>
                  ))}
                </ol>
              </div>
            )}
            {view.gaps.length > 0 && (
              <div>
                <h2>O que ainda vamos confirmar</h2>
                <ul>
                  {view.gaps.map((gap) => (
                    <li key={gap}>{gap}</li>
                  ))}
                </ul>
              </div>
            )}
          </section>
        )}

        <section className="result-journey">
          <h2>A sua jornada</h2>
          <p className="result-sub">
            Esta é a primeira parte. Na jornada completa, cada etapa parte deste
            mapa até chegar ao Núcleo Essencial.
          </p>
          <ol className="journey-steps">
            <li className="done">
              <span className="step-mark">✓</span>
              <div>
                <strong>Nitidez</strong>
                <p>
                  o que você faz, para quem e o que fica de fora quando você se
                  apresenta
                </p>
              </div>
            </li>
            {NEXT_STEPS.map((step) => (
              <li
                key={step.name}
                className={
                  step.name === "Núcleo Essencial" ? "core" : undefined
                }
              >
                <span className="step-mark" />
                <div>
                  <strong>{step.name}</strong>
                  <p>{step.delivers}</p>
                </div>
              </li>
            ))}
          </ol>
        </section>

        <footer className="result-foot">
          Prévia do resultado final do Valor Visível, montada só com a primeira
          parte da jornada.
        </footer>
      </div>
    </div>
  );
}
