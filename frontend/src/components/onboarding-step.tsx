"use client";

import { useState } from "react";
import type { OnboardingStepEvent } from "@/lib/protocol";

interface Props {
  step: OnboardingStepEvent;
  onConsent: (accepted: boolean, label: string) => void;
  onAnswer: (value: string | string[], shown: string) => void;
}

export function OnboardingStep({ step, onConsent, onAnswer }: Props) {
  const [picked, setPicked] = useState<string[]>([]);
  const [text, setText] = useState("");

  if (step.field === "consent") {
    return (
      <div className="choice-panel">
        <p className="question">{step.question}</p>
        <div className="choice-list">
          {step.options.map((option, i) => (
            <button
              key={option}
              className="choice"
              onClick={() => onConsent(i === 0, option)}
            >
              {option}
            </button>
          ))}
        </div>
      </div>
    );
  }

  const toggle = (option: string) =>
    setPicked((current) =>
      current.includes(option)
        ? current.filter((o) => o !== option)
        : [...current, option],
    );

  const submit = (value: string | string[]) => {
    const shown = Array.isArray(value) ? value.join(", ") : value;
    if (!shown.trim()) return;
    onAnswer(value, shown);
    setPicked([]);
    setText("");
  };

  return (
    <div className="choice-panel">
      {step.field !== "baseline" && (
        <span className="step-count">
          Pergunta {step.step} de {step.total}
        </span>
      )}
      <p className="question">{step.question}</p>
      {step.options.length > 0 && (
        <div className="choice-list">
          {step.options.map((option) =>
            step.multiple ? (
              <button
                key={option}
                className="choice"
                aria-pressed={picked.includes(option)}
                onClick={() => toggle(option)}
              >
                {option}
              </button>
            ) : (
              <button
                key={option}
                className="choice"
                onClick={() => submit(option)}
              >
                {option}
              </button>
            ),
          )}
        </div>
      )}
      {step.multiple && (
        <div className="actions">
          <button
            className="primary"
            disabled={!picked.length}
            onClick={() => submit(picked)}
          >
            Continuar
          </button>
        </div>
      )}
      {step.free_text && (
        <div className="free-text-row">
          <input
            value={text}
            placeholder={
              step.options.length ? "Ou escreva do seu jeito" : "Escreva aqui"
            }
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && submit(text)}
            aria-label={step.question}
          />
          <button
            className="primary"
            disabled={!text.trim()}
            onClick={() => submit(text)}
          >
            Enviar
          </button>
        </div>
      )}
    </div>
  );
}
