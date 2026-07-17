"use client";

/* Fluxo de agendamento em 4 passos (mobile-first):
   serviço → profissional → dia/horário → identificação + confirmação.

   Sessão: cookie HttpOnly (o JS não enxerga) — guardamos só o nome em
   localStorage como memória de UX. Se a API devolver 401 no agendamento,
   voltamos ao passo de identificação e refazemos a sessão. */

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  api,
  ApiError,
  type PublicAppointment,
  type PublicInfo,
  type PublicProfessional,
  type PublicService,
} from "@/lib/api";
import {
  dateLong,
  dayNumber,
  localDayISO,
  maskPhone,
  money,
  monthShort,
  timeHM,
  weekdayShort,
} from "@/lib/format";
import InstallBanner from "@/components/install-banner";

const KNOWN_NAME_KEY = "tt_client_name";

type Step = 1 | 2 | 3 | 4;

const STEP_LABELS = ["Serviço", "Profissional", "Horário", "Confirmar"];

function StepHeader({ step }: { step: Step }) {
  return (
    <header className="pt-6 pb-4">
      <Link href="/" className="text-sm text-cinza hover:text-prata-suave">
        ← Taylor &amp; Thedy
      </Link>
      <ol className="mt-4 flex gap-1" aria-label="Etapas do agendamento">
        {STEP_LABELS.map((label, i) => (
          <li key={label} className="flex-1">
            {/* passo ativo carrega a listra de barbeiro */}
            {i + 1 === step ? (
              <div className="stripe rounded-full" aria-hidden />
            ) : (
              <div
                className={`h-1 rounded-full ${i + 1 < step ? "bg-destaque" : "bg-aco-claro"}`}
                aria-hidden
              />
            )}
            <span
              className={`mt-1 block text-[11px] ${
                i + 1 === step ? "text-prata" : "text-cinza"
              }`}
            >
              {label}
            </span>
          </li>
        ))}
      </ol>
    </header>
  );
}

export default function BookingFlow({ info }: { info: PublicInfo }) {
  const [step, setStep] = useState<Step>(1);
  const [service, setService] = useState<PublicService | null>(null);
  const [professional, setProfessional] = useState<PublicProfessional | null>(null);
  const [dayOffset, setDayOffset] = useState(0);
  const [slots, setSlots] = useState<string[] | null>(null);
  const [slotsError, setSlotsError] = useState<string | null>(null);
  const [slot, setSlot] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [knownName, setKnownName] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [needsIdentify, setNeedsIdentify] = useState(true);
  const [done, setDone] = useState<PublicAppointment | null>(null);

  useEffect(() => {
    const saved = localStorage.getItem(KNOWN_NAME_KEY);
    if (saved) {
      setKnownName(saved);
      setNeedsIdentify(false);
    }
  }, []);

  const days = useMemo(() => {
    const list: Date[] = [];
    const now = new Date();
    for (let i = 0; i < 14; i++) {
      list.push(new Date(now.getTime() + i * 86_400_000));
    }
    return list;
  }, []);

  const selectedDay = days[dayOffset];

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

  const groupedSlots = useMemo(() => {
    if (!slots) return null;
    const groups: Record<string, string[]> = { Manhã: [], Tarde: [], Noite: [] };
    for (const s of slots) {
      const h = parseInt(timeHM(s).slice(0, 2), 10);
      if (h < 12) groups["Manhã"].push(s);
      else if (h < 18) groups["Tarde"].push(s);
      else groups["Noite"].push(s);
    }
    return groups;
  }, [slots]);

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
        const session = await api.createSession(name.trim(), digits);
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
        setError("Esse horário acabou de ser ocupado. Escolha outro.");
        setStep(3);
      } else {
        setError(e instanceof ApiError ? e.message : "Não foi possível agendar.");
      }
    } finally {
      setSubmitting(false);
    }
  }, [service, professional, slot, needsIdentify, name, phone]);

  if (done) {
    return (
      <main className="mx-auto w-full max-w-md px-6 pb-16">
        <header className="pt-14 text-center">
          <p className="font-display text-5xl" aria-hidden>
            ✂️
          </p>
          <h1 className="mt-4 font-display text-3xl font-semibold">Horário marcado!</h1>
        </header>
        <div className="mt-8 rounded-xl bg-aco p-5">
          <p className="font-medium">{done.service_name}</p>
          <p className="mt-1 text-prata-suave">
            {dateLong(done.start_at)} às <span className="tnum">{timeHM(done.start_at)}</span>
          </p>
          <p className="mt-1 text-prata-suave">com {done.barber_name}</p>
          <p className="mt-3 font-display text-xl text-destaque">{money(done.total_amount)}</p>
        </div>
        <InstallBanner />
        <div className="mt-8 flex flex-col gap-3 text-center">
          <Link
            href="/meus-agendamentos"
            className="rounded-xl bg-destaque px-6 py-3 font-semibold text-grafite"
          >
            Ver meus agendamentos
          </Link>
          <Link href="/" className="text-sm text-prata-suave underline underline-offset-4">
            Voltar ao início
          </Link>
        </div>
      </main>
    );
  }

  return (
    <main className="mx-auto w-full max-w-md px-6 pb-16">
      <StepHeader step={step} />

      {step === 1 && (
        <section aria-label="Escolha o serviço">
          <h1 className="font-display text-2xl font-semibold">O que vai fazer hoje?</h1>
          <ul className="mt-4 space-y-2">
            {info.services.map((s) => (
              <li key={s.id}>
                <button
                  onClick={() => {
                    setService(s);
                    setProfessional(null);
                    setStep(2);
                  }}
                  className="flex w-full items-baseline justify-between gap-4 rounded-xl bg-aco px-4 py-4 text-left transition-colors hover:bg-aco-claro"
                >
                  <span>
                    <span className="block font-medium">{s.name}</span>
                    <span className="block text-sm text-cinza">{s.duration_min} min</span>
                  </span>
                  <span className="font-display text-lg text-destaque tnum">
                    {money(s.price)}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}

      {step === 2 && service && (
        <section aria-label="Escolha o profissional">
          <h1 className="font-display text-2xl font-semibold">Quem vai te atender?</h1>
          <p className="mt-1 text-sm text-prata-suave">{service.name}</p>
          <ul className="mt-4 space-y-2">
            {eligiblePros.map((p) => (
              <li key={p.id}>
                <button
                  onClick={() => {
                    setProfessional(p);
                    setStep(3);
                  }}
                  className="flex w-full items-center gap-3 rounded-xl bg-aco px-4 py-4 text-left transition-colors hover:bg-aco-claro"
                >
                  <span
                    aria-hidden
                    className="flex h-10 w-10 items-center justify-center rounded-full bg-aco-claro font-display font-semibold text-destaque"
                  >
                    {p.name.charAt(0)}
                  </span>
                  <span>
                    <span className="block font-medium">{p.name}</span>
                    {p.specialty && (
                      <span className="block text-xs text-cinza">{p.specialty}</span>
                    )}
                  </span>
                </button>
              </li>
            ))}
          </ul>
          {eligiblePros.length === 0 && (
            <p className="mt-4 text-prata-suave">
              Nenhum profissional disponível para este serviço agora.
            </p>
          )}
          <BackButton onClick={() => setStep(1)} />
        </section>
      )}

      {step === 3 && service && professional && (
        <section aria-label="Escolha o horário">
          <h1 className="font-display text-2xl font-semibold">Escolha o horário</h1>
          <p className="mt-1 text-sm text-prata-suave">
            {service.name} · {professional.name}
          </p>

          <div className="mt-4 -mx-6 overflow-x-auto px-6">
            <div className="flex gap-2 pb-2" role="tablist" aria-label="Dia">
              {days.map((d, i) => (
                <button
                  key={i}
                  role="tab"
                  aria-selected={i === dayOffset}
                  onClick={() => setDayOffset(i)}
                  className={`flex min-w-[3.5rem] flex-col items-center rounded-xl px-2 py-2 text-sm transition-colors ${
                    i === dayOffset
                      ? "bg-destaque font-semibold text-grafite"
                      : "bg-aco text-prata-suave hover:bg-aco-claro"
                  }`}
                >
                  <span className="text-[11px] uppercase">{weekdayShort(d)}</span>
                  <span className="font-display text-lg tnum">{dayNumber(d)}</span>
                  <span className="text-[10px] uppercase">{monthShort(d)}</span>
                </button>
              ))}
            </div>
          </div>

          {slots === null && !slotsError && (
            <p className="mt-6 text-prata-suave">Buscando horários…</p>
          )}
          {slotsError && (
            <p className="mt-6 text-vermelho">
              {slotsError}{" "}
              <button className="underline" onClick={() => void loadSlots()}>
                Tentar de novo
              </button>
            </p>
          )}
          {slots !== null && slots.length === 0 && (
            <p className="mt-6 text-prata-suave">
              Sem horários livres neste dia. Escolha outro dia acima.
            </p>
          )}
          {groupedSlots &&
            Object.entries(groupedSlots).map(([label, list]) =>
              list.length === 0 ? null : (
                <div key={label} className="mt-5">
                  <h2 className="text-sm font-medium uppercase tracking-wide text-cinza">
                    {label}
                  </h2>
                  <div className="mt-2 grid grid-cols-4 gap-2">
                    {list.map((s) => (
                      <button
                        key={s}
                        onClick={() => {
                          setSlot(s);
                          setStep(4);
                        }}
                        className="rounded-lg bg-aco px-2 py-2.5 text-center font-medium tnum transition-colors hover:bg-destaque hover:text-grafite"
                      >
                        {timeHM(s)}
                      </button>
                    ))}
                  </div>
                </div>
              ),
            )}
          <BackButton onClick={() => setStep(2)} />
        </section>
      )}

      {step === 4 && service && professional && slot && (
        <section aria-label="Confirme seu agendamento">
          <h1 className="font-display text-2xl font-semibold">Confirme</h1>
          <div className="mt-4 rounded-xl bg-aco p-5">
            <p className="font-medium">{service.name}</p>
            <p className="mt-1 text-prata-suave">
              {dateLong(slot)} às <span className="tnum">{timeHM(slot)}</span>
            </p>
            <p className="mt-1 text-prata-suave">com {professional.name}</p>
            <p className="mt-3 font-display text-xl text-destaque">{money(service.price)}</p>
          </div>

          {needsIdentify ? (
            <form
              className="mt-6 space-y-4"
              onSubmit={(e) => {
                e.preventDefault();
                void confirm();
              }}
            >
              <div>
                <label htmlFor="nome" className="block text-sm font-medium">
                  Seu nome
                </label>
                <input
                  id="nome"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  autoComplete="name"
                  required
                  minLength={2}
                  className="mt-1 w-full rounded-lg border border-aco-claro bg-aco px-3 py-3 text-prata placeholder:text-cinza"
                  placeholder="Como podemos te chamar"
                />
              </div>
              <div>
                <label htmlFor="telefone" className="block text-sm font-medium">
                  WhatsApp / celular
                </label>
                <input
                  id="telefone"
                  value={phone}
                  onChange={(e) => setPhone(maskPhone(e.target.value))}
                  inputMode="tel"
                  autoComplete="tel-national"
                  required
                  className="mt-1 w-full rounded-lg border border-aco-claro bg-aco px-3 py-3 text-prata tnum placeholder:text-cinza"
                  placeholder="(63) 99999-9999"
                />
                <p className="mt-1 text-xs text-cinza">
                  Usamos seu número para confirmar e lembrar do horário.
                </p>
              </div>
              {error && <p className="text-sm text-vermelho">{error}</p>}
              <button
                type="submit"
                disabled={submitting}
                className="w-full rounded-xl bg-destaque px-6 py-4 text-lg font-semibold text-grafite transition-colors hover:bg-destaque-escuro disabled:opacity-60"
              >
                {submitting ? "Agendando…" : "Confirmar agendamento"}
              </button>
            </form>
          ) : (
            <div className="mt-6 space-y-4">
              <p className="text-prata-suave">
                Agendando como <span className="font-medium text-prata">{knownName}</span>{" "}
                <button
                  className="text-sm text-cinza underline underline-offset-4"
                  onClick={() => {
                    localStorage.removeItem(KNOWN_NAME_KEY);
                    setKnownName(null);
                    setNeedsIdentify(true);
                  }}
                >
                  não é você?
                </button>
              </p>
              {error && <p className="text-sm text-vermelho">{error}</p>}
              <button
                onClick={() => void confirm()}
                disabled={submitting}
                className="w-full rounded-xl bg-destaque px-6 py-4 text-lg font-semibold text-grafite transition-colors hover:bg-destaque-escuro disabled:opacity-60"
              >
                {submitting ? "Agendando…" : "Confirmar agendamento"}
              </button>
            </div>
          )}
          <BackButton onClick={() => setStep(3)} />
        </section>
      )}
    </main>
  );
}

function BackButton({ onClick }: { onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className="mt-6 text-sm text-cinza underline underline-offset-4 hover:text-prata-suave"
    >
      ← Voltar
    </button>
  );
}
