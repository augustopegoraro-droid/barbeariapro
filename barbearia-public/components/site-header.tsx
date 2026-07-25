/* Cabeçalho fixo da landing (UI_SPEC_V3 §2): wordmark à esquerda, âncoras de
   seção no meio e o CTA sempre visível à direita — em telas estreitas as
   âncoras somem e sobra o essencial (marca + agendar). Server component. */

import Link from "next/link";
import { Wordmark } from "@/components/wordmark";

const SECOES = [
  { href: "#servicos", label: "Serviços" },
  { href: "#equipe", label: "Equipe" },
  { href: "#visite", label: "Horários" },
];

export function SiteHeader() {
  return (
    <header className="sticky top-0 z-40 border-b border-borda-sutil bg-fundo/85 backdrop-blur-lg">
      <div className="mx-auto flex w-full max-w-5xl items-center justify-between gap-6 px-5 py-3 sm:px-8">
        <Link href="/" aria-label="Taylor e Thedy — início" className="text-marfim">
          <Wordmark fontSize={19} />
        </Link>

        <nav aria-label="Seções" className="hidden items-center gap-7 sm:flex">
          {SECOES.map((s) => (
            <a
              key={s.href}
              href={s.href}
              className="rotulo flex min-h-11 items-center text-tinta-suave transition-colors hover:text-marfim"
            >
              {s.label}
            </a>
          ))}
        </nav>

        <Link
          href="/agendar"
          className="inline-flex min-h-11 items-center rounded-full border border-ouro px-5 text-xs font-medium tracking-[0.16em] text-ouro uppercase transition-colors hover:bg-ouro hover:text-tinta-invertida"
        >
          Agendar
        </Link>
      </div>
    </header>
  );
}
