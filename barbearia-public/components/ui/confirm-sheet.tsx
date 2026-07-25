"use client";

/* Bottom sheet de confirmação (UX A4/§4.5; UI_SPEC_V2: painel branco +
   sombra-3, backdrop navy translúcido): foco inicial na opção segura,
   Esc fecha, foco preso no diálogo. */

import { useEffect, useRef } from "react";
import { Spinner } from "@/components/ui/buttons";

export function ConfirmSheet({
  title,
  body,
  confirmLabel,
  confirmBusyLabel,
  dismissLabel,
  busy,
  error,
  onConfirm,
  onDismiss,
}: {
  title: string;
  body: string;
  confirmLabel: string;
  confirmBusyLabel: string;
  dismissLabel: string;
  busy: boolean;
  error: string | null;
  onConfirm: () => void;
  onDismiss: () => void;
}) {
  const panelRef = useRef<HTMLDivElement>(null);
  const dismissRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    dismissRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        onDismiss();
        return;
      }
      if (e.key !== "Tab") return;
      // Trap simples: cicla entre os focáveis do sheet.
      const focusables = Array.from(
        panelRef.current?.querySelectorAll<HTMLElement>("button, a[href]") ?? [],
      );
      if (focusables.length === 0) return;
      e.preventDefault();
      const idx = focusables.indexOf(document.activeElement as HTMLElement);
      const next = e.shiftKey
        ? idx <= 0
          ? focusables.length - 1
          : idx - 1
        : idx >= focusables.length - 1
          ? 0
          : idx + 1;
      focusables[next].focus();
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      previous?.focus();
    };
  }, [onDismiss]);

  return (
    <div className="fixed inset-0 z-50 flex flex-col justify-end">
      <button
        aria-label={dismissLabel}
        onClick={onDismiss}
        className="absolute inset-0"
        style={{ background: "rgba(0, 0, 0, 0.65)" }}
        tabIndex={-1}
      />
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="sheet-titulo"
        className="anim-entrar relative mx-auto w-full max-w-md rounded-t-2xl bg-superficie p-6 pb-[calc(env(safe-area-inset-bottom)+1.5rem)]"
        style={{ boxShadow: "var(--sombra-3)" }}
      >
        <h2 id="sheet-titulo" className="font-display text-2xl text-tinta">
          {title}
        </h2>
        <p className="mt-2 text-tinta-suave">{body}</p>
        {error && (
          <p role="alert" className="mt-3 text-sm text-vermelho-tinta">
            {error}
          </p>
        )}
        <div className="mt-6 flex flex-col gap-3">
          <button
            ref={dismissRef}
            onClick={onDismiss}
            disabled={busy}
            className="inline-flex min-h-11 w-full items-center justify-center rounded-xl border border-borda bg-transparent px-6 py-3 font-medium text-marfim transition-colors hover:border-ouro hover:text-ouro disabled:opacity-60"
          >
            {dismissLabel}
          </button>
          <button
            onClick={onConfirm}
            disabled={busy}
            className="inline-flex min-h-11 w-full items-center justify-center gap-2 rounded-xl bg-vermelho-tinta px-6 py-3 font-semibold text-superficie transition-opacity hover:opacity-90 disabled:opacity-60"
          >
            {busy && <Spinner />}
            {busy ? confirmBusyLabel : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
