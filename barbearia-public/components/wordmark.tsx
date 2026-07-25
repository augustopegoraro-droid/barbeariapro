/* Wordmark oficial — a peça da fachada real (assets/images/fachada-real.png).

   Anatomia: a placa marfim com o "t" VAZADO (public/t-fachada.png, 746×1334,
   alfa real) à esquerda, e as palavras "aylor" / "hedy" empilhadas à direita —
   exatamente como o letreiro. Regras herdadas do pacote de marca:

   - o "t" NUNCA é fonte nem SVG desenhado à mão; é sempre esse PNG;
   - o recorte mostra o fundo da página, então o wordmark exige fundo escuro;
   - a placa mede ≈1,86× o font-size das palavras e alinha pelo topo, de modo
     que ultrapassa o "aylor" em cima e a linha do "hedy" embaixo. */

const PROPORCAO_PLACA = 746 / 1334;

export function Wordmark({
  fontSize = 19,
  className = "",
}: {
  fontSize?: number;
  className?: string;
}) {
  const alturaPlaca = fontSize * 1.86;

  return (
    <span className={`flex items-start gap-[1px] ${className}`}>
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src="/t-fachada.png"
        alt=""
        aria-hidden
        width={Math.round(alturaPlaca * PROPORCAO_PLACA)}
        height={Math.round(alturaPlaca)}
        style={{ height: alturaPlaca, width: "auto" }}
        className="mr-[5px] block flex-none"
      />
      <span
        className="font-display flex flex-col gap-px"
        style={{
          fontSize,
          lineHeight: 0.78,
          letterSpacing: "0.02em",
          paddingTop: fontSize * 0.1,
        }}
      >
        <span>aylor</span>
        <span>hedy</span>
      </span>
    </span>
  );
}
