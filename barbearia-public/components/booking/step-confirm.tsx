import type { RefObject } from "react";
import type { PublicProfessional, PublicService } from "@/lib/api";
import { maskPhone } from "@/lib/format";
import { AppointmentSummary } from "@/components/ui/appointment-summary";
import { SolidButton, Spinner } from "@/components/ui/buttons";
import { BackButton } from "@/components/booking/back-button";

export function StepConfirm({
  service,
  professional,
  slot,
  needsIdentify,
  knownName,
  name,
  phone,
  submitting,
  error,
  onNameChange,
  onPhoneChange,
  onForget,
  onConfirm,
  onBack,
  headingRef,
}: {
  service: PublicService;
  professional: PublicProfessional;
  slot: string;
  needsIdentify: boolean;
  knownName: string | null;
  name: string;
  phone: string;
  submitting: boolean;
  error: string | null;
  onNameChange: (v: string) => void;
  onPhoneChange: (v: string) => void;
  onForget: () => void;
  onConfirm: () => void;
  onBack: () => void;
  headingRef: RefObject<HTMLHeadingElement | null>;
}) {
  return (
    <section aria-label="Confirme seu agendamento">
      <h1
        ref={headingRef}
        tabIndex={-1}
        className="font-display text-2xl outline-none"
      >
        Confirme
      </h1>
      <div className="mt-4">
        <AppointmentSummary
          serviceName={service.name}
          startAt={slot}
          barberName={professional.name}
          price={service.price}
        />
      </div>

      {needsIdentify ? (
        <form
          className="mt-6 space-y-4"
          onSubmit={(e) => {
            e.preventDefault();
            onConfirm();
          }}
        >
          <div>
            <label htmlFor="nome" className="block text-sm font-medium text-tinta">
              Seu nome
            </label>
            <input
              id="nome"
              value={name}
              onChange={(e) => onNameChange(e.target.value)}
              autoComplete="name"
              required
              minLength={2}
              className="mt-1 w-full rounded-lg border border-borda bg-superficie px-3 py-3 text-tinta transition-colors placeholder:text-tinta-fraca focus:border-borda-ativa"
              placeholder="Como podemos te chamar"
            />
          </div>
          <div>
            <label htmlFor="telefone" className="block text-sm font-medium text-tinta">
              WhatsApp / celular
            </label>
            <input
              id="telefone"
              value={phone}
              onChange={(e) => onPhoneChange(maskPhone(e.target.value))}
              inputMode="tel"
              autoComplete="tel-national"
              required
              className="mt-1 w-full rounded-lg border border-borda bg-superficie px-3 py-3 text-tinta tnum transition-colors placeholder:text-tinta-fraca focus:border-borda-ativa"
              placeholder="(63) 99999-9999"
            />
            <p className="mt-1 text-xs text-tinta-suave">
              Usamos seu número para confirmar e lembrar do horário.
            </p>
          </div>
          {error && (
            <p role="alert" className="text-sm text-vermelho-tinta">
              {error}
            </p>
          )}
          <SolidButton type="submit" disabled={submitting}>
            {submitting && <Spinner />}
            {submitting ? "Agendando…" : "Confirmar agendamento"}
          </SolidButton>
        </form>
      ) : (
        <div className="mt-6 space-y-4">
          <p className="text-tinta-suave">
            Agendando como <span className="font-medium text-tinta">{knownName}</span>{" "}
            <button
              className="inline-flex min-h-11 items-center text-sm text-tinta-fraca underline underline-offset-4"
              onClick={onForget}
            >
              não é você?
            </button>
          </p>
          {error && (
            <p role="alert" className="text-sm text-vermelho-tinta">
              {error}
            </p>
          )}
          <SolidButton onClick={onConfirm} disabled={submitting}>
            {submitting && <Spinner />}
            {submitting ? "Agendando…" : "Confirmar agendamento"}
          </SolidButton>
        </div>
      )}
      <BackButton onClick={onBack} />
    </section>
  );
}
