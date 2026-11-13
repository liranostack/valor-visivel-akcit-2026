import type { Synthesis } from "@/lib/journey";
import { LAYER_NAMES } from "@/lib/journey";

export function SynthesisCard({
  synthesis,
  onApprove,
  onShowResult,
}: {
  synthesis: Synthesis;
  onApprove?: () => void;
  onShowResult?: () => void;
}) {
  const name = synthesis.layerId ? LAYER_NAMES[synthesis.layerId] : "Camada";
  return (
    <div className="card synthesis">
      <div className="header">
        <strong>
          {name === "Nitidez" ? "Mapa de Clareza" : `Síntese · ${name}`}
        </strong>
      </div>
      <div className="content">
        {synthesis.sections.map((section) => (
          <section key={section.title}>
            <h3>{section.title}</h3>
            <p>{section.markdown.replace(/\*\*/g, "")}</p>
          </section>
        ))}
        {onApprove && (
          <div className="review">
            <p>
              Antes de seguir, confira o mapa. Ele está fiel ao que você contou?
            </p>
            <button className="primary" onClick={onApprove}>
              Está fiel, aprovar
            </button>
            <p className="hint">
              Se algo não estiver fiel, escreva o que ajustar no campo da
              conversa.
            </p>
          </div>
        )}
        {onShowResult && (
          <div className="review">
            <button className="primary" onClick={onShowResult}>
              Ver o resultado
            </button>
          </div>
        )}
        {synthesis.gaps.length > 0 && (
          <section className="gaps">
            <h3>O que ainda não sabemos</h3>
            {synthesis.gaps.map((gap) => (
              <p key={gap}>{gap}</p>
            ))}
          </section>
        )}
      </div>
    </div>
  );
}
