import type { PublicAppointment } from "@/lib/api";
import { AppointmentSummary } from "@/components/ui/appointment-summary";
import { GhostLink, SolidLink } from "@/components/ui/buttons";
import InstallBanner from "@/components/install-banner";
import AtivarNotificacoes from "@/components/ativar-notificacoes";

export function BookingSuccess({ done }: { done: PublicAppointment }) {
  return (
    <main className="mx-auto w-full max-w-md px-6 pb-16">
      <header className="pt-14 text-center">
        <p className="font-display text-5xl" aria-hidden>
          ✂️
        </p>
        <h1 className="mt-4 font-display text-3xl">Horário marcado!</h1>
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
