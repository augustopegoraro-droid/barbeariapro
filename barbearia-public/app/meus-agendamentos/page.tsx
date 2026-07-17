"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { api, ApiError, type PublicAppointment } from "@/lib/api";
import { dateLong, money, timeHM } from "@/lib/format";

const STATUS_LABEL: Record<string, string> = {
  agendado: "Agendado",
  concluido: "Concluído",
  cancelado: "Cancelado",
  faltou: "Não compareceu",
};

export default function MeusAgendamentosPage() {
  const [items, setItems] = useState<PublicAppointment[] | null>(null);
  const [noSession, setNoSession] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [canceling, setCanceling] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      setItems(await api.myAppointments());
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) setNoSession(true);
      else setError(e instanceof ApiError ? e.message : "Falha ao carregar.");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const cancel = async (publicId: string) => {
    setCanceling(publicId);
    setError(null);
    try {
      await api.cancel(publicId);
      await load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Não foi possível cancelar.");
    } finally {
      setCanceling(null);
    }
  };

  return (
    <main className="mx-auto w-full max-w-md px-6 pb-16">
      <header className="pt-6 pb-4">
        <Link href="/" className="text-sm text-cinza hover:text-prata-suave">
          ← Taylor &amp; Thedy
        </Link>
        <h1 className="mt-4 font-display text-2xl font-semibold">Meus agendamentos</h1>
      </header>

      {noSession && (
        <div className="mt-6 rounded-xl bg-aco p-5 text-center">
          <p className="text-prata-suave">
            Você ainda não tem agendamentos neste aparelho.
          </p>
          <Link
            href="/agendar"
            className="mt-4 inline-block rounded-xl bg-destaque px-6 py-3 font-semibold text-grafite"
          >
            Agendar horário
          </Link>
        </div>
      )}

      {error && <p className="mt-4 text-vermelho">{error}</p>}

      {items === null && !noSession && !error && (
        <p className="mt-6 text-prata-suave">Carregando…</p>
      )}

      {items !== null && items.length === 0 && (
        <div className="mt-6 rounded-xl bg-aco p-5 text-center">
          <p className="text-prata-suave">Nenhum agendamento por aqui ainda.</p>
          <Link
            href="/agendar"
            className="mt-4 inline-block rounded-xl bg-destaque px-6 py-3 font-semibold text-grafite"
          >
            Agendar horário
          </Link>
        </div>
      )}

      <ul className="mt-4 space-y-3">
        {items?.map((a) => (
          <li key={a.public_id} className="rounded-xl bg-aco p-5">
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className="font-medium">{a.service_name}</p>
                <p className="mt-1 text-sm text-prata-suave">
                  {dateLong(a.start_at)} às <span className="tnum">{timeHM(a.start_at)}</span>
                </p>
                <p className="text-sm text-prata-suave">com {a.barber_name}</p>
              </div>
              <span
                className={`rounded-full px-2.5 py-1 text-xs font-medium ${
                  a.status === "agendado"
                    ? "bg-destaque/15 text-destaque"
                    : a.status === "cancelado"
                      ? "bg-vermelho/15 text-vermelho"
                      : "bg-aco-claro text-prata-suave"
                }`}
              >
                {STATUS_LABEL[a.status] ?? a.status}
              </span>
            </div>
            <div className="mt-3 flex items-center justify-between">
              <p className="font-display text-lg text-destaque tnum">{money(a.total_amount)}</p>
              {a.cancelable && (
                <button
                  onClick={() => void cancel(a.public_id)}
                  disabled={canceling === a.public_id}
                  className="text-sm text-vermelho underline underline-offset-4 disabled:opacity-60"
                >
                  {canceling === a.public_id ? "Cancelando…" : "Cancelar"}
                </button>
              )}
            </div>
          </li>
        ))}
      </ul>

      {items !== null && items.length > 0 && (
        <p className="mt-6 text-center text-xs text-cinza">
          Cancelamento pelo site até 2h antes do horário. Depois disso, chame a
          gente no WhatsApp.
        </p>
      )}
    </main>
  );
}
