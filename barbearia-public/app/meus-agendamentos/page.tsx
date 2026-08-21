"use client";

/* Meus agendamentos.
   P0 de rodadas anteriores (UX A4/§4.5): cancelamento exige confirmação num
   bottom sheet (foco na opção segura, Esc fecha) + toast de resultado com
   "Agendar novo horário".

   A API agora devolve `service_id`/`barber_id` (Fase A), então "Remarcar"
   monta o deep-link já pré-selecionado; e `rating`/`can_rate` destravam a
   avaliação pós-atendimento (definitiva, sem edição). */

import Link from "next/link";
import { Wordmark } from "@/components/wordmark";
import { useCallback, useEffect, useState } from "react";
import { api, ApiError, type PublicAppointment } from "@/lib/api";
import { dateLong, money, timeHM } from "@/lib/format";
import { StatusBadge } from "@/components/ui/status-badge";
import { EmptyState } from "@/components/ui/empty-state";
import { SolidLink } from "@/components/ui/buttons";
import { ConfirmSheet } from "@/components/ui/confirm-sheet";
import { Toast, type ToastData } from "@/components/ui/toast";
import AtivarNotificacoes from "@/components/ativar-notificacoes";
import { EstrelasLeitura, RatingSheet } from "@/components/rating-sheet";

export default function MeusAgendamentosPage() {
  const [items, setItems] = useState<PublicAppointment[] | null>(null);
  const [noSession, setNoSession] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [target, setTarget] = useState<PublicAppointment | null>(null);
  const [canceling, setCanceling] = useState(false);
  const [sheetError, setSheetError] = useState<string | null>(null);
  const [toast, setToast] = useState<ToastData | null>(null);
  const [rateTarget, setRateTarget] = useState<PublicAppointment | null>(null);
  const [rating, setRating] = useState(false);
  const [rateError, setRateError] = useState<string | null>(null);

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

  const confirmCancel = useCallback(async () => {
    if (!target) return;
    setCanceling(true);
    setSheetError(null);
    try {
      await api.cancel(target.public_id);
      setTarget(null);
      setToast({
        kind: "sucesso",
        message: "Horário cancelado.",
        actionLabel: "Agendar novo horário",
        actionHref: "/agendar",
      });
      await load();
    } catch (e) {
      if (e instanceof ApiError) {
        // 422 = corrida com a janela de 2h — mostra o detail e atualiza a lista.
        setSheetError(e.message);
        if (e.status === 422) await load();
      } else {
        setSheetError("Sem conexão. Seu horário não foi cancelado — tente de novo.");
      }
    } finally {
      setCanceling(false);
    }
  }, [target, load]);

  const confirmRate = useCallback(
    async (nota: number, comentario: string) => {
      if (!rateTarget) return;
      setRating(true);
      setRateError(null);
      try {
        await api.rate(rateTarget.public_id, {
          rating: nota,
          ...(comentario.trim() ? { comment: comentario.trim() } : {}),
        });
        setRateTarget(null);
        setToast({ kind: "sucesso", message: "Obrigado pela avaliação!" });
        await load();
      } catch (e) {
        if (e instanceof ApiError) {
          // 409 = já avaliado (UNIQUE), 422 = fora da janela/não concluído.
          // Nos dois casos a lista está desatualizada — recarrega.
          setRateError(e.message);
          if (e.status === 409 || e.status === 422) await load();
        } else {
          setRateError("Sem conexão. Sua avaliação não foi enviada.");
        }
      } finally {
        setRating(false);
      }
    },
    [rateTarget, load],
  );

  return (
    <main className="mx-auto w-full max-w-md px-6 pb-16">
      <header className="pt-6 pb-4">
        <Link
          href="/"
          className="inline-flex min-h-11 items-center gap-2 text-sm text-tinta-fraca transition-colors hover:text-tinta-suave"
        >
          <span aria-hidden>←</span>
          <Wordmark fontSize={15} />
        </Link>
        <h1 className="mt-4 font-display text-2xl">Meus agendamentos</h1>
      </header>

      {items !== null && items.length > 0 && <AtivarNotificacoes />}

      {noSession && (
        <div className="mt-6">
          <EmptyState
            message="Você ainda não tem agendamentos neste aparelho."
            action={<SolidLink size="inline" href="/agendar">Agendar horário</SolidLink>}
          />
        </div>
      )}

      {error && (
        <p role="alert" className="mt-4 text-vermelho-tinta">
          {error}
        </p>
      )}

      {items === null && !noSession && !error && (
        <p aria-live="polite" className="mt-6 text-tinta-suave">
          Carregando…
        </p>
      )}

      {items !== null && items.length === 0 && (
        <div className="mt-6">
          <EmptyState
            message="Nenhum agendamento por aqui ainda."
            action={<SolidLink size="inline" href="/agendar">Agendar horário</SolidLink>}
          />
        </div>
      )}

      <ul className="mt-4 space-y-3">
        {items?.map((a) => (
          <li
            key={a.public_id}
            className="rounded-xl border border-borda-sutil bg-superficie p-5"
            style={{ boxShadow: "var(--sombra-1)" }}
          >
            <div className="flex items-start justify-between gap-3">
              <div>
                <p
                  className={`font-medium ${a.status === "cancelado" ? "opacity-70" : ""}`}
                >
                  {a.service_name}
                </p>
                <p className="mt-1 text-sm text-tinta-suave">
                  {dateLong(a.start_at)} às <span className="tnum">{timeHM(a.start_at)}</span>
                </p>
                <p className="text-sm text-tinta-suave">com {a.barber_name}</p>
              </div>
              <StatusBadge status={a.status} />
            </div>
            <div className="mt-3 flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
              <p className="font-display text-lg text-tinta tnum">{money(a.total_amount)}</p>
              <div className="flex items-center gap-4">
                {/* Já avaliado: mostra a nota (é definitiva, não há o que editar). */}
                {a.rating != null && <EstrelasLeitura rating={a.rating} />}
                {a.status === "concluido" && a.can_rate && (
                  <button
                    onClick={() => {
                      setRateError(null);
                      setRateTarget(a);
                    }}
                    className="inline-flex min-h-11 items-center text-sm font-medium text-ouro underline underline-offset-4 transition-opacity hover:opacity-80"
                  >
                    Avaliar
                  </button>
                )}
                {a.status === "agendado" && a.cancelable && (
                  <Link
                    href={`/agendar?servico=${a.service_id}&profissional=${a.barber_id}&remarcar=${a.public_id}`}
                    className="inline-flex min-h-11 items-center text-sm text-tinta-suave underline underline-offset-4 transition-colors hover:text-marfim"
                  >
                    Remarcar
                  </Link>
                )}
                {a.cancelable && (
                  <button
                    onClick={() => {
                      setSheetError(null);
                      setTarget(a);
                    }}
                    className="inline-flex min-h-11 items-center text-sm text-vermelho-tinta underline underline-offset-4 transition-opacity hover:opacity-80"
                  >
                    Cancelar
                  </button>
                )}
              </div>
            </div>
          </li>
        ))}
      </ul>

      {items !== null && items.length > 0 && (
        <p className="mt-6 text-center text-xs text-tinta-suave">
          Cancelamento pelo site até 2h antes do horário. Depois disso, chame a
          gente no WhatsApp.
        </p>
      )}

      {target && (
        <ConfirmSheet
          title="Cancelar este horário?"
          body={`${target.service_name} · ${dateLong(target.start_at)} às ${timeHM(target.start_at)} com ${target.barber_name}.`}
          confirmLabel="Cancelar agendamento"
          confirmBusyLabel="Cancelando…"
          dismissLabel="Manter horário"
          busy={canceling}
          error={sheetError}
          onConfirm={() => void confirmCancel()}
          onDismiss={() => {
            if (!canceling) setTarget(null);
          }}
        />
      )}

      {rateTarget && (
        <RatingSheet
          title="Como foi seu atendimento?"
          body={`${rateTarget.service_name} · ${dateLong(rateTarget.start_at)} com ${rateTarget.barber_name}.`}
          busy={rating}
          error={rateError}
          onSubmit={(nota, comentario) => void confirmRate(nota, comentario)}
          onDismiss={() => {
            if (!rating) setRateTarget(null);
          }}
        />
      )}

      {toast && <Toast toast={toast} onClose={() => setToast(null)} />}
    </main>
  );
}
