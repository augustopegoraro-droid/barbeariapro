"use client";

/* Toast fixo no rodapé (UI_SPEC_V3 §2 item 10): superfície escura + borda +
   sombra-2; acentos nos pares -tinta; ação em ouro. Sucesso auto-dismiss 4s
   (role="status"), erro persiste até ação/dismiss (role="alert"). Um por vez. */

import Link from "next/link";
import { useEffect } from "react";

export type ToastData = {
  kind: "sucesso" | "erro";
  message: string;
  actionLabel?: string;
  actionHref?: string;
};

export function Toast({
  toast,
  onClose,
}: {
  toast: ToastData;
  onClose: () => void;
}) {
  useEffect(() => {
    if (toast.kind !== "sucesso") return;
    const t = setTimeout(onClose, 4000);
    return () => clearTimeout(t);
  }, [toast, onClose]);

  return (
    <div
      role={toast.kind === "erro" ? "alert" : "status"}
      className="anim-entrar fixed inset-x-4 z-50 mx-auto max-w-md"
      style={{
        bottom: "calc(env(safe-area-inset-bottom) + 16px)",
        boxShadow: "var(--sombra-2)",
      }}
    >
      <div className="flex items-start gap-3 rounded-2xl border border-borda bg-superficie p-4">
        <span
          aria-hidden
          className="w-[3px] shrink-0 self-stretch rounded-full"
          style={{
            background:
              toast.kind === "erro" ? "var(--vermelho-tinta)" : "var(--verde-tinta)",
          }}
        />
        <div className="flex-1 text-sm text-tinta">
          <p>{toast.message}</p>
          {toast.actionLabel && toast.actionHref && (
            <Link
              href={toast.actionHref}
              className="mt-1 inline-flex min-h-11 items-center font-medium text-ouro underline underline-offset-4"
            >
              {toast.actionLabel}
            </Link>
          )}
        </div>
        <button
          onClick={onClose}
          aria-label="Fechar aviso"
          className="-m-2 flex h-11 w-11 items-center justify-center text-tinta-fraca transition-colors hover:text-marfim"
        >
          ✕
        </button>
      </div>
    </div>
  );
}
