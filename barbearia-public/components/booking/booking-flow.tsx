"use client";

/* Orquestrador do fluxo de agendamento em 4 passos (mobile-first):
   serviço → profissional → dia/horário → identificação + confirmação.
   Estado centralizado aqui; os passos são componentes de apresentação
   (components/booking/step-*.tsx — decomposição do FRONTEND_AUDIT §6).

   Sessão: cookie HttpOnly (o JS não enxerga) — guardamos só o nome em
   localStorage como memória de UX. Se a API devolver 401 no agendamento,
   voltamos ao passo de identificação e refazemos a sessão.

   P0 desta rodada (UX_PLAN §6):
   - A1: 409 volta ao passo 3 com banner VISÍVEL + slot que falhou riscado;
   - A6: `?servico={id}` pré-seleciona o serviço e abre no passo 2
     (lido de window.location.search — convenção do projeto p/ client);
   - A2: dias fechados desabilitados na régua via `info.hours`;
   - foco move para o h1 a cada troca de passo (§5.3). */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  api,
  ApiError,
  type PublicAppointment,
  type PublicInfo,
  type PublicProfessional,
  type PublicService,
} from "@/lib/api";
import { localDayISO, localWeekday } from "@/lib/format";
import type { Step } from "@/components/booking/types";
import { StepHeader } from "@/components/booking/step-header";
import { StepService } from "@/components/booking/step-service";
import { StepProfessional } from "@/components/booking/step-professional";
import { StepSchedule } from "@/components/booking/step-schedule";
import { StepConfirm } from "@/components/booking/step-confirm";
import { BookingSuccess } from "@/components/booking/booking-success";

const KNOWN_NAME_KEY = "tt_client_name";

export default function BookingFlow({ info }: { info: PublicInfo }) {
  const [step, setStep] = useState<Step>(1);
  const [service, setService] = useState<PublicService | null>(null);
  const [professional, setProfessional] = useState<PublicProfessional | null>(null);
  const [dayOffset, setDayOffset] = useState(0);
  const [slots, setSlots] = useState<string[] | null>(null);
  const [slotsError, setSlotsError] = useState<string | null>(null);
  const [slot, setSlot] = useState<string | null>(null);
  const [conflict, setConflict] = useState(false);
  const [conflictSlot, setConflictSlot] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  // Aceite da política de privacidade — só aparece para quem ainda não tem
  // sessão (é quando o titular entra na base).
  const [acceptPrivacy, setAcceptPrivacy] = useState(false);
  const [knownName, setKnownName] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [needsIdentify, setNeedsIdentify] = useState(true);
  const [done, setDone] = useState<PublicAppointment | null>(null);

  const headingRef = useRef<HTMLHeadingElement | null>(null);
  const mountedRef = useRef(false);

  useEffect(() => {
    const saved = localStorage.getItem(KNOWN_NAME_KEY);
    if (saved) {
      setKnownName(saved);
      setNeedsIdentify(false);
    }
    // Pré-seleção vinda da home (?servico={id}) — UX A6.
    const preId = Number(new URLSearchParams(window.location.search).get("servico"));
    if (preId) {
      const pre = info.services.find((s) => s.id === preId);
      if (pre) {
        setService(pre);
        setStep(2);
      }
    }
  }, [info.services]);

  // Acessibilidade (§5.3): a cada troca de passo o foco vai para o h1.
  useEffect(() => {
    if (!mountedRef.current) {
      mountedRef.current = true;
      return;
    }
    headingRef.current?.focus();
  }, [step]);

  const days = useMemo(() => {
    const list: Date[] = [];
    const now = new Date();
    for (let i = 0; i < 14; i++) {
      list.push(new Date(now.getTime() + i * 86_400_000));
    }
    return list;
  }, []);

  const selectedDay = days[dayOffset];

  // Dias fechados (UX A2): weekdays sem horário de funcionamento no payload.
  // Se o gestor ocultou os horários (hours vazio), não bloqueamos nada.
  const isClosed = useMemo(() => {
    if (info.hours.length === 0) return null;
    const open = new Set(info.hours.map((h) => h.weekday));
    return (d: Date) => !open.has(localWeekday(d));
  }, [info.hours]);

  // Ao entrar no passo 3 com o dia atual fechado, pula para o 1º dia aberto.
  useEffect(() => {
    if (step !== 3 || !isClosed) return;
    if (isClosed(days[dayOffset])) {
      const next = days.findIndex((d) => !isClosed(d));
      if (next >= 0) setDayOffset(next);
    }
  }, [step, isClosed, days, dayOffset]);

  const eligiblePros = useMemo(
    () =>
      service
        ? info.professionals.filter((p) => service.barber_ids.includes(p.id))
        : [],
    [info.professionals, service],
  );

  const loadSlots = useCallback(async () => {
    if (!service || !professional) return;
    setSlots(null);
    setSlotsError(null);
    setSlot(null);
    try {
      const resp = await api.slots(
        service.id,
        professional.id,
        localDayISO(selectedDay),
      );
      setSlots(resp.slots);
    } catch (e) {
      setSlotsError(e instanceof ApiError ? e.message : "Falha ao buscar horários.");
    }
  }, [service, professional, selectedDay]);

  useEffect(() => {
    if (step === 3) void loadSlots();
  }, [step, loadSlots]);

  const confirm = useCallback(async () => {
    if (!service || !professional || !slot) return;
    setSubmitting(true);
    setError(null);
    try {
      if (needsIdentify) {
        const digits = phone.replace(/\D/g, "");
        if (name.trim().length < 2 || digits.length < 10) {
          setError("Preencha seu nome e um telefone com DDD.");
          setSubmitting(false);
          return;
        }
        if (!acceptPrivacy) {
          setError("Aceite a política de privacidade para continuar.");
          setSubmitting(false);
          return;
        }
        const session = await api.createSession(name.trim(), digits, acceptPrivacy);
        localStorage.setItem(KNOWN_NAME_KEY, session.client_name);
        setKnownName(session.client_name);
        setNeedsIdentify(false);
      }
      const appt = await api.book(service.id, professional.id, slot);
      setDone(appt);
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) {
        // sessão expirou/limpou: pede identificação de novo
        localStorage.removeItem(KNOWN_NAME_KEY);
        setKnownName(null);
        setNeedsIdentify(true);
        setError("Confirme seus dados para concluir o agendamento.");
      } else if (e instanceof ApiError && e.status === 409) {
        // UX A1: feedback VISÍVEL no passo 3 (banner + slot riscado).
        setConflict(true);
        setConflictSlot(slot);
        setSlot(null);
        setStep(3);
      } else {
        setError(e instanceof ApiError ? e.message : "Não foi possível agendar.");
      }
    } finally {
      setSubmitting(false);
    }
  }, [service, professional, slot, needsIdentify, name, phone, acceptPrivacy]);

  if (done) {
    return <BookingSuccess done={done} />;
  }

  return (
    <main className="mx-auto w-full max-w-md px-6 pb-16">
      <StepHeader step={step} />

      {step === 1 && (
        <StepService
          services={info.services}
          headingRef={headingRef}
          onSelect={(s) => {
            setService(s);
            setProfessional(null);
            setStep(2);
          }}
        />
      )}

      {step === 2 && service && (
        <StepProfessional
          service={service}
          professionals={eligiblePros}
          headingRef={headingRef}
          onSelect={(p) => {
            setProfessional(p);
            setStep(3);
          }}
          onBack={() => setStep(1)}
        />
      )}

      {step === 3 && service && professional && (
        <StepSchedule
          service={service}
          professional={professional}
          days={days}
          dayOffset={dayOffset}
          closedWeekday={isClosed}
          slots={slots}
          slotsError={slotsError}
          conflict={conflict}
          conflictSlot={conflictSlot}
          headingRef={headingRef}
          onSelectDay={(i) => {
            setConflict(false);
            setConflictSlot(null);
            setDayOffset(i);
          }}
          onSelectSlot={(s) => {
            setConflict(false);
            setSlot(s);
            setStep(4);
          }}
          onRetry={() => void loadSlots()}
          onBack={() => setStep(2)}
        />
      )}

      {step === 4 && service && professional && slot && (
        <StepConfirm
          service={service}
          professional={professional}
          slot={slot}
          needsIdentify={needsIdentify}
          knownName={knownName}
          name={name}
          phone={phone}
          acceptPrivacy={acceptPrivacy}
          submitting={submitting}
          error={error}
          headingRef={headingRef}
          onNameChange={setName}
          onPhoneChange={setPhone}
          onAcceptPrivacyChange={setAcceptPrivacy}
          onForget={() => {
            localStorage.removeItem(KNOWN_NAME_KEY);
            setKnownName(null);
            setNeedsIdentify(true);
          }}
          onConfirm={() => void confirm()}
          onBack={() => setStep(3)}
        />
      )}
    </main>
  );
}
