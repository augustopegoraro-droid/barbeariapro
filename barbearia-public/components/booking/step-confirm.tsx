import type { RefObject } from "react";
import type { PublicProfessional, PublicService } from "@/lib/api";
import { AppointmentSummary } from "@/components/ui/appointment-summary";
import { IdentificacaoFields } from "@/components/ui/identificacao";
import { SolidButton, Spinner } from "@/components/ui/buttons";
import { BackButton } from "@/components/booking/back-button";
import { OfertaAssinatura } from "@/components/booking/oferta-assinatura";

export function StepConfirm({
  service,
  professional,
  slot,
  needsIdentify,
  knownName,
  name,
  phone,
  acceptPrivacy,
  submitting,
  error,
  onNameChange,
  onPhoneChange,
  onAcceptPrivacyChange,
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
  acceptPrivacy: boolean;
  submitting: boolean;
  error: string | null;
  onNameChange: (v: string) => void;
  onPhoneChange: (v: string) => void;
  onAcceptPrivacyChange: (v: boolean) => void;
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

      <OfertaAssinatura servicoId={service.id} />

      {needsIdentify ? (
        <form
          className="mt-6 space-y-4"
          onSubmit={(e) => {
            e.preventDefault();
            onConfirm();
          }}
        >
          <IdentificacaoFields
            idPrefix="agendar"
            name={name}
            phone={phone}
            acceptPrivacy={acceptPrivacy}
            onNameChange={onNameChange}
            onPhoneChange={onPhoneChange}
            onAcceptPrivacyChange={onAcceptPrivacyChange}
          />
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
