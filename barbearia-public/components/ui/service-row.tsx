/* Linha/cartão de serviço (UI_SPEC_V2 §2 item 3).
   - Home: linha tocável sem caixa (lista com divide-borda-sutil) com chevron →
     /agendar?servico={id} (UX A6).
   - Passo 1: cartão branco com sombra + fio (§1.6). */

import Link from "next/link";
import type { PublicService } from "@/lib/api";
import { money } from "@/lib/format";

function ServiceInfo({ service }: { service: PublicService }) {
  return (
    <span>
      <span className="block font-medium text-tinta">{service.name}</span>
      <span className="block text-sm text-tinta-fraca">
        {service.duration_min} min
      </span>
    </span>
  );
}

export function ServiceLinkRow({ service }: { service: PublicService }) {
  return (
    <Link
      href={`/agendar?servico=${service.id}`}
      className="flex min-h-14 items-center justify-between gap-4 py-3 transition-colors hover:bg-superficie-2/60"
    >
      <ServiceInfo service={service} />
      <span className="flex items-center gap-2">
        <span className="font-display text-lg text-tinta tnum">
          {money(service.price)}
        </span>
        <span aria-hidden className="text-tinta-fraca">
          ›
        </span>
      </span>
    </Link>
  );
}

export function ServiceCardButton({
  service,
  onSelect,
}: {
  service: PublicService;
  onSelect: () => void;
}) {
  return (
    <button
      onClick={onSelect}
      className="flex w-full items-baseline justify-between gap-4 rounded-xl border border-borda-sutil bg-superficie px-4 py-4 text-left transition-colors hover:bg-superficie-2 active:scale-[0.99]"
      style={{ boxShadow: "var(--sombra-1)" }}
    >
      <ServiceInfo service={service} />
      <span className="font-display text-lg text-tinta tnum">
        {money(service.price)}
      </span>
    </button>
  );
}
