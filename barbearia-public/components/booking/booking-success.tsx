"use client";

import { useEffect, useRef } from "react";

import type { PublicAppointment } from "@/lib/api";
import { AppointmentSummary } from "@/components/ui/appointment-summary";
import { GhostLink, SolidLink } from "@/components/ui/buttons";
import InstallBanner from "@/components/install-banner";
import AtivarNotificacoes from "@/components/ativar-notificacoes";

/* Redireciona para o WhatsApp depois de um respiro, para o cliente ver o
   "Horário marcado!" antes. O `<a>` fica visível como ação principal e como
   fallback (redirect bloqueado, sem WhatsApp, ou cliente voltou da conversa). */
const AUTO_REDIRECT_MS = 1800;

const SOLID_WA =
  "mt-6 inline-flex min-h-11 w-full items-center justify-center gap-2 rounded-xl bg-ouro px-6 py-4 text-lg font-semibold text-tinta-invertida transition-colors hover:bg-ouro-claro active:scale-[0.985]";

export function BookingSuccess({
  done,
  rescheduled = false,
  whatsappUrl,
}: {
  done: PublicAppointment;
  /* Veio de `?remarcar=`: o horário antigo foi cancelado na mesma transação
     que criou este — dizer "marcado" esconderia isso do cliente. */
  rescheduled?: boolean;
  /* Ausente = sem redirecionamento (só a tela de sucesso). */
  whatsappUrl?: string;
}) {
  const redirected = useRef(false);

  useEffect(() => {
    if (!whatsappUrl || redirected.current) return;
    const key = `wa-confirm-sent:${done.public_id}`;
    try {
      if (sessionStorage.getItem(key)) return; // já mandou; não redireciona de novo
    } catch {
      /* modo privado/sem storage: segue e redireciona uma vez via o ref */
    }
    redirected.current = true;
    const t = setTimeout(() => {
      try {
        sessionStorage.setItem(key, "1");
      } catch {
        /* ok */
      }
      window.location.href = whatsappUrl;
    }, AUTO_REDIRECT_MS);
    return () => clearTimeout(t);
  }, [whatsappUrl, done.public_id]);

  return (
    <main className="mx-auto w-full max-w-md px-6 pb-16">
      <header className="pt-14 text-center">
        <p className="font-display text-5xl" aria-hidden>
          ✂️
        </p>
        <h1 className="mt-4 font-display text-3xl">
          {rescheduled ? "Horário remarcado com sucesso" : "Horário marcado!"}
        </h1>
        {rescheduled && (
          <p className="mt-2 text-sm text-tinta-suave">
            O horário anterior foi cancelado.
          </p>
        )}
        {whatsappUrl && (
          <p className="mt-2 text-sm text-tinta-suave">
            Vamos te levar ao WhatsApp para confirmar — é só apertar enviar.
          </p>
        )}
      </header>
      <div className="mt-8">
        <AppointmentSummary
          serviceName={done.service_name}
          startAt={done.start_at}
          barberName={done.barber_name}
          price={done.total_amount}
        />
      </div>
      {whatsappUrl && (
        <a href={whatsappUrl} className={SOLID_WA} rel="noopener">
          Confirmar no WhatsApp
        </a>
      )}
      <AtivarNotificacoes />
      <InstallBanner />
      <div className="mt-8 flex flex-col items-center gap-3 text-center">
        <SolidLink href="/meus-agendamentos">Ver meus agendamentos</SolidLink>
        <GhostLink href="/">Voltar ao início</GhostLink>
      </div>
    </main>
  );
}
