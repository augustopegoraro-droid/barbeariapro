/* Vitrine dos planos de assinatura/pacote (server component, zero JS).
   Cada cartão traz nome, preço, o que inclui e o CTA — que é o único pedaço
   client (`checkout-button.tsx`), porque precisa identificar o cliente. */

import type { MembershipPlanPublic } from "@/lib/api";
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

function PlanoCard({ plano }: { plano: MembershipPlanPublic }) {
  return (
    <article
      className="flex flex-col rounded-2xl border border-borda-sutil bg-superficie p-6"
      style={{ boxShadow: "var(--sombra-1)" }}
    >
      <h2 className="font-display text-2xl leading-tight text-marfim">
        {plano.name}
      </h2>
      {plano.description && (
        <p className="mt-2 text-sm text-tinta-suave">{plano.description}</p>
      )}

      <p className="mt-4 font-display text-3xl text-ouro tnum">
        {money(plano.price)}
      </p>
      <p className="text-sm text-tinta-fraca">por {vigencia(plano.duration_days)}</p>

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
      </ul>

      <div className="mt-6">
        <CheckoutButton planId={plano.id} planName={plano.name} />
      </div>
    </article>
  );
}

export function Planos({ planos }: { planos: MembershipPlanPublic[] }) {
  return (
    <div className="mt-8 grid gap-5 sm:grid-cols-2">
      {planos.map((p) => (
        <PlanoCard key={p.id} plano={p} />
      ))}
    </div>
  );
}
