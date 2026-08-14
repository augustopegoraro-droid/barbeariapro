"use client";

/* Ativação de notificações push (Web Push/VAPID) — confirmação de horário +
   lembretes (24h/30min). Molde visual de `install-banner.tsx`. iOS 16.4+ só
   entrega push com o site adicionado à Tela de Início (limitação da Apple). */

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { disablePush, enablePush, getExistingSubscription, pushSupported } from "@/lib/push";

const DISMISSED_KEY = "tt_push_dismissed";

export default function AtivarNotificacoes() {
  const [visible, setVisible] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!pushSupported()) return;
    if (localStorage.getItem(DISMISSED_KEY)) return;
    void getExistingSubscription().then((sub) => setVisible(!sub));
  }, []);

  if (!visible) return null;

  return (
    <aside
      className="mt-6 rounded-xl border border-borda-sutil bg-superficie p-4"
      style={{ boxShadow: "var(--sombra-2)" }}
    >
      <p className="font-medium text-marfim">Ativar notificações</p>
      <p className="mt-1 text-sm text-tinta-suave">
        Avisamos no celular quando o horário estiver chegando — sem precisar abrir o app.
      </p>
      <div className="mt-3 flex gap-3">
        <button
          disabled={busy}
          className="inline-flex min-h-11 items-center rounded-lg bg-ouro px-4 py-2 text-sm font-semibold text-tinta-invertida transition-colors hover:bg-ouro-claro disabled:opacity-60"
          onClick={async () => {
            setBusy(true);
            const result = await enablePush(api.subscribePush);
            setBusy(false);
            if (result === "ok") {
              setVisible(false);
            } else {
              setVisible(false);
              localStorage.setItem(DISMISSED_KEY, "1");
            }
          }}
        >
          {busy ? "Ativando…" : "Ativar"}
        </button>
        <button
          className="inline-flex min-h-11 items-center rounded-lg px-4 py-2 text-sm text-tinta-fraca underline underline-offset-4 transition-colors hover:text-tinta-suave"
          onClick={() => {
            localStorage.setItem(DISMISSED_KEY, "1");
            setVisible(false);
          }}
        >
          Agora não
        </button>
      </div>
    </aside>
  );
}

export function useDisablePush() {
  return () => disablePush(api.unsubscribePush);
}
