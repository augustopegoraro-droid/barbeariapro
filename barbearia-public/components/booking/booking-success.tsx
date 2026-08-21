import type { PublicAppointment } from "@/lib/api";
import { AppointmentSummary } from "@/components/ui/appointment-summary";
import { GhostLink, SolidLink } from "@/components/ui/buttons";
import InstallBanner from "@/components/install-banner";
import AtivarNotificacoes from "@/components/ativar-notificacoes";

export function BookingSuccess({
  done,
  rescheduled = false,
}: {
  done: PublicAppointment;
  /* Veio de `?remarcar=`: o horário antigo foi cancelado na mesma transação
     que criou este — dizer "marcado" esconderia isso do cliente. */
  rescheduled?: boolean;
}) {
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
      </header>
      <div className="mt-8">
        <AppointmentSummary
          serviceName={done.service_name}
          startAt={done.start_at}
          barberName={done.barber_name}
          price={done.total_amount}
        />
      </div>
      <AtivarNotificacoes />
      <InstallBanner />
      <div className="mt-8 flex flex-col items-center gap-3 text-center">
        <SolidLink href="/meus-agendamentos">Ver meus agendamentos</SolidLink>
        <GhostLink href="/">Voltar ao início</GhostLink>
      </div>
    </main>
  );
}
