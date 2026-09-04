"use client";

/* Bump A (D-104 Fase 4) — order bump no checkout do agendamento: se o
   serviço escolhido é coberto pelo combo de um plano em destaque, oferece a
   assinatura antes de confirmar. Funciona sem sessão (o visitante pode ainda
   não estar identificado) — a API só não exclui quem já assina.

   Nunca bloqueia o fluxo: sem plano recomendado, o componente não renderiza
   nada; aceitar/recusar são só eventos de log (`membership_offer_events`),
   fire-and-forget. */

import { useEffect, useRef, useState } from "react";
import { api, type OfertaPlano } from "@/lib/api";
import { SolidLink } from "@/components/ui/buttons";
import { money } from "@/lib/format";

export function OfertaAssinatura({ servicoId }: { servicoId: number }) {
  const [oferta, setOferta] = useState<OfertaPlano | null>(null);
  const [dispensada, setDispensada] = useState(false);
  const logadoShown = useRef(false);

  useEffect(() => {
    let cancelado = false;
    setDispensada(false);
    logadoShown.current = false;
    api
      .oferta(servicoId)
      .then(({ plan }) => {
        if (!cancelado) setOferta(plan);
      })
      .catch(() => {
        // Bump é sempre opcional — falha ao buscar não deve travar a página.
      });
    return () => {
      cancelado = true;
    };
  }, [servicoId]);

  useEffect(() => {
    if (!oferta || logadoShown.current) return;
    logadoShown.current = true;
    api
      .registrarEventoOferta({
        outcome: "shown",
        plan_id: oferta.id,
        shown_amount: oferta.avulso_equivalente,
      })
      .catch(() => {});
  }, [oferta]);

  if (!oferta || dispensada) return null;

  const porUso = oferta.included_uses
    ? oferta.price / oferta.included_uses
    : null;

  return (
    <div
      className="mt-4 rounded-2xl border border-ouro/40 bg-ouro/5 p-4"
      style={{ boxShadow: "var(--sombra-1)" }}
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          {oferta.badge && (
            <span className="mb-1 inline-block rounded-full bg-ouro/10 px-2 py-0.5 text-xs font-medium text-ouro">
              {oferta.badge}
            </span>
          )}
          <p className="text-sm text-tinta">
            Você está pagando <span className="tnum font-medium">{money(oferta.avulso_equivalente)}</span> neste
            atendimento. No plano <span className="font-medium text-ouro">{oferta.name}</span>
            {porUso != null && (
              <>
                {" "}sai <span className="tnum">{money(porUso)}</span> por visita
              </>
            )}
            {oferta.headline && <> — {oferta.headline}</>}.
          </p>
        </div>
        <button
          type="button"
          aria-label="Dispensar oferta"
          className="shrink-0 text-tinta-fraca"
          onClick={() => {
            setDispensada(true);
            api
              .registrarEventoOferta({ outcome: "dismissed", plan_id: oferta.id })
              .catch(() => {});
          }}
        >
          ✕
        </button>
      </div>
      <SolidLink
        href={`/assinatura?plano=${oferta.id}`}
        size="inline"
        className="mt-3"
        onClick={() => {
          api
            .registrarEventoOferta({ outcome: "accepted", plan_id: oferta.id })
            .catch(() => {});
        }}
      >
        Assinar agora
      </SolidLink>
    </div>
  );
}
