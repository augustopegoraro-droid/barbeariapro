/* Lockup da marca Taylor & Thedy, fiel ao letreiro da fachada (D-79): as
   palavras "Taylor" e "hedy" (Optima) em linha, com o "T" maiúsculo serifado
   MONUMENTAL do Didot entre elas — lendo TaylorThedy (o "T" grande é o de
   Thedy). Prata cromada sobre o grafite, como na placa.

   As letras são ARTE FINAL vetorial (outlines em components/logo-paths.ts,
   extraídos via fontTools): o logo não depende de webfont e é idêntico em
   qualquer aparelho. */

import { HEDY_D, HEDY_W, SLOGAN_D, SLOGAN_W, TAYLOR_D, TAYLOR_W, TEE_D } from "@/components/logo-paths";

// Proporções do "T" monumental relativas às palavras (Optima, em=1000).
const TEE_SCALE = 1.6; // altura ~1.6× a caixa-alta das palavras
const TEE_GAP_L = 30; // folga "Taylor" → "T"
const TEE_GAP_R = 30; // folga "T" → "hedy"
const TEE_DROP = -40; // pé do "T" cai um pouco abaixo da linha de base (como na placa)

// Geometria do lockup (unidades em, baseline y=0, y para cima).
const TEE_X = TAYLOR_W + TEE_GAP_L;
const TEE_ADV = 684 * TEE_SCALE; // avanço do glifo Didot (684) escalado
const HEDY_X = TEE_X + TEE_ADV + TEE_GAP_R;
const NAME_W = HEDY_X + HEDY_W;
const CAP_TOP = 712 * TEE_SCALE; // topo do "T" (mais alto que as palavras)

// "T" Didot (em=1000, baseline y=0). Renderizado DENTRO do grupo do lockup, que
// já aplica scale(1,-1) — por isso o escalonamento aqui é positivo (só amplia).
function Tee() {
  return (
    <g transform={`translate(${TEE_X},${TEE_DROP}) scale(${TEE_SCALE},${TEE_SCALE})`}>
      <path d={TEE_D} fill="var(--prata)" />
    </g>
  );
}

export function LogoMark({ size = 72 }: { size?: number }) {
  // Só o "T" da marca, centrado com folga leve.
  return (
    <svg width={size} height={size} viewBox="0 -6 684 724" aria-hidden>
      <g transform="translate(0,712) scale(1,-1)">
        <path d={TEE_D} fill="var(--prata)" />
      </g>
    </svg>
  );
}

export function LogoLockup({ width = 320 }: { width?: number }) {
  const sloganScale = 3.0;
  const sloganX = NAME_W / 2 - (SLOGAN_W * sloganScale) / 2;
  const viewH = CAP_TOP + 600; // caixa-alta + descidas + slogan
  return (
    <svg
      width={width}
      height={(width * viewH) / NAME_W}
      viewBox={`0 0 ${NAME_W.toFixed(0)} ${viewH.toFixed(0)}`}
      role="img"
      aria-label="Taylor e Thedy — Renove seu Estilo"
    >
      {/* Palavras + "T" monumental, na mesma linha de base (y=CAP_TOP no SVG) */}
      <g transform={`translate(0,${CAP_TOP.toFixed(1)}) scale(1,-1)`} fill="var(--prata)">
        <path d={TAYLOR_D} />
        <Tee />
        <g transform={`translate(${HEDY_X.toFixed(1)},0)`}>
          <path d={HEDY_D} />
        </g>
      </g>
      {/* Arial Rounded MT Bold, centralizado abaixo do nome */}
      <g
        transform={`translate(${sloganX.toFixed(1)},${(CAP_TOP + 380).toFixed(1)}) scale(${sloganScale})`}
        fill="var(--prata)"
      >
        <path d={SLOGAN_D} />
      </g>
    </svg>
  );
}
