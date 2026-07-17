/* Lockup da marca Taylor & Thedy, recriado da FACHADA real (D-79): um único
   "t" caligráfico dentro da caixa clara alta — cabeça em curl, bandeira em
   vírgula (baseline do "aylor") e bojo de ponta erguida (altura-x do
   "hedy"). O traço fica grafite DENTRO da caixa e prata fora dela, como na
   placa. Inline SVG: os <text> herdam as webfonts da página (Tenor Sans ≈
   Optima da placa; Quicksand ≈ o rounded do slogan). */

const LIG = `
  M 60 96 C 58 56 78 34 114 28 C 146 23 172 26 194 34
  C 230 48 248 94 242 150 C 238 196 222 210 206 196
  C 212 140 198 120 182 112 L 182 428
  C 182 500 208 532 232 518 C 247 508 252 486 254 450
  L 264 436 C 265 506 238 570 186 584 C 132 598 108 542 104 458
  L 98 116 C 80 114 62 108 60 96 Z`;

function Mark({ clipId }: { clipId: string }) {
  return (
    <>
      <defs>
        <clipPath id={clipId}>
          <rect x="18" y="10" width="248" height="558" />
        </clipPath>
      </defs>
      <rect x="18" y="10" width="248" height="558" fill="var(--prata)" />
      <path d={LIG} fill="var(--prata-suave)" />
      <path d={LIG} fill="var(--grafite)" clipPath={`url(#${clipId})`} />
    </>
  );
}

export function LogoMark({ size = 72 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={(size * 640) / 300}
      viewBox="0 0 300 640"
      aria-hidden
    >
      <Mark clipId="tt-mark" />
    </svg>
  );
}

export function LogoLockup({ width = 300 }: { width?: number }) {
  return (
    <svg
      width={width}
      height={(width * 700) / 1000}
      viewBox="0 0 1000 700"
      role="img"
      aria-label="Taylor e Thedy — Renove seu Estilo"
    >
      <Mark clipId="tt-lockup" />
      <text
        x="308"
        y="205"
        fontFamily="var(--font-tenor), Georgia, serif"
        fontSize="250"
        letterSpacing="4"
        fill="var(--prata)"
        textLength="660"
      >
        aylor
      </text>
      <text
        x="308"
        y="540"
        fontFamily="var(--font-tenor), Georgia, serif"
        fontSize="250"
        letterSpacing="4"
        fill="var(--prata)"
        textLength="640"
      >
        hedy
      </text>
      <text
        x="520"
        y="672"
        fontFamily="var(--font-quicksand), system-ui, sans-serif"
        fontSize="62"
        fontWeight="700"
        letterSpacing="2"
        textAnchor="middle"
        fill="var(--prata)"
      >
        Renove seu Estilo
      </text>
    </svg>
  );
}
