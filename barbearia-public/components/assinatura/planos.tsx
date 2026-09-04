"use client";

/* Vitrine dos planos de assinatura/pacote. Client component: o toggle de
   público (Masculino/Feminino/Todos) e a escolha de add-ons (Bump C) do plano
   em destaque exigem estado no browser — o único pedaço que de fato precisa
   de JS além do CTA (`checkout-button.tsx`, que já era client). */

import { useMemo, useState } from "react";
import type { MembershipAddonPublic, MembershipPlanPublic } from "@/lib/api";
import { money } from "@/lib/format";
import { CheckoutButton } from "@/components/assinatura/checkout-button";

function vigencia(dias: number): string {
  if (dias % 365 === 0) {
    const anos = dias / 365;
    return anos === 1 ? "1 ano" : `${anos} anos`;
  }
  if (dias % 30 === 0) {
    const meses = dias / 30;
    return meses === 1 ? "1 mês" : `${meses} meses`;
  }
  return `${dias} dias`;
}

function usos(inclusos: number | null): string {
  if (inclusos === null) return "Usos ilimitados na vigência";
  return inclusos === 1 ? "1 uso incluso" : `${inclusos} usos inclusos`;
}

const AUDIENCIA_LABEL: Record<string, string> = {
  todos: "Todos",
  masculino: "Masculino",
  feminino: "Feminino",
};

function AddonPicker({
  addons,
  selecionados,
  onToggle,
}: {
  addons: MembershipAddonPublic[];
  selecionados: Set<number>;
  onToggle: (id: number) => void;
}) {
  if (addons.length === 0) return null;
  return (
    <div className="mt-4 space-y-2 border-t border-borda-sutil pt-4">
      <p className="text-xs uppercase tracking-wide text-tinta-fraca">
        Adicione ao plano
      </p>
      {addons.map((a) => (
        <label
          key={a.id}
          className="flex min-h-11 cursor-pointer items-center justify-between gap-3 text-sm text-tinta-suave"
        >
          <span className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={selecionados.has(a.id)}
              onChange={() => onToggle(a.id)}
              className="h-4 w-4 accent-ouro"
            />
            {a.name}
          </span>
          <span className="tnum text-tinta-fraca">+{money(a.price)}/mês</span>
        </label>
      ))}
    </div>
  );
}

function PlanoCard({ plano }: { plano: MembershipPlanPublic }) {
  const [selecionados, setSelecionados] = useState<Set<number>>(new Set());
  const toggleAddon = (id: number) =>
    setSelecionados((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const economia = plano.avulso_equivalente - plano.price;

  return (
    <article
      className="flex flex-col rounded-2xl border border-borda-sutil bg-superficie p-6"
      style={{ boxShadow: "var(--sombra-1)" }}
    >
      {plano.badge && (
        <span className="mb-2 inline-block w-fit rounded-full border border-ouro/40 bg-ouro/10 px-3 py-1 text-xs font-medium text-ouro">
          {plano.badge}
        </span>
      )}
      <h2 className="font-display text-2xl leading-tight text-marfim">
        {plano.name}
      </h2>
      {plano.headline && (
        <p className="mt-1 text-sm text-ouro">{plano.headline}</p>
      )}
      {plano.description && (
        <p className="mt-2 text-sm text-tinta-suave">{plano.description}</p>
      )}

      <p className="mt-4 font-display text-3xl text-ouro tnum">
        {money(plano.price)}
      </p>
      <p className="text-sm text-tinta-fraca">por {vigencia(plano.duration_days)}</p>
      {economia > 0.01 && (
        <p className="mt-1 text-sm text-tinta-suave">
          Você economiza <span className="tnum text-ouro">{money(economia)}</span> por
          ciclo em relação ao avulso
        </p>
      )}

      <ul className="mt-5 space-y-2 text-sm text-tinta-suave">
        <li className="flex gap-2">
          <span aria-hidden className="text-ouro">
            ·
          </span>
          {usos(plano.included_uses)}
        </li>
        {plano.services.map((s, i) => (
          <li key={`${s}-${i}`} className="flex gap-2">
            <span aria-hidden className="text-ouro">
              ·
            </span>
            {s}
          </li>
        ))}
        {plano.perks.map((p, i) => (
          <li key={`perk-${i}`} className="flex gap-2">
            <span aria-hidden className="text-ouro">
              ·
            </span>
            {p}
          </li>
        ))}
      </ul>

      {plano.is_featured && (
        <AddonPicker
          addons={plano.addons}
          selecionados={selecionados}
          onToggle={toggleAddon}
        />
      )}

      <div className="mt-6">
        <CheckoutButton
          planId={plano.id}
          planName={plano.name}
          addonIds={Array.from(selecionados)}
        />
      </div>
    </article>
  );
}

export function Planos({ planos }: { planos: MembershipPlanPublic[] }) {
  const audiencias = useMemo(() => {
    const presentes = new Set(planos.map((p) => p.audience));
    // Só mostra o toggle quando há de fato mais de um público na vitrine —
    // uma barbearia com só planos unissex não precisa dele.
    return presentes.size > 1 || (presentes.size === 1 && !presentes.has("unissex"))
      ? (["todos", "masculino", "feminino"] as const)
      : null;
  }, [planos]);
  const [filtro, setFiltro] = useState<"todos" | "masculino" | "feminino">("todos");

  const visiveis = planos.filter(
    (p) => filtro === "todos" || p.audience === filtro || p.audience === "unissex",
  );

  return (
    <div className="mt-8">
      {audiencias && (
        <div className="mb-6 flex gap-2" role="tablist" aria-label="Filtrar por público">
          {audiencias.map((a) => (
            <button
              key={a}
              role="tab"
              aria-selected={filtro === a}
              onClick={() => setFiltro(a)}
              className={`min-h-11 rounded-full border px-4 text-sm transition-colors ${
                filtro === a
                  ? "border-ouro bg-ouro/10 text-ouro"
                  : "border-borda-sutil text-tinta-suave"
              }`}
            >
              {AUDIENCIA_LABEL[a]}
            </button>
          ))}
        </div>
      )}
      <div className="grid gap-5 sm:grid-cols-2">
        {visiveis.map((p) => (
          <PlanoCard key={p.id} plano={p} />
        ))}
      </div>
    </div>
  );
}
