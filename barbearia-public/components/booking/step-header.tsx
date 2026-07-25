/* Stepper do fluxo (UI_SPEC_V3 §2 item 7): ativo = ouro sólido, concluído =
   ouro/45 (lê mais que o futuro sem competir com o ativo), futuro =
   superfície-3. `aria-current="step"` no ativo. */

import Link from "next/link";
import { Wordmark } from "@/components/wordmark";
import type { Step } from "@/components/booking/types";

const STEP_LABELS = ["Serviço", "Profissional", "Horário", "Confirmar"];

export function StepHeader({ step }: { step: Step }) {
  return (
    <header className="pt-6 pb-4">
      <Link
        href="/"
        className="inline-flex min-h-11 items-center gap-2 text-sm text-tinta-fraca transition-colors hover:text-tinta-suave"
      >
        <span aria-hidden>←</span>
        <Wordmark fontSize={15} />
      </Link>
      <ol className="mt-4 flex gap-1" aria-label="Etapas do agendamento">
        {STEP_LABELS.map((label, i) => (
          <li
            key={label}
            className="flex-1"
            aria-current={i + 1 === step ? "step" : undefined}
          >
            <div
              className={`h-1 rounded-full ${
                i + 1 === step
                  ? "bg-ouro"
                  : i + 1 < step
                    ? "bg-ouro/45"
                    : "bg-superficie-3"
              }`}
              aria-hidden
            />
            <span
              className={`mt-1 block text-[11px] ${
                i + 1 === step
                  ? "font-medium text-ouro"
                  : i + 1 < step
                    ? "text-tinta-suave"
                    : "text-tinta-fraca"
              }`}
            >
              {label}
            </span>
          </li>
        ))}
      </ol>
    </header>
  );
}
