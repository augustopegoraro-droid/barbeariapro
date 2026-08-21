"use client";

/* Bottom sheet de avaliação — mesma base do `components/ui/confirm-sheet.tsx`
   (foco preso no diálogo, Esc fecha, painel em superfície + sombra-3).

   A avaliação é DEFINITIVA: a tabela nasce append-only e não há endpoint de
   edição (Fase A). Por isso o botão diz "Enviar avaliação" e o texto avisa. */

import { useEffect, useRef, useState } from "react";
import { Spinner } from "@/components/ui/buttons";
import { hapticImpact } from "@/lib/native";

const MAX_COMENTARIO = 1000;

function Estrela({ preenchida }: { preenchida: boolean }) {
  return (
    <svg
      viewBox="0 0 24 24"
      className="h-8 w-8"
      fill={preenchida ? "currentColor" : "none"}
      stroke="currentColor"
      strokeWidth={1.5}
      strokeLinejoin="round"
      aria-hidden
    >
      <path d="m12 3.6 2.6 5.3 5.9.9-4.3 4.1 1 5.8-5.2-2.7-5.2 2.7 1-5.8-4.3-4.1 5.9-.9Z" />
    </svg>
  );
}

/** Estrelas só de leitura — usado na lista de agendamentos já avaliados. */
export function EstrelasLeitura({ rating }: { rating: number }) {
  return (
    <span
      className="inline-flex items-center gap-0.5 text-ouro"
      aria-label={`Avaliado com ${rating} de 5 estrelas`}
    >
      {[1, 2, 3, 4, 5].map((n) => (
        <span key={n} className="h-4 w-4 [&>svg]:h-4 [&>svg]:w-4">
          <Estrela preenchida={n <= rating} />
        </span>
      ))}
    </span>
  );
}

export function RatingSheet({
  title,
  body,
  busy,
  error,
  onSubmit,
  onDismiss,
}: {
  title: string;
  body: string;
  busy: boolean;
  error: string | null;
  onSubmit: (rating: number, comment: string) => void;
  onDismiss: () => void;
}) {
  const panelRef = useRef<HTMLDivElement>(null);
  const dismissRef = useRef<HTMLButtonElement>(null);
  const [rating, setRating] = useState(0);
  const [comment, setComment] = useState("");

  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    dismissRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        onDismiss();
        return;
      }
      if (e.key !== "Tab") return;
      const focusables = Array.from(
        panelRef.current?.querySelectorAll<HTMLElement>(
          "button, a[href], textarea",
        ) ?? [],
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
        aria-label="Fechar"
        onClick={onDismiss}
        className="absolute inset-0"
        style={{ background: "rgba(0, 0, 0, 0.65)" }}
        tabIndex={-1}
      />
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="avaliacao-titulo"
        className="anim-entrar relative mx-auto w-full max-w-md rounded-t-2xl bg-superficie p-6 pb-[calc(env(safe-area-inset-bottom)+1.5rem)]"
        style={{ boxShadow: "var(--sombra-3)" }}
      >
        <h2 id="avaliacao-titulo" className="font-display text-2xl text-tinta">
          {title}
        </h2>
        <p className="mt-2 text-tinta-suave">{body}</p>

        <div
          role="radiogroup"
          aria-label="Nota de 1 a 5 estrelas"
          className="mt-5 flex justify-center gap-2"
        >
          {[1, 2, 3, 4, 5].map((n) => (
            <button
              key={n}
              type="button"
              role="radio"
              aria-checked={rating === n}
              aria-label={`${n} ${n === 1 ? "estrela" : "estrelas"}`}
              disabled={busy}
              onClick={() => {
                setRating(n);
                void hapticImpact();
              }}
              className={`flex h-12 w-12 items-center justify-center rounded-full transition-colors disabled:opacity-60 ${
                n <= rating ? "text-ouro" : "text-tinta-fraca hover:text-ouro"
              }`}
            >
              <Estrela preenchida={n <= rating} />
            </button>
          ))}
        </div>

        <label htmlFor="avaliacao-comentario" className="mt-5 block text-sm text-tinta-suave">
          Quer contar como foi? (opcional)
        </label>
        <textarea
          id="avaliacao-comentario"
          value={comment}
          maxLength={MAX_COMENTARIO}
          rows={3}
          disabled={busy}
          onChange={(e) => setComment(e.target.value)}
          className="mt-2 w-full rounded-xl border border-borda bg-superficie-2 px-4 py-3 text-tinta placeholder:text-tinta-fraca disabled:opacity-60"
          placeholder="O atendimento, o corte, o ambiente…"
        />
        <p className="mt-1 text-right text-xs text-tinta-fraca tnum">
          {comment.length}/{MAX_COMENTARIO}
        </p>

        {error && (
          <p role="alert" className="mt-3 text-sm text-vermelho-tinta">
            {error}
          </p>
        )}

        <div className="mt-5 flex flex-col gap-3">
          <button
            onClick={() => onSubmit(rating, comment)}
            disabled={busy || rating === 0}
            className="inline-flex min-h-11 w-full items-center justify-center gap-2 rounded-xl bg-ouro px-6 py-3 font-semibold text-tinta-invertida transition-colors hover:bg-ouro-claro disabled:opacity-60"
          >
            {busy && <Spinner />}
            {busy ? "Enviando…" : "Enviar avaliação"}
          </button>
          <button
            ref={dismissRef}
            onClick={onDismiss}
            disabled={busy}
            className="inline-flex min-h-11 w-full items-center justify-center rounded-xl border border-borda bg-transparent px-6 py-3 font-medium text-marfim transition-colors hover:border-ouro hover:text-ouro disabled:opacity-60"
          >
            Agora não
          </button>
        </div>
        <p className="mt-3 text-center text-xs text-tinta-fraca">
          A avaliação é definitiva — depois de enviada não dá para editar.
        </p>
      </div>
    </div>
  );
}
