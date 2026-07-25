/* Prova social (UI_SPEC_V3 §5) — depoimentos REAIS publicados no Google.

   Fonte: exportação de 24/07/2026 (`Avaliaçoesgoogle.pdf`, no repo do backend).
   Nota 4,8 em 400 avaliações. Só entram aqui textos verbatim de avaliações
   públicas, com o nome que a pessoa já exibe no Google. Nada é inventado nem
   parafraseado — se um depoimento sair do ar, ele sai daqui também. */

export const NOTA_GOOGLE = "4,8";
export const TOTAL_AVALIACOES = 400;

export const DEPOIMENTOS = [
  {
    texto:
      "Melhor corte de Palmas. Eles atendem todos artistas famosos que vem p Palmas",
    autor: "Augusto Pegoraro",
  },
  {
    texto:
      "Impecáveis no corte de cabelo! Trago meus filhos há anos para cortar com eles e o atendimento sempre é excelente. Super indico — para mim, são os melhores de Palmas!",
    autor: "Rafaella Catani",
  },
] as const;

export function Depoimentos() {
  return (
    <ul className="mt-8 grid gap-4 sm:grid-cols-2">
      {DEPOIMENTOS.map((d) => (
        <li
          key={d.autor}
          className="rounded-2xl border border-borda-sutil bg-superficie p-6"
          style={{ boxShadow: "var(--sombra-1)" }}
        >
          <p aria-hidden className="text-ouro">
            ★★★★★
          </p>
          <blockquote className="font-display mt-3 text-xl leading-snug font-light text-marfim">
            “{d.texto}”
          </blockquote>
          <p className="mt-4 text-sm text-tinta-fraca">{d.autor} · Google</p>
        </li>
      ))}
    </ul>
  );
}
