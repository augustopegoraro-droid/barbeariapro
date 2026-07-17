/* Lockup da marca Taylor & Thedy, recriado da FACHADA real (D-79, v2 fiel à
   foto da placa): ligadura caligráfica "lt" — um "l" fino à esquerda e um "t"
   de haste larga com cabeça em curl, bandeira em vírgula (baseline do
   "aylor") e bojo de ponta erguida (altura-x do "hedy"). O traço fica
   grafite DENTRO do painel claro e prata fora dele, como na placa.
   Inline SVG: os <text> herdam as webfonts da página (Tenor Sans ≈ Optima
   da placa; Quicksand ≈ o rounded do slogan). */

const LIG = `
  M 76 96 C 74 56 94 34 130 28 C 162 23 188 26 210 34
  C 246 48 264 94 258 150 C 254 196 238 210 222 196
  C 228 140 214 120 198 112 L 198 428
  C 198 500 224 532 248 518 C 263 508 268 486 270 450
  L 280 436 C 281 506 254 570 202 584 C 148 598 124 542 120 458
  L 114 116 C 96 114 78 108 76 96 Z
  M 44 14 L 66 14 C 64 160 64 300 68 446 L 46 446 C 42 300 42 160 44 14 Z`;

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
