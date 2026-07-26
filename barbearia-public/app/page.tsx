import Link from "next/link";
import { fetchInfo, type PublicInfo, type PublicService } from "@/lib/api";
import { WEEKDAYS_PT } from "@/lib/format";
import { SiteHeader } from "@/components/site-header";
import { Hero } from "@/components/hero";
import {
  Depoimentos,
  NOTA_GOOGLE,
  TOTAL_AVALIACOES,
} from "@/components/depoimentos";
import { Wordmark } from "@/components/wordmark";
import { ServiceLinkRow } from "@/components/ui/service-row";
import { ProfessionalAvatar } from "@/components/ui/professional";
import { EnderecoLegenda, mapsUrl } from "@/components/ui/endereco";
import {
  ContatoBotoes,
  IconeFacebook,
  IconeInstagram,
} from "@/components/ui/contato-botoes";
import { resolverContato } from "@/lib/contato";
import StickyCta from "@/components/sticky-cta";

export const revalidate = 300;

/* schema.org exige os dias em inglês — mandar "Segunda" faz o Google
   descartar o horário inteiro (era o comportamento até 2026-07-25). */
const WEEKDAYS_SCHEMA = [
  "Sunday",
  "Monday",
  "Tuesday",
  "Wednesday",
  "Thursday",
  "Friday",
  "Saturday",
];

function jsonLd(info: PublicInfo, siteUrl: string, endereco: string) {
  return {
    "@context": "https://schema.org",
    "@type": "HairSalon",
    name: info.name,
    url: siteUrl,
    image: `${siteUrl}/fachada.webp`,
    address: {
      "@type": "PostalAddress",
      streetAddress: "LO 01 - Q. 103 Sul, Rua SO 11, 60",
      addressLocality: "Palmas",
      addressRegion: "TO",
      postalCode: "77015-028",
      addressCountry: "BR",
      name: endereco,
    },
    telephone: info.public_info.phone || undefined,
    priceRange: "$$",
    aggregateRating: {
      "@type": "AggregateRating",
      ratingValue: "4.8",
      reviewCount: TOTAL_AVALIACOES,
    },
    openingHoursSpecification: info.hours.map((h) => ({
      "@type": "OpeningHoursSpecification",
      dayOfWeek: WEEKDAYS_SCHEMA[h.weekday],
      opens: h.open_time,
      closes: h.close_time,
    })),
  };
}

function groupedHours(info: PublicInfo) {
  const byDay = new Map<number, string[]>();
  for (const h of info.hours) {
    const list = byDay.get(h.weekday) ?? [];
    list.push(`${h.open_time}–${h.close_time}`);
    byDay.set(h.weekday, list);
  }
  return byDay;
}

/** "9h–19h" — a faixa que cobre todos os dias abertos, para a régua do hero. */
function faixaHorario(info: PublicInfo): string | null {
  if (info.hours.length === 0) return null;
  const hhmm = (t: string) => t.slice(0, 5);
  const abre = info.hours.map((h) => hhmm(h.open_time)).sort()[0];
  const fecha = info.hours
    .map((h) => hhmm(h.close_time))
    .sort()
    .at(-1)!;
  const enxuto = (t: string) =>
    t.endsWith(":00") ? `${Number(t.slice(0, 2))}h` : t;
  return `${enxuto(abre)}–${enxuto(fecha)}`;
}

function porCategoria(servicos: PublicService[]) {
  const grupos = new Map<string, PublicService[]>();
  for (const s of servicos) {
    const chave = s.category?.trim() || "Serviços";
    grupos.set(chave, [...(grupos.get(chave) ?? []), s]);
  }
  return [...grupos.entries()];
}

function TituloSecao({
  rotulo,
  titulo,
  id,
}: {
  rotulo: string;
  titulo: string;
  id: string;
}) {
  return (
    <>
      <p className="flex items-center gap-3">
        <span className="regua-secao" aria-hidden />
        <span className="rotulo text-tinta-suave">{rotulo}</span>
      </p>
      <h2
        id={id}
        className="font-display mt-3 text-3xl leading-tight font-light text-marfim sm:text-4xl"
      >
        {titulo}
      </h2>
    </>
  );
}

export default async function HomePage() {
  let info: PublicInfo | null = null;
  try {
    info = await fetchInfo(revalidate);
  } catch {
    info = null;
  }

  if (!info) {
    return (
      <main className="mx-auto flex min-h-[80dvh] w-full max-w-md flex-col items-center justify-center gap-5 px-6 text-center">
        <Wordmark fontSize={40} />
        <p className="text-tinta-suave">
          Não foi possível carregar as informações agora. Tente novamente em
          instantes.
        </p>
        <Link
          href="/agendar"
          className="cta-agendar inline-flex min-h-14 items-center justify-center rounded-full px-8 text-lg font-semibold"
        >
          Agendar horário
        </Link>
      </main>
    );
  }

  const hours = groupedHours(info);
  const siteUrl =
    process.env.NEXT_PUBLIC_SITE_URL ?? "https://taylorethedy.com";
  const contato = resolverContato(info);
  const endereco = contato.address;
  const grupos = porCategoria(info.services);

  return (
    <>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{
          __html: JSON.stringify(jsonLd(info, siteUrl, endereco)),
        }}
      />

      <SiteHeader
        instagramUrl={contato.instagramUrl}
        facebookUrl={contato.facebookUrl}
      />

      <Hero
        profissionais={info.professionals.length}
        faixaHorario={faixaHorario(info)}
        nota={NOTA_GOOGLE}
        avaliacoes={TOTAL_AVALIACOES}
        endereco={endereco}
      />
      {/* Sentinela: quando o hero sai da viewport, a barra fixa entra (UX A7). */}
      <div id="fim-do-hero" aria-hidden />

      <main>
        {/* Serviços — cada linha agenda direto, com o serviço já escolhido (UX A6) */}
        <section
          aria-labelledby="servicos-titulo"
          id="servicos"
          className="mx-auto w-full max-w-5xl scroll-mt-20 px-5 py-16 sm:px-8"
        >
          <TituloSecao
            rotulo="Serviços"
            titulo="Preço fechado, duração real"
            id="servicos-titulo"
          />
          <p className="mt-3 max-w-[52ch] text-tinta-suave">
            Toque em um serviço para agendar já com ele selecionado.
          </p>

          <div className="mt-8 grid gap-x-12 gap-y-10 sm:grid-cols-2">
            {grupos.map(([categoria, servicos]) => (
              <div key={categoria}>
                <h3 className="rotulo text-ouro">{categoria}</h3>
                <ul className="mt-2 divide-y divide-borda-sutil">
                  {servicos.map((s) => (
                    <li key={s.id}>
                      <ServiceLinkRow service={s} />
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </section>

        {/* A casa — fotos reais da fachada e da vista aérea */}
        <section
          aria-labelledby="casa"
          className="mx-auto w-full max-w-5xl px-5 py-16 sm:px-8"
        >
          <TituloSecao rotulo="O espaço" titulo="Nossa casa" id="casa" />
          <div className="mt-8 grid items-start gap-4 sm:grid-cols-2 lg:grid-cols-1">
            {/* A fachada já abre o hero no desktop — aqui ela só aparece nas
                larguras em que o hero não a mostra, para não repetir a foto. */}
            <figure className="lg:hidden">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src="/fachada.webp"
                alt="Fachada da Taylor e Thedy, no Plano Diretor Sul, em Palmas"
                loading="lazy"
                className="aspect-[4/3] w-full rounded-2xl border border-borda-sutil object-cover"
              />
              <EnderecoLegenda endereco={endereco} />
            </figure>
            {/* Enquadramento deliberadamente diferente do da fachada: aérea
                com a loja no contexto da avenida e a skyline de Palmas ao
                fundo. O `hero-poster.jpg` que estava aqui era outro quadro do
                mesmo drone, quase idêntico à foto de cima — no celular, onde
                as duas empilham, virava a mesma imagem repetida. */}
            <figure>
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src="/vista-aerea.webp"
                alt="Vista aérea da Taylor e Thedy na avenida, com a skyline de Palmas ao fundo"
                loading="lazy"
                width={1400}
                height={1050}
                className="aspect-[4/3] w-full rounded-2xl border border-borda-sutil object-cover"
              />
              {/* Ponto de referência que o cliente de Palmas reconhece — a
                  Don Pneus aparece na própria foto, à esquerda. */}
              <figcaption className="mt-3 text-sm text-tinta-suave">
                Ao lado da Don Pneus
              </figcaption>
            </figure>
          </div>
        </section>

        {/* Prova social — avaliações públicas do Google */}
        <section
          aria-labelledby="clientes"
          className="mx-auto w-full max-w-5xl px-5 py-16 sm:px-8"
        >
          <TituloSecao
            rotulo="Clientes"
            titulo={`${NOTA_GOOGLE} em ${TOTAL_AVALIACOES} avaliações`}
            id="clientes"
          />
          <Depoimentos />
        </section>

        {/* Equipe */}
        {info.professionals.length > 0 && (
          <section
            aria-labelledby="equipe-titulo"
            id="equipe"
            className="mx-auto w-full max-w-5xl scroll-mt-20 px-5 py-16 sm:px-8"
          >
            <TituloSecao
              rotulo="Equipe"
              titulo="Quem atende"
              id="equipe-titulo"
            />
            <ul className="mt-8 grid gap-3 sm:grid-cols-3">
              {info.professionals.map((p) => (
                <li
                  key={p.id}
                  className="flex items-center gap-3 rounded-2xl border border-borda-sutil bg-superficie px-5 py-4"
                  style={{ boxShadow: "var(--sombra-1)" }}
                >
                  <ProfessionalAvatar name={p.name} />
                  <span>
                    <span className="block font-medium text-marfim">
                      {p.name}
                    </span>
                    {p.specialty && (
                      <span className="block text-xs text-tinta-fraca">
                        {p.specialty}
                      </span>
                    )}
                  </span>
                </li>
              ))}
            </ul>
          </section>
        )}

        {/* Onde e quando */}
        <section
          aria-labelledby="visite-titulo"
          id="visite"
          className="mx-auto w-full max-w-5xl scroll-mt-20 px-5 py-16 sm:px-8"
        >
          <TituloSecao
            rotulo="Visite"
            titulo="Onde e quando"
            id="visite-titulo"
          />

          <div className="mt-8 grid gap-6 sm:grid-cols-2">
            {hours.size > 0 && (
              <div
                className="rounded-2xl border border-borda-sutil bg-superficie p-6"
                style={{ boxShadow: "var(--sombra-1)" }}
              >
                <h3 className="rotulo text-ouro">Horário de funcionamento</h3>
                <ul className="mt-4 space-y-1 text-sm">
                  {WEEKDAYS_PT.map((label, weekday) => (
                    <li key={weekday} className="flex justify-between py-1">
                      <span
                        className={hours.has(weekday) ? "" : "text-tinta-fraca"}
                      >
                        {label}
                      </span>
                      <span className="tnum text-tinta-suave">
                        {hours.get(weekday)?.join(" · ") ?? "Fechado"}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            <div
              className="flex flex-col rounded-2xl border border-borda-sutil bg-superficie p-6"
              style={{ boxShadow: "var(--sombra-1)" }}
            >
              <h3 className="rotulo text-ouro">Endereço</h3>
              <p className="mt-4 text-sm text-tinta-suave">{endereco}</p>
              <a
                href={mapsUrl(endereco)}
                target="_blank"
                rel="noopener noreferrer"
                className="mt-2 inline-flex min-h-11 items-center text-sm text-ouro transition-colors hover:text-ouro-claro"
              >
                Abrir no mapa →
              </a>

              <h3 className="rotulo mt-6 text-ouro">Fale com a gente</h3>
              <ContatoBotoes contato={contato} className="mt-3" />
            </div>
          </div>
        </section>

        {/* Fechamento — ninguém precisa rolar de volta ao hero para agendar */}
        <section className="mx-auto w-full max-w-5xl px-5 pb-16 sm:px-8">
          <div
            className="rounded-3xl border border-borda-sutil bg-superficie px-6 py-12 text-center"
            style={{ boxShadow: "var(--sombra-2)" }}
          >
            <h2 className="font-display text-3xl leading-tight font-light text-marfim">
              Renove seu estilo.
            </h2>
            <p className="mx-auto mt-3 max-w-[40ch] text-tinta-suave">
              Escolha o serviço, o profissional e o horário. Leva menos de um
              minuto.
            </p>
            <Link
              href="/agendar"
              className="cta-agendar mx-auto mt-8 flex min-h-14 w-full max-w-sm items-center justify-center rounded-full px-8 text-lg font-semibold"
            >
              Agendar horário
            </Link>
          </div>
        </section>
      </main>

      <footer className="border-t border-borda-sutil">
        <div className="mx-auto flex w-full max-w-5xl flex-col gap-6 px-5 py-10 pb-40 sm:flex-row sm:items-end sm:justify-between sm:px-8 sm:pb-16">
          <div>
            <Wordmark fontSize={22} />
            <p className="mt-3 text-sm text-tinta-fraca">
              Renove seu estilo · Palmas, Tocantins
            </p>
          </div>
          <div className="flex flex-wrap gap-4 text-sm">
            <Link
              href="/agendar"
              className="inline-flex min-h-11 items-center text-ouro transition-colors hover:text-ouro-claro"
            >
              Agendar
            </Link>
            <Link
              href="/meus-agendamentos"
              className="inline-flex min-h-11 items-center text-tinta-suave transition-colors hover:text-marfim"
            >
              Meus agendamentos
            </Link>
            <a
              href={`https://wa.me/${contato.whatsappDigits}`}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex min-h-11 items-center text-tinta-suave transition-colors hover:text-marfim"
            >
              WhatsApp
            </a>
            <a
              href={contato.instagramUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex min-h-11 items-center gap-1.5 text-tinta-suave transition-colors hover:text-marfim"
            >
              <IconeInstagram />
              Instagram
            </a>
            <a
              href={contato.facebookUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex min-h-11 items-center gap-1.5 text-tinta-suave transition-colors hover:text-marfim"
            >
              <IconeFacebook />
              Facebook
            </a>
          </div>
        </div>
      </footer>

      <StickyCta />
    </>
  );
}
