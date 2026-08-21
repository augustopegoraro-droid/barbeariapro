"use client";

/* Conteúdo da home do modo app. Tudo que ela mostra depende da sessão de
   cliente (cookie HttpOnly, D-79), então é client-side: o nome vem do
   localStorage (memória de UX, mesma chave do fluxo de agendamento) e o
   próximo horário vem de `GET /me/appointments`. */

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, ApiError, type PublicAppointment } from "@/lib/api";
import { dateLong, money, timeHM } from "@/lib/format";
import { SolidLink } from "@/components/ui/buttons";
import { Wordmark } from "@/components/wordmark";
import RegistrarPushNativo from "@/components/registrar-push-nativo";

const KNOWN_NAME_KEY = "tt_client_name";

function primeiroNome(nome: string): string {
  return nome.trim().split(/\s+/)[0] ?? nome;
}

function saudacao(): string {
  const h = new Date().getHours();
  if (h < 12) return "Bom dia";
  if (h < 18) return "Boa tarde";
  return "Boa noite";
}

const ATALHO =
  "flex min-h-14 flex-1 items-center justify-center rounded-xl border border-borda-sutil bg-superficie px-4 py-3 text-sm font-medium text-marfim transition-colors hover:border-ouro hover:text-ouro";

export default function InicioCliente() {
  const [nome, setNome] = useState<string | null>(null);
  const [proximo, setProximo] = useState<PublicAppointment | null>(null);
  const [carregando, setCarregando] = useState(true);

  useEffect(() => {
    setNome(localStorage.getItem(KNOWN_NAME_KEY));
    void (async () => {
      try {
        const itens = await api.myAppointments();
        const agora = Date.now();
        const futuros = itens
          .filter(
            (a) => a.status === "agendado" && new Date(a.start_at).getTime() > agora,
          )
          .sort(
            (a, b) =>
              new Date(a.start_at).getTime() - new Date(b.start_at).getTime(),
          );
        setProximo(futuros[0] ?? null);
      } catch (e) {
        // 401 = sem sessão neste aparelho: a home segue valendo, só sem o card.
        if (!(e instanceof ApiError)) setProximo(null);
      } finally {
        setCarregando(false);
      }
    })();
  }, []);

  return (
    <main className="mx-auto w-full max-w-md px-6 pt-10 pb-16">
      <header>
        <Wordmark fontSize={17} />
        <h1 className="mt-4 font-display text-3xl text-tinta">
          {saudacao()}
          {nome ? `, ${primeiroNome(nome)}` : ""}.
        </h1>
        <p className="mt-1 text-tinta-suave">Pronto para renovar o estilo?</p>
      </header>

      <section className="mt-8" aria-label="Próximo horário">
        {carregando && (
          <p aria-live="polite" className="text-tinta-suave">
            Carregando…
          </p>
        )}

        {!carregando && proximo && (
          <Link
            href="/meus-agendamentos"
            className="block rounded-xl border border-borda-sutil bg-superficie p-5 transition-colors hover:border-ouro"
            style={{ boxShadow: "var(--sombra-1)" }}
          >
            <p className="rotulo text-ouro">
              <span className="regua-secao mr-2" aria-hidden />
              Seu próximo horário
            </p>
            <p className="mt-3 font-medium text-tinta">{proximo.service_name}</p>
            <p className="mt-1 text-sm text-tinta-suave">
              {dateLong(proximo.start_at)} às{" "}
              <span className="tnum">{timeHM(proximo.start_at)}</span>
            </p>
            <p className="text-sm text-tinta-suave">com {proximo.barber_name}</p>
            <p className="mt-3 font-display text-lg text-tinta tnum">
              {money(proximo.total_amount)}
            </p>
          </Link>
        )}

        {!carregando && !proximo && (
          <div
            className="rounded-xl border border-borda-sutil bg-superficie p-5 text-tinta-suave"
            style={{ boxShadow: "var(--sombra-1)" }}
          >
            Você não tem horário marcado. Escolha um serviço e a gente cuida do
            resto.
          </div>
        )}
      </section>

      <div className="mt-6">
        <SolidLink href="/agendar">Agendar horário</SolidLink>
      </div>

      <nav aria-label="Atalhos" className="mt-4 flex gap-3">
        <Link href="/meus-agendamentos" className={ATALHO}>
          Meus agendamentos
        </Link>
        <Link href="/perfil" className={ATALHO}>
          Perfil
        </Link>
      </nav>

      <RegistrarPushNativo />
    </main>
  );
}
