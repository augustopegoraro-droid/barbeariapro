/* Seção "Não é apenas um serviço. É uma experiência." — server component,
   zero JS. As 6 fotos (public/ritual/*.webp) são still-life/macro editoriais
   geradas propositalmente sem rosto humano nem cena de atendimento
   "documentada" — ilustram o clima de cada etapa, não fingem ser um
   registro real do salão (ver decisão registrada na conversa que criou
   este componente). */

const ETAPAS = [
  {
    slug: "consulta",
    nome: "Consulta",
    desc: "Ouvimos o que você quer antes de tocar em qualquer tesoura.",
    icone: (
      <>
        <circle cx="12" cy="8" r="3.2" fill="none" strokeWidth={1.4} />
        <path
          d="M5 20c1.5-4 4-5.5 7-5.5S17.5 16 19 20"
          fill="none"
          strokeWidth={1.4}
          strokeLinecap="round"
        />
      </>
    ),
  },
  {
    slug: "corte",
    nome: "Corte",
    desc: "Técnica apurada, risco por risco, para o formato certo.",
    icone: (
      <>
        <circle cx="6" cy="6" r="2.1" fill="none" strokeWidth={1.4} />
        <circle cx="6" cy="18" r="2.1" fill="none" strokeWidth={1.4} />
        <path
          d="M7.6 7.4 20 18M7.6 16.6 20 6"
          strokeWidth={1.4}
          strokeLinecap="round"
        />
      </>
    ),
  },
  {
    slug: "textura",
    nome: "Textura",
    desc: "Camadas e movimento que se ajustam ao seu tipo de fio.",
    icone: (
      <path
        d="M4 6c3 0 3 3 6 3s3-3 6-3 3 3 6 3M4 12c3 0 3 3 6 3s3-3 6-3 3 3 6 3M4 18c3 0 3 3 6 3s3-3 6-3 3 3 6 3"
        fill="none"
        strokeWidth={1.3}
        strokeLinecap="round"
      />
    ),
  },
  {
    slug: "cor",
    nome: "Cor",
    desc: "Coloração e mechas com precisão de tom e reflexo.",
    icone: (
      <path
        d="M12 3c3.5 4 6 7.2 6 10.5A6 6 0 1 1 6 13.5C6 10.2 8.5 7 12 3Z"
        fill="none"
        strokeWidth={1.4}
        strokeLinejoin="round"
      />
    ),
  },
  {
    slug: "finalizacao",
    nome: "Finalização",
    desc: "Escova, secagem e o acabamento que fecha o visual.",
    icone: (
      <>
        <path
          d="M4 19c4-9 8-13 12-14M12 5c2 1 4 3 4 6"
          fill="none"
          strokeWidth={1.4}
          strokeLinecap="round"
        />
        <circle cx="18.5" cy="5.5" r="1.4" fill="none" strokeWidth={1.3} />
      </>
    ),
  },
  {
    slug: "cuidado",
    nome: "Cuidado",
    desc: "Recomendações reais para manter o resultado em casa.",
    icone: (
      <path
        d="M12 20s-7-4.4-7-9.6A4.4 4.4 0 0 1 12 7a4.4 4.4 0 0 1 7 3.4C19 15.6 12 20 12 20Z"
        fill="none"
        strokeWidth={1.4}
        strokeLinejoin="round"
      />
    ),
  },
];

export function Ritual() {
  return (
    <section
      aria-labelledby="experiencia-titulo"
      id="experiencia"
      className="mx-auto w-full max-w-5xl scroll-mt-20 px-5 py-16 sm:px-8"
    >
      <h2
        id="experiencia-titulo"
        className="font-display text-center text-3xl leading-tight font-light text-marfim sm:text-4xl"
      >
        Não é apenas um serviço.
        <br />
        <em className="text-ouro-claro italic">É uma experiência.</em>
      </h2>

      <div className="mt-10 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {ETAPAS.map((etapa, i) => (
          <article
            key={etapa.slug}
            className="overflow-hidden rounded-2xl border border-borda-sutil bg-superficie"
            style={{ boxShadow: "var(--sombra-1)" }}
          >
            <div className="relative aspect-[4/3]">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={`/ritual/${etapa.slug}.webp`}
                alt=""
                aria-hidden
                loading="lazy"
                width={900}
                height={879}
                className="h-full w-full object-cover"
              />
              <div
                aria-hidden
                className="pointer-events-none absolute inset-0"
                style={{
                  background:
                    "linear-gradient(180deg, rgba(10,11,13,0) 40%, rgba(10,11,13,0.94) 100%)",
                }}
              />
              <svg
                className="absolute top-4 left-5 z-10 h-7 w-7 text-ouro-claro"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeLinecap="round"
                style={{ filter: "drop-shadow(0 1px 4px rgba(0,0,0,.6))" }}
                aria-hidden
              >
                {etapa.icone}
              </svg>
              <span className="tnum absolute bottom-3 left-5 z-10 text-xs tracking-[0.14em] text-tinta-fraca">
                {String(i + 1).padStart(2, "0")}
              </span>
            </div>
            <div className="px-6 py-5">
              <h3 className="font-display text-xl text-marfim">
                {etapa.nome}
              </h3>
              <p className="mt-1.5 text-sm text-tinta-suave">{etapa.desc}</p>
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}
