/* Hero da landing (UI_SPEC_V3 §3) — server component, zero JS.

   Hierarquia deliberada: marca → promessa → prova (nota do Google) → AÇÃO.
   O CTA fica acima da dobra em qualquer altura de tela e é o único elemento
   dourado sólido da região; "Meus agendamentos" vem logo abaixo, discreto,
   porque é o caminho de quem já é cliente. A faixa de números fecha o bloco
   com o que o cliente pergunta antes de marcar: quantos profissionais e que
   horas abre. */

import Link from "next/link";
import { Wordmark } from "@/components/wordmark";
import { EnderecoLegenda } from "@/components/ui/endereco";

/* Tempo de casa — confirmado pelo dono em 2026-07-25. É o único número da
   régua que não vem da API; se mudar, muda aqui. */
export const ANOS_DE_CASA = "25 anos";

export function Hero({
  profissionais,
  faixaHorario,
  nota,
  avaliacoes,
  endereco,
}: {
  profissionais: number;
  faixaHorario: string | null;
  nota: string;
  avaliacoes: number;
  endereco: string;
}) {
  const numeros = [
    { valor: ANOS_DE_CASA, rotulo: "Em Palmas", estrelas: false },
    {
      valor: nota,
      rotulo: `${avaliacoes} avaliações · Google`,
      estrelas: true,
    },
    profissionais > 0
      ? {
          valor: String(profissionais),
          rotulo: "Profissionais",
          estrelas: false,
        }
      : null,
    faixaHorario
      ? { valor: faixaHorario, rotulo: "Funcionamento", estrelas: false }
      : null,
  ].filter(
    (n): n is { valor: string; rotulo: string; estrelas: boolean } =>
      n !== null,
  );

  /* No mobile a régua quebra em 2 colunas; a partir de sm cada número ganha a
     sua, seja qual for a quantidade que sobreviveu aos dados da API. */
  const colunas =
    { 2: "sm:grid-cols-2", 3: "sm:grid-cols-3", 4: "sm:grid-cols-4" }[
      numeros.length
    ] ?? "sm:grid-cols-4";

  return (
    <section className="relative overflow-hidden">
      {/* Halo dourado atrás da marca — a luz da placa iluminada à noite */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-x-0 top-0 h-[420px]"
        style={{
          background:
            "radial-gradient(60% 60% at 50% 0%, rgba(201,168,106,0.14) 0%, transparent 70%)",
        }}
      />

      <div className="relative mx-auto grid w-full max-w-5xl gap-12 px-5 pt-14 pb-12 sm:px-8 sm:pt-20 lg:grid-cols-[minmax(0,1fr)_minmax(0,26rem)] lg:items-center">
        <div>
          <h1 aria-label="Taylor e Thedy — Renove seu estilo">
            <Wordmark fontSize={44} className="sm:hidden" />
            <Wordmark fontSize={64} className="hidden sm:flex" />
            <span className="font-display mt-6 block text-3xl leading-[1.1] font-light text-marfim sm:text-5xl">
              Renove seu estilo.
            </span>
          </h1>

          <p className="mt-4 max-w-[46ch] text-tinta-suave">
            Salão e barbearia no Plano Diretor Sul há {ANOS_DE_CASA}. Corte,
            barba, coloração e sobrancelha com hora marcada — sem fila de
            espera.
          </p>

          <p className="mt-5 flex items-center gap-2 text-sm text-tinta-suave">
            <span aria-hidden className="text-ouro">
              ★
            </span>
            <span className="tnum text-marfim">{nota}</span>
            <span>· {avaliacoes} avaliações no Google</span>
          </p>

          <div className="mt-8 flex max-w-md flex-col gap-3">
            <Link
              href="/agendar"
              className="cta-agendar group flex min-h-14 w-full items-center justify-center gap-2 rounded-full px-6 py-4 text-lg font-semibold tracking-wide"
            >
              <span className="relative z-10">Agendar horário</span>
              <svg
                className="relative z-10 h-5 w-5 transition-transform duration-200 group-hover:translate-x-1"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth={2.4}
                strokeLinecap="round"
                strokeLinejoin="round"
                aria-hidden
              >
                <path d="M5 12h14M13 6l6 6-6 6" />
              </svg>
            </Link>
            <Link
              href="/meus-agendamentos"
              className="inline-flex min-h-11 items-center justify-center text-sm text-tinta-suave underline underline-offset-4 transition-colors hover:text-marfim"
            >
              Ver meus agendamentos
            </Link>
          </div>

          {numeros.length > 0 && (
            <dl
              className={`mt-12 grid grid-cols-2 gap-px overflow-hidden rounded-2xl border border-borda-sutil bg-borda-sutil ${colunas}`}
            >
              {numeros.map((n) => (
                <div key={n.rotulo} className="bg-fundo px-4 py-5 text-center">
                  <dt className="tnum text-2xl font-semibold tracking-tight text-ouro">
                    {n.valor}
                    {n.estrelas && (
                      <span
                        aria-hidden
                        className="ml-1 align-middle text-[0.5em] tracking-[0.06em] text-ouro"
                      >
                        ★★★★★
                      </span>
                    )}
                  </dt>
                  <dd className="mt-1 text-xs text-tinta-fraca">{n.rotulo}</dd>
                </div>
              ))}
            </dl>
          )}
        </div>

        {/* Só no desktop: a fachada ocupa a coluna que sobraria vazia. Abaixo
            de lg ela some daqui e aparece na seção "Nossa casa" — a foto nunca
            se repete na mesma largura de tela. */}
        <figure className="hidden lg:block">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src="/fachada.webp"
            alt="Fachada da Taylor e Thedy, no Plano Diretor Sul, em Palmas"
            width={1600}
            height={1376}
            className="w-full rounded-3xl border border-borda-sutil object-cover"
            style={{ boxShadow: "var(--sombra-3)" }}
          />
          <EnderecoLegenda endereco={endereco} />
        </figure>
      </div>
    </section>
  );
}
