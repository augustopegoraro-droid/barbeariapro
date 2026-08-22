/* Resumo de uma assinatura vigente — saldo de usos, vigência e combo.
   Compartilhado entre a página de sucesso do checkout e o card do perfil. */

import type { ActiveMembership } from "@/lib/api";

function data(iso: string): string {
  return new Date(iso).toLocaleDateString("pt-BR", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
}

export function AssinaturaResumo({
  assinatura,
}: {
  assinatura: ActiveMembership;
}) {
  const { included_uses, used_uses } = assinatura;
  const restantes = included_uses === null ? null : included_uses - used_uses;

  return (
    <div
      className="rounded-2xl border border-borda-sutil bg-superficie p-5"
      style={{ boxShadow: "var(--sombra-1)" }}
    >
      <p className="font-display text-xl text-marfim">
        {assinatura.plan_name ?? "Pacote personalizado"}
      </p>

      <p className="mt-2 text-sm text-tinta-suave tnum">
        {restantes === null
          ? "Usos ilimitados na vigência"
          : `${restantes} de ${included_uses} ${
              included_uses === 1 ? "uso disponível" : "usos disponíveis"
            }`}
      </p>
      <p className="text-sm text-tinta-fraca tnum">
        Válido até {data(assinatura.end_at)}
      </p>

      {assinatura.services.length > 0 && (
        <ul className="mt-4 space-y-1 text-sm text-tinta-suave">
          {assinatura.services.map((s, i) => (
            <li key={`${s}-${i}`} className="flex gap-2">
              <span aria-hidden className="text-ouro">
                ·
              </span>
              {s}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
