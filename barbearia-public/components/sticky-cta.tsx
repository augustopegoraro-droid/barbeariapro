"use client";

/* Barra fixa de conversão da home (UX A7/§4.1; tratamento escuro na
   UI_SPEC_V3 §3.4): aparece quando o hero sai da viewport (sentinela
   #fim-do-hero via IntersectionObserver) e some ao voltar. Sem `.cta-agendar`
   aqui — o glow é exclusivo do hero e do fechamento; aqui é o ouro sólido
   nível 2. `prefers-reduced-motion` coberto pelo reset global. */

import Link from "next/link";
import { useEffect, useState } from "react";

export default function StickyCta() {
  const [show, setShow] = useState(false);

  useEffect(() => {
    const sentinel = document.getElementById("fim-do-hero");
    if (!sentinel) return;
    /* Só entra depois que o hero SAI por cima (sentinela acima da viewport).
       Se aparecesse já ao intersectar, duplicaria o CTA do hero na 1ª tela. */
    const io = new IntersectionObserver(([entry]) => {
      setShow(!entry.isIntersecting && entry.boundingClientRect.top < 0);
    });
    io.observe(sentinel);
    return () => io.disconnect();
  }, []);

  return (
    <div
      aria-hidden={!show}
      className={`fixed inset-x-0 bottom-0 z-40 transition-all duration-200 ${
        show ? "translate-y-0 opacity-100" : "pointer-events-none translate-y-4 opacity-0"
      }`}
      style={{ boxShadow: "0 -10px 30px rgba(0, 0, 0, 0.55)" }}
    >
      <div className="border-t border-borda-sutil bg-fundo/90 px-6 pt-3 pb-[calc(env(safe-area-inset-bottom)+0.5rem)] backdrop-blur-lg">
        <div className="mx-auto flex w-full max-w-md flex-col items-center gap-1">
          <Link
            href="/agendar"
            tabIndex={show ? 0 : -1}
            className="inline-flex min-h-11 w-full items-center justify-center gap-2 rounded-full bg-ouro px-6 py-3 text-lg font-semibold text-tinta-invertida transition-colors hover:bg-ouro-claro active:scale-[0.985]"
          >
            Agendar horário
          </Link>
          <Link
            href="/meus-agendamentos"
            tabIndex={show ? 0 : -1}
            className="inline-flex min-h-11 items-center text-sm text-tinta-suave underline underline-offset-4 transition-colors hover:text-marfim"
          >
            Meus agendamentos
          </Link>
        </div>
      </div>
    </div>
  );
}
