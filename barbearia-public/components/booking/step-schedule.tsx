/* Passo 3 — dia + horário (tratamento claro: UI_SPEC_V2 §2 itens 5-6).
   - Régua de dias: botões com `aria-pressed` (a semântica tab/tablist anterior
     era incorreta), scroll-snap, dia de hoje com ponto navy, dia FECHADO
     desabilitado usando `info.hours` (UX A2) — sem chamada extra ao backend.
   - Grade de slots: alvos ≥44px, 5 colunas a partir de 420px, resultado
     anunciado via `aria-live`; seleção/hover = navy.
   - Volta por 409 (UX A1): banner visível no topo da grade + o horário que
     falhou, se ainda listado, aparece indisponível (riscado). */

import { useEffect, useRef } from "react";
import type { RefObject } from "react";
import type { PublicProfessional, PublicService } from "@/lib/api";
import { dayNumber, monthShort, timeHM, weekdayShort } from "@/lib/format";
import { Notice } from "@/components/ui/notice";
import { BackButton } from "@/components/booking/back-button";

export function StepSchedule({
  service,
  professional,
  days,
  dayOffset,
  closedWeekday,
  slots,
  slotsError,
  conflict,
  conflictSlot,
  onSelectDay,
  onSelectSlot,
  onRetry,
  onBack,
  headingRef,
}: {
  service: PublicService;
  professional: PublicProfessional;
  days: Date[];
  dayOffset: number;
  /** null = horários desconhecidos (visibilidade oculta) → nenhum dia é bloqueado */
  closedWeekday: ((d: Date) => boolean) | null;
  slots: string[] | null;
  slotsError: string | null;
  conflict: boolean;
  conflictSlot: string | null;
  onSelectDay: (offset: number) => void;
  onSelectSlot: (slot: string) => void;
  onRetry: () => void;
  onBack: () => void;
  headingRef: RefObject<HTMLHeadingElement | null>;
}) {
  const stripRef = useRef<HTMLDivElement>(null);

  // Dia selecionado rola para ficar totalmente visível (§2.5).
  useEffect(() => {
    const el = stripRef.current?.querySelector<HTMLElement>(
      '[aria-pressed="true"]',
    );
    el?.scrollIntoView({ inline: "nearest", block: "nearest" });
  }, [dayOffset]);

  const groupedSlots = groupByPeriod(slots);

  return (
    <section aria-label="Escolha o horário">
      <h1
        ref={headingRef}
        tabIndex={-1}
        className="font-display text-2xl outline-none"
      >
        Escolha o horário
      </h1>
      <p className="mt-1 text-sm text-tinta-suave">
        {service.name} · {professional.name}
      </p>

      {conflict && (
        <div className="mt-4">
          <Notice kind="aviso">
            Esse horário acabou de ser reservado por outra pessoa. Escolha outro
            — a lista já está atualizada.
          </Notice>
        </div>
      )}

      <div className="mt-4 -mx-6 overflow-x-auto px-6">
        <div
          ref={stripRef}
          role="group"
          aria-label="Escolha o dia"
          className="flex gap-2 pb-2"
          style={{ scrollSnapType: "x proximity" }}
        >
          {days.map((d, i) => {
            const closed = closedWeekday ? closedWeekday(d) : false;
            const selected = i === dayOffset;
            return (
              <button
                key={i}
                aria-pressed={selected}
                disabled={closed}
                onClick={() => onSelectDay(i)}
                style={{
                  scrollSnapAlign: "start",
                  ...(selected ? { boxShadow: "var(--sombra-1)" } : undefined),
                }}
                className={`flex min-h-16 min-w-[3.5rem] flex-col items-center rounded-xl border px-2 py-2 text-sm transition-colors ${
                  selected
                    ? "border-transparent bg-ouro font-semibold text-tinta-invertida"
                    : closed
                      ? "border-borda-sutil bg-superficie text-tinta-fraca opacity-50"
                      : "border-borda-sutil bg-superficie text-tinta-suave hover:bg-superficie-2"
                }`}
              >
                <span className="text-[11px] uppercase tracking-[0.08em]">
                  {weekdayShort(d)}
                </span>
                <span className="font-display text-lg tnum">{dayNumber(d)}</span>
                {closed ? (
                  <span className="text-[10px] uppercase">Fechado</span>
                ) : (
                  <span className="flex flex-col items-center text-[10px] uppercase">
                    {monthShort(d)}
                    {i === 0 && !selected && (
                      <span
                        aria-hidden
                        className="mt-0.5 h-1 w-1 rounded-full bg-tinta-invertida"
                      />
                    )}
                  </span>
                )}
              </button>
            );
          })}
        </div>
      </div>

      {/* Resultado da busca anunciado ao leitor de tela */}
      <p aria-live="polite" className="sr-only">
        {slots === null
          ? "Carregando horários"
          : slots.length === 0
            ? "Nenhum horário disponível neste dia"
            : `${slots.length} horários disponíveis`}
      </p>

      {slots === null && !slotsError && (
        <p className="mt-6 text-tinta-suave">Buscando horários…</p>
      )}
      {slotsError && (
        <p className="mt-6 text-vermelho-tinta">
          {slotsError}{" "}
          <button
            className="inline-flex min-h-11 items-center underline"
            onClick={onRetry}
          >
            Tentar de novo
          </button>
        </p>
      )}
      {slots !== null && slots.length === 0 && (
        <p className="mt-6 text-tinta-suave">
          Sem horários livres neste dia. Escolha outro dia acima.
        </p>
      )}
      {groupedSlots &&
        Object.entries(groupedSlots).map(([label, list]) =>
          list.length === 0 ? null : (
            <div key={label} className="mt-5">
              <h2 className="text-sm font-medium uppercase tracking-wide text-tinta-fraca">
                {label}
              </h2>
              <div className="mt-2 grid grid-cols-4 gap-2 min-[420px]:grid-cols-5">
                {list.map((s) =>
                  s === conflictSlot ? (
                    <span
                      key={s}
                      aria-disabled="true"
                      className="flex min-h-11 items-center justify-center rounded-lg border border-borda bg-transparent px-2 py-2.5 text-center font-medium text-tinta-fraca/60 line-through tnum"
                    >
                      {timeHM(s)}
                    </span>
                  ) : (
                    <button
                      key={s}
                      onClick={() => onSelectSlot(s)}
                      className="min-h-11 rounded-lg border border-borda-sutil bg-superficie px-2 py-2.5 text-center font-medium text-marfim tnum transition-colors hover:border-ouro hover:bg-ouro hover:text-tinta-invertida"
                    >
                      {timeHM(s)}
                    </button>
                  ),
                )}
              </div>
            </div>
          ),
        )}
      <BackButton onClick={onBack} />
    </section>
  );
}

function groupByPeriod(slots: string[] | null) {
  if (!slots) return null;
  const groups: Record<string, string[]> = { Manhã: [], Tarde: [], Noite: [] };
  for (const s of slots) {
    const h = parseInt(timeHM(s).slice(0, 2), 10);
    if (h < 12) groups["Manhã"].push(s);
    else if (h < 18) groups["Tarde"].push(s);
    else groups["Noite"].push(s);
  }
  return groups;
}
