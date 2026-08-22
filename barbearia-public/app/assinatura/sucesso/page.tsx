"use client";

/* Retorno do Stripe Checkout.

   Esta página NÃO confirma nada: chegar aqui só prova que o cliente voltou da
   Stripe (a URL é pública e ele controla o navegador). Quem confirma o
   pagamento e cria a assinatura é o webhook, no backend. Aqui apenas
   perguntamos "já valeu?" em polling curto, e se o webhook ainda não chegou,
   tranquilizamos em vez de mentir nos dois sentidos. */

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { api, type ActiveMembership } from "@/lib/api";
import { AssinaturaResumo } from "@/components/assinatura/assinatura-resumo";
import { SolidLink, GhostLink } from "@/components/ui/buttons";

const INTERVALO_MS = 2000;
const TENTATIVAS = 8; // ~16s

export default function AssinaturaSucessoPage() {
  const [assinatura, setAssinatura] = useState<ActiveMembership | null>(null);
  const [desistiu, setDesistiu] = useState(false);
  const rodouRef = useRef(false);

  useEffect(() => {
    if (rodouRef.current) return;
    rodouRef.current = true;

    let cancelado = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const tentar = async (restantes: number) => {
      if (cancelado) return;
      try {
        const atual = await api.minhaAssinatura();
        if (cancelado) return;
        if (atual) {
          setAssinatura(atual);
          return;
        }
      } catch {
        /* sessão/rede instável: seguimos tentando até o limite */
      }
      if (restantes <= 1) {
        if (!cancelado) setDesistiu(true);
        return;
      }
      timer = setTimeout(() => void tentar(restantes - 1), INTERVALO_MS);
    };

    void tentar(TENTATIVAS);
    return () => {
      cancelado = true;
      if (timer) clearTimeout(timer);
    };
  }, []);

  return (
    <main className="mx-auto w-full max-w-md px-6 pb-16">
      <header className="pt-14 text-center">
        <p className="font-display text-5xl" aria-hidden>
          ✂️
        </p>
        <h1 className="mt-4 font-display text-3xl">
          {assinatura ? "Assinatura ativada" : "Recebemos seu pagamento"}
        </h1>
        <p className="mt-2 text-sm text-tinta-suave" aria-live="polite">
          {assinatura
            ? "Seu pacote já está valendo. É só agendar."
            : desistiu
              ? "Pode levar alguns minutos para liberar. Confira em “Minha assinatura” daqui a pouco — não é preciso pagar de novo."
              : "Estamos liberando seu pacote…"}
        </p>
      </header>

      {assinatura && (
        <div className="mt-8">
          <AssinaturaResumo assinatura={assinatura} />
        </div>
      )}

      <div className="mt-8 flex flex-col items-center gap-3 text-center">
        <SolidLink href="/agendar">Agendar horário</SolidLink>
        <GhostLink href="/perfil">Ver minha assinatura</GhostLink>
        <Link
          href="/"
          className="inline-flex min-h-11 items-center text-sm text-tinta-fraca transition-colors hover:text-tinta-suave"
        >
          Voltar ao início
        </Link>
      </div>
    </main>
  );
}
