"use client";

/* Card "Minha assinatura" do perfil.

   Some por completo quando não há assinatura vigente (ou a chamada falha):
   quem nunca assinou não precisa de um vazio dizendo isso — a oferta já vive
   em `/assinatura`. */

import { useEffect, useState } from "react";
import { api, type ActiveMembership } from "@/lib/api";
import { AssinaturaResumo } from "@/components/assinatura/assinatura-resumo";
import { GhostLink } from "@/components/ui/buttons";

export function MinhaAssinatura() {
  const [assinatura, setAssinatura] = useState<ActiveMembership | null>(null);

  useEffect(() => {
    let cancelado = false;
    void (async () => {
      try {
        const atual = await api.minhaAssinatura();
        if (!cancelado) setAssinatura(atual);
      } catch {
        /* sem sessão/indisponível: a seção simplesmente não aparece */
      }
    })();
    return () => {
      cancelado = true;
    };
  }, []);

  if (!assinatura) return null;

  return (
    <section className="mt-8" aria-label="Minha assinatura">
      <h2 className="rotulo text-tinta-suave">Minha assinatura</h2>
      <div className="mt-3">
        <AssinaturaResumo assinatura={assinatura} />
      </div>
      <GhostLink href="/agendar">Usar minha assinatura</GhostLink>
    </section>
  );
}
