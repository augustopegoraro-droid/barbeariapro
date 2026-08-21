"use client";

/* Barra de navegação inferior — só existe no modo app (WebView do Capacitor).

   `isApp` vem do server (User-Agent, `app/layout.tsx`): sem flash de barra no
   browser comum. Ícones inline, como o resto do site (não há lib de ícones e o
   CSP não carrega nada de fora — ver `components/ui/contato-botoes.tsx`). */

import Link from "next/link";
import { usePathname } from "next/navigation";
import { hapticImpact } from "@/lib/native";
import type { ReactNode } from "react";

function IconeInicio() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.7} strokeLinecap="round" strokeLinejoin="round" className="h-5 w-5" aria-hidden>
      <path d="M3 10.5 12 3l9 7.5" />
      <path d="M5 9.6V20h14V9.6" />
    </svg>
  );
}

function IconeAgendar() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.7} strokeLinecap="round" strokeLinejoin="round" className="h-5 w-5" aria-hidden>
      <rect x="3" y="5" width="18" height="16" rx="3" />
      <path d="M8 3v4M16 3v4M3 10h18M12 14v4M10 16h4" />
    </svg>
  );
}

function IconeHistorico() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.7} strokeLinecap="round" strokeLinejoin="round" className="h-5 w-5" aria-hidden>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7v5.3l3.3 2" />
    </svg>
  );
}

function IconePerfil() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.7} strokeLinecap="round" strokeLinejoin="round" className="h-5 w-5" aria-hidden>
      <circle cx="12" cy="8.5" r="3.8" />
      <path d="M4.5 20a7.5 7.5 0 0 1 15 0" />
    </svg>
  );
}

function IconeNovidades() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.7} strokeLinecap="round" strokeLinejoin="round" className="h-5 w-5" aria-hidden>
      <path d="M3 10.5v3a1.5 1.5 0 0 0 1.5 1.5H7l6 4V6.5l-6 4H4.5A1.5 1.5 0 0 0 3 12Z" />
      <path d="M17 9.5a4 4 0 0 1 0 5" />
      <path d="M7 15v4h3" />
    </svg>
  );
}

const ABAS: { href: string; label: string; icon: ReactNode }[] = [
  { href: "/inicio", label: "Início", icon: <IconeInicio /> },
  { href: "/agendar", label: "Agendar", icon: <IconeAgendar /> },
  { href: "/novidades", label: "Novidades", icon: <IconeNovidades /> },
  { href: "/meus-agendamentos", label: "Histórico", icon: <IconeHistorico /> },
  { href: "/perfil", label: "Perfil", icon: <IconePerfil /> },
];

export default function AppTabBar({ isApp }: { isApp: boolean }) {
  const pathname = usePathname();
  if (!isApp) return null;

  return (
    <nav
      aria-label="Navegação principal"
      className="fixed inset-x-0 bottom-0 z-40 border-t border-borda-sutil bg-fundo/95 backdrop-blur-lg"
      style={{ paddingBottom: "env(safe-area-inset-bottom)" }}
    >
      <ul className="mx-auto flex w-full max-w-md items-stretch">
        {ABAS.map((aba) => {
          const ativa =
            pathname === aba.href || pathname.startsWith(`${aba.href}/`);
          return (
            <li key={aba.href} className="flex-1">
              <Link
                href={aba.href}
                aria-current={ativa ? "page" : undefined}
                onClick={() => void hapticImpact()}
                className={`flex min-h-14 flex-col items-center justify-center gap-1 py-2 text-[11px] font-medium transition-colors ${
                  ativa ? "text-ouro" : "text-tinta-fraca hover:text-tinta-suave"
                }`}
              >
                {aba.icon}
                {aba.label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
