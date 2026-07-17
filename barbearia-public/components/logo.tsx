/* Lockup da marca Taylor & Thedy, recriado da fachada real (D-79):
   ligadura dupla de "t" — o mesmo glifo é o T de Taylor (linha de cima) e o
   T de Thedy (linha de baixo); dentro do quadrado claro o traço inverte para
   grafite, fora fica prata. Inline SVG: os <text> herdam a webfont da página. */

const MARK = `
  M 196 28 Q 138 28 138 92 L 138 116 L 106 116 L 106 148 L 138 148
  L 138 230 L 106 230 L 106 262 L 138 262 L 138 330 Q 138 396 204 396
  L 246 396 L 246 362 L 210 362 Q 174 362 174 324 L 174 262 L 250 262
  L 250 230 L 174 230 L 174 148 L 250 148 L 250 116 L 174 116 L 174 94
  Q 174 62 200 62 L 216 62 L 216 28 Z`;

export function LogoMark({ size = 72 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={(size * 440) / 400}
      viewBox="0 0 400 440"
      aria-hidden
    >
      <defs>
        <clipPath id="tt-box">
          <rect x="36" y="16" width="180" height="192" />
        </clipPath>
      </defs>
      <rect x="36" y="16" width="180" height="192" fill="var(--prata)" />
      <path d={MARK} fill="var(--prata-suave)" />
      <path d={MARK} fill="var(--grafite)" clipPath="url(#tt-box)" />
    </svg>
  );
}

export function LogoLockup({ width = 300 }: { width?: number }) {
  return (
    <svg
      width={width}
      height={(width * 300) / 640}
      viewBox="0 0 640 300"
      role="img"
      aria-label="Taylor e Thedy"
    >
      <defs>
        <clipPath id="tt-box-l">
          <rect x="10" y="0" width="126" height="134" />
        </clipPath>
      </defs>
      <g transform="translate(0,-6) scale(0.7)">
        <rect x="14" y="10" width="180" height="192" fill="var(--prata)" />
        <path d={MARK} transform="translate(-22,-18)" fill="var(--prata-suave)" />
        <path
          d={MARK}
          transform="translate(-22,-18)"
          fill="var(--grafite)"
          clipPath="url(#tt-box-l)"
        />
      </g>
      <text
        x="188"
        y="102"
        fontFamily="var(--font-tenor), Georgia, serif"
        fontSize="106"
        letterSpacing="6"
        fill="var(--prata)"
      >
        aylor
      </text>
      <text
        x="188"
        y="212"
        fontFamily="var(--font-tenor), Georgia, serif"
        fontSize="106"
        letterSpacing="6"
        fill="var(--prata)"
      >
        hedy
      </text>
      <text
        x="192"
        y="272"
        fontFamily="var(--font-quicksand), system-ui, sans-serif"
        fontSize="34"
        fontWeight="600"
        letterSpacing="3"
        fill="var(--prata-suave)"
      >
        Renove seu Estilo
      </text>
    </svg>
  );
}
