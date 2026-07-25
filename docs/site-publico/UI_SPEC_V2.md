# UI_SPEC_V2 — Site Público Taylor & Thedy · Tema Claro ("A placa à luz do dia")

> **Status:** substitui as premissas visuais do `UI_SPEC.md` (v1) por decisão do dono (2026-07-22):
> o vídeo de drone **sai** do hero e o tema grafite escuro **deixa de ser a base**. O v1 permanece no
> repositório como histórico e como referência de anatomia/estados (que **não mudam**). O
> `UX_PLAN.md` segue 100% válido — nenhum fluxo, microcopy ou comportamento muda.
>
> **Escopo desta v2:** direção da identidade clara, tokens completos, releitura dos 12 componentes
> (só deltas de valor/tratamento) e o hero novo + `sticky-cta` + rodapé. A migração foi desenhada
> para ser **mecânica**: §1.9 traz a tabela token-a-token e classe-a-classe.

---

## 0. Direção — "A placa à luz do dia"

A identidade v1 era a placa da fachada **à noite**: o site inteiro era a chapa navy. A v2 vira a
mesma placa para **a luz do dia de Palmas**: a página é clara, arejada e moderna — e o navy da
fachada (`#262c36`) **não desaparece: ele se concentra**. Deixa de ser fundo e vira **tinta e
assinatura**: é a cor de todo o texto, do CTA e de uma única **faixa navy no topo** onde a logo
cromada vive intocada (a logo é prata — ela nunca pousa sobre fundo claro; ela carrega o próprio
pedaço da fachada consigo). O resultado é premium e masculino sem ser escuro: neutros frios
(nada de cream/bege), branco de porcelana, aço claro nos cinzas, navy denso como acento —
uma barbearia sofisticada, não uma clínica.

Três regras que definem a v2:
1. **Navy é acento, não fundo** — aparece em exatamente 4 lugares: faixa da logo (header), CTA,
   estados selecionados e a listra `.stripe`. Quanto menos navy, mais forte ele fica.
2. **A logo cromada só existe sobre navy** (§3.3 do v1 continua valendo: nunca recolorir o webp).
   Onde precisar da marca sobre claro, usa-se o **`LogoMark`** (o "T" vetorial de `logo.tsx`) com
   `fill: var(--tinta)` — SVG recolore sem perda.
3. **Profundidade vem de sombra, não de camada de cor** — inversão do v1: no claro, os cards são
   brancos sobre `#f5f6f8` com sombras frias sutis; a escadinha de cinzas fica para insets/hover.

---

## 1. Design tokens v2

Mesma mecânica do projeto: `:root` + `@theme inline` em `app/globals.css`. **Estratégia de
migração:** a v2 introduz uma camada **semântica** (`--fundo`, `--superficie`, `--tinta`…) e os
componentes migram de classe por busca-e-troca (tabela §1.9). Os tokens v1 (`--grafite`,
`--prata`…) **permanecem declarados** — a faixa navy, o CTA e a logo os usam.

### 1.1 Fundos claros em camadas

| Token | Valor | Uso |
|---|---|---|
| `--fundo` | `#f5f6f8` | Camada 0: fundo da página (`html`) — branco-aço frio, nunca cream |
| `--superficie` | `#ffffff` | Camada 1: cards, inputs, toast, sticky-cta |
| `--superficie-2` | `#eceef1` (= antigo `--prata`) | Camada 2: inset dentro de card, hover de item claro, base de skeleton, chip neutro |
| `--superficie-3` | `#dfe3e9` (= antigo `--destaque`) | Camada 3: hover sobre `--superficie-2`, trilho concluído do stepper |
| `--navy` | `#262c36` (= `--grafite`) | Acento: faixa da logo, CTA, seleção, stripe |
| `--navy-profundo` | `#1b2029` (= `--grafite-profundo`) | Gradiente do CTA/faixa, texto máximo |

A escadinha prata do v1 vira, literalmente, as superfícies do claro — a paleta não muda de família,
muda de papel. Regra de profundidade v2: **card = branco + sombra; dentro de card = `--superficie-2`;
hover = +1 camada de superfície.** Nunca card cinza sobre fundo cinza sem sombra.

### 1.2 Bordas

| Token | Valor | Uso |
|---|---|---|
| `--borda-sutil` | `rgba(27, 32, 41, 0.08)` | Divisores internos, contorno de card (sempre junto de `--sombra-1`) |
| `--borda` | `#d3d8df` | Borda de input em repouso, divisores fortes, contorno do botão secundário |
| `--borda-ativa` | `#4a5464` | Borda de input focado, card/slot selecionado |

### 1.3 Texto (3 níveis) + contraste WCAG AA verificado

| Token | Valor | Papel | Contraste s/ `--fundo` `#f5f6f8` | s/ `--superficie` `#fff` |
|---|---|---|---|---|
| `--tinta` | `#1b2029` | Primário: títulos, nomes, preços | **14,9:1** ✅ | **16,2:1** ✅ |
| `--tinta-suave` | `#4a5464` | Secundário: datas, "com Fulano", labels | **7,1:1** ✅ | **7,7:1** ✅ |
| `--tinta-fraca` | `#6b7686` | Terciário/legenda | **4,3:1** ⚠️ | **4,6:1** ✅ |

**Regra do `--tinta-fraca`** (herda a regra do `--cinza` v1): sobre `--fundo` fica logo abaixo de
4,5:1 → usar somente em texto ≥ 18 px, ou ≥ 14 px peso ≥ 600, ou decorativo/uppercase; **sobre
branco (`--superficie`) passa AA** e pode ser usado em legenda normal. Legenda essencial continua
em `--tinta-suave`.

Texto sobre navy (faixa/CTA/seleção): sempre `--prata` `#eceef1` — **13,0:1** ✅ (par do v1, intacto).

### 1.4 Acento navy + CTA metálico reinterpretado

| Token | Valor | Contraste | Uso |
|---|---|---|---|
| `--navy` | `#262c36` | texto `--prata` = 13,0:1 ✅ | Fundo de botão sólido, dia/slot selecionado |
| `--navy-hover` | `#323a46` (= `--aco`) | 11,1:1 ✅ | Hover do botão sólido (clareia — botão escuro clareia no hover) |

**`.cta-agendar` v2 — "a placa em bloco":** deixa de ser prata e vira o navy da fachada com o
brilho cromado por cima. Mesma anatomia/keyframes; só valores mudam:

```css
.cta-agendar {
  background: linear-gradient(180deg, #3e4754 0%, #262c36 55%, #1b2029 100%);
  color: var(--prata);
  box-shadow:
    0 10px 30px rgba(27, 32, 41, 0.35),
    inset 0 1px 0 rgba(255, 255, 255, 0.22);   /* fio cromado superior */
}
/* facho (::after): rgba(255,255,255,0.7) → rgba(236,238,241,0.45) — cromo, não flash */
/* cta-glow: última camada do 50% vira 0 0 26px 2px rgba(38,44,54,0.35) (halo navy) */
```
Timings congelados do v1 mantidos (180 ms / 3,2 s / 3,6 s). Continua **máximo 1 por tela** e
continua sendo o único elemento com pulso permanente.

### 1.5 Estados funcionais (pares claro)

As cores v1 (`#4ade80`/`#f87171`/`#fbbf24`) foram calibradas para fundo escuro e **falham sobre
claro** (verde 1,7:1). A v2 adiciona os pares-tinta e mantém os v1 só para uso sobre navy:

| Token | Valor | Contraste s/ `--superficie` | s/ fundo do badge | Uso |
|---|---|---|---|---|
| `--verde-tinta` | `#166534` | 7,1:1 ✅ | 6,4:1 s/ `#dcfce7` ✅ | Texto/ícone sucesso, WhatsApp |
| `--vermelho-tinta` | `#b91c1c` | 6,5:1 ✅ | 5,3:1 s/ `#fee2e2` ✅ | Texto erro, "Cancelar" |
| `--ambar-tinta` | `#854d0e` | 6,9:1 ✅ | 6,2:1 s/ `#fef3c7` ✅ | Texto aviso |
| `--verde-fundo` | `#dcfce7` | — | — | Fundo de badge "Agendado" |
| `--vermelho-fundo` | `#fee2e2` | — | — | Fundo de badge "Cancelado" |
| `--ambar-fundo` | `#fef3c7` | — | — | Fundo de badge "Não compareceu" |

Badge: fundo sólido do par (não mais `cor/15` — opacidade sobre claro lava a cor).

### 1.6 Sombras (frias, tintadas de navy)

| Nível | Token | Valor v2 |
|---|---|---|
| 1 | `--sombra-1` | `0 1px 3px rgba(27,32,41,0.08), 0 4px 12px rgba(27,32,41,0.06)` |
| 2 | `--sombra-2` | `0 8px 24px rgba(27,32,41,0.12)` |
| 3 | `--sombra-3` | `0 16px 48px rgba(27,32,41,0.18)` |
| CTA | *(no seletor)* | §1.4 |

Todo card branco carrega `--sombra-1` + `border: 1px solid var(--borda-sutil)` (no claro, sombra
sem fio de borda parece manchada; fio sem sombra parece wireframe — sempre os dois).

### 1.7 Tipografia, espaçamento, raios, movimento — herdados

Integralmente iguais ao v1 (§1.7–1.9, §1.11 do v1): Tenor Sans display 400 (sem faux-bold) +
Quicksand 400–700; escala de 9 papéis; `tnum`; escala de 4 px; raios 8/12/16/pílula; durações
150/240/400 ms e easings `cubic-bezier(0.2,0,0,1)` / `(0,0,0.2,1)`. Únicas mudanças:

- `:focus-visible` → `outline: 2px solid var(--navy)` (offset 2 mantido); sobre navy (CTA,
  seleção) o offset de 2 px sobre fundo claro já dá o anel — nada extra.
- `.stripe` (assinatura) recolore, mesma geometria:
  `repeating-linear-gradient(-45deg, var(--navy) 0 10px, var(--fundo) 10px 14px, #8792a1 14px 24px, var(--fundo) 24px 28px)`.
  Orçamento ritual do v1 §3.6 mantido (topo do body, divisores da home, passo ativo — ≤ 3/tela).

### 1.8 `html` e viewport

```css
html { background: var(--fundo); color: var(--tinta); }
```
`viewport.themeColor` **permanece `#262c36`**: a status bar funde com a faixa navy da logo (§4.1) —
o topo do app continua sendo a fachada. `appleWebApp.statusBarStyle` sai de `black-translucent`
para `default`? **Não** — manter `black-translucent`; a faixa navy fica atrás da status bar.

### 1.9 Tabela de migração mecânica (v1 → v2)

Tokens novos no `@theme inline`: `--color-fundo`, `--color-superficie`, `--color-superficie-2`,
`--color-superficie-3`, `--color-navy`, `--color-navy-hover`, `--color-tinta`, `--color-tinta-suave`,
`--color-tinta-fraca`, `--color-verde-tinta`, `--color-vermelho-tinta`, `--color-ambar-tinta`,
`--color-verde-fundo`, `--color-vermelho-fundo`, `--color-ambar-fundo`.

Busca-e-troca nos componentes (`components/ui/*`, `components/booking/*`, páginas):

| Classe v1 | Classe v2 | Contexto |
|---|---|---|
| `bg-grafite` (página) | *(nada — html já é `--fundo`)* | |
| `bg-grafite/85` | `bg-superficie/85` | sticky-cta |
| `bg-grafite-profundo` | `bg-superficie` | toast, skeleton base → `bg-superficie-2` no skeleton |
| `bg-aco` | `bg-superficie` + `--sombra-1` + `border-borda-sutil` | cards, inputs |
| `bg-aco` (chips de contato, avatar-fundo) | `bg-superficie-2` | elementos dentro de card/rodapé |
| `hover:bg-aco-claro` | `hover:bg-superficie-2` | cards interativos |
| `bg-aco-claro` (inset: avatar, trilho futuro, badge concluído) | `bg-superficie-2` | |
| `hover:bg-aco` (outline button) | `hover:bg-superficie-2` | |
| `text-prata` | `text-tinta` | texto primário |
| `text-prata-suave` | `text-tinta-suave` | secundário |
| `text-cinza` | `text-tinta-fraca` | terciário (regra §1.3) |
| `text-destaque` (preços) | `text-tinta` (preço é `font-display` — a fonte já destaca) | |
| `text-destaque` (avatar inicial) | `text-tinta-suave` | |
| `bg-destaque text-grafite` (seleção/botão sólido) | `bg-navy text-prata` | dia/slot selecionado, SolidButton |
| `hover:bg-destaque-escuro` | `hover:bg-navy-hover` | SolidButton |
| `hover:bg-destaque hover:text-grafite` (slot) | `hover:bg-navy hover:text-prata` | |
| `bg-verde/15 text-verde` | `bg-verde-fundo text-verde-tinta` | badge Agendado |
| `bg-vermelho/15 text-vermelho` | `bg-vermelho-fundo text-vermelho-tinta` | badge Cancelado |
| `bg-ambar/15 text-ambar` | `bg-ambar-fundo text-ambar-tinta` | badge Não compareceu |
| `text-verde` / `text-vermelho` / `text-ambar` (avulsos) | `text-verde-tinta` / `text-vermelho-tinta` / `text-ambar-tinta` | links WhatsApp, erros inline, Cancelar |
| `border-borda` / `border-borda-ativa` / `border-borda-sutil` | *(mesmos nomes — valores mudam no `:root`)* | |
| `border-grafite/30 border-t-grafite` (Spinner sobre prata) | `border-prata/30 border-t-prata` (spinner agora vive sobre navy) | |

---

## 2. Releitura dos 12 componentes (só deltas — anatomia e estados = v1 §2)

1. **Botão primário `.cta-agendar`** — vira bloco navy metálico (§1.4). Nível 2 `SolidButton`/
   `SolidLink` (`ui/buttons.tsx`): `bg-navy text-prata hover:bg-navy-hover`; resto intacto.
   `Spinner`: anel `border-prata/30 border-t-prata`.
2. **Secundário / fantasma** — `OutlineButton`: `border-borda text-tinta hover:border-borda-ativa
   hover:bg-superficie-2`. `GhostLink`: `text-tinta-suave hover:text-tinta`. Destrutivo-fantasma:
   `text-vermelho-tinta`.
3. **Card de serviço** (`ui/service-row.tsx`, passo 1) — `bg-superficie border border-borda-sutil`
   + `--sombra-1`, hover `bg-superficie-2`; nome `text-tinta`, duração `text-tinta-fraca` (ok:
   decorativa), preço `font-display text-lg text-tinta tnum`. Na home: linhas com
   `divide-borda-sutil`, sem caixa (mantido).
4. **Card/avatar de profissional** (`ui/professional.tsx`) — card como §2.3; avatar
   `bg-superficie-2`, inicial `font-display text-tinta-suave`; foto real ganha
   `border-borda-sutil`.
5. **Strip de dias** — default `bg-superficie border-borda-sutil text-tinta-suave`, hover
   `bg-superficie-2`; **selecionado `bg-navy text-prata` + `--sombra-1`**; ponto "hoje"
   `bg-navy`; sem-horários `opacity-50`. Snap e medidas do v1 intactos.
6. **Grid de slots** — livre `bg-superficie border-borda-sutil text-tinta`; hover/selecionado
   `bg-navy text-prata`; indisponível `bg-transparent text-tinta-fraca/60 line-through
   border-borda`. Colunas/alvos do v1.
7. **Stepper** (`booking/step-header.tsx`) — ativo: `.stripe` v2 (recolorida, §1.7); concluído
   `bg-superficie-3`… **não**: concluído precisa ler mais que o futuro → concluído `bg-navy/60`,
   futuro `bg-superficie-3`. Labels: ativo `text-tinta`, concluído `text-tinta-suave`, futuro
   `text-tinta-fraca`.
8. **Campos de formulário** — `bg-superficie border-borda text-tinta placeholder:text-tinta-fraca`
   (placeholder sobre branco = 4,6:1 ✅); focus `border-borda-ativa`; erro `border-vermelho-tinta`
   + mensagem `text-vermelho-tinta`. Fonte ≥ 16 px mantida.
9. **Card de agendamento** (`ui/appointment-summary.tsx`) — `bg-superficie border-borda-sutil` +
   `--sombra-1`; divisor `border-borda-sutil`; preço `text-tinta`; badges §1.5
   (`ui/status-badge.tsx` troca o mapa `STYLES` pelos pares fundo/tinta).
10. **Toast** (`ui/toast.tsx`) — `bg-superficie border-borda` + `--sombra-2`; texto `text-tinta`;
    barra de acento `--verde-tinta`/`--vermelho-tinta`; ação `text-navy underline`; fechar
    `text-tinta-fraca hover:text-tinta`. Posição/roles/durações do v1.
11. **Empty states** (`ui/empty-state.tsx`) — `bg-superficie border-borda-sutil` + `--sombra-1`,
    frase `text-tinta-suave`, ação `SolidButton` navy. Textos canônicos inalterados.
12. **Skeleton** — base `bg-superficie-2`, shimmer `rgba(255,255,255,0.6)` varrendo 1,2 s;
    delay 150 ms / mínimo 300 ms / `aria-busy` / reduced-motion como no v1.

`ConfirmSheet` (`ui/confirm-sheet.tsx`): painel `bg-superficie rounded-2xl` + `--sombra-3`;
backdrop `rgba(27,32,41,0.45)`.

---

## 3. Hero novo (sem vídeo) — "A placa sobre a vitrine"

Estrutura da home, de cima para baixo (substitui `hero-cinematic.tsx` por um componente server
`hero-plate.tsx` — sem JS de scroll; `sticky-cta` continua observando a sentinela `#fim-do-hero`):

```
┌──────────────────────────────────────┐
│ .stripe (4px, v2)                    │ ← borda da placa (topo do body, mantida)
│ ╔══════════ FAIXA NAVY ═══════════╗ │
│ ║        [logo-lockup.webp]        ║ │ ← a fachada, intocada
│ ║      BARBEARIA · PALMAS/TO       ║ │
│ ╚══════════════════════════════════╝ │
│                                      │ ← fundo claro começa aqui
│   Renove seu estilo.                 │ ← headline Tenor Sans
│   Corte e barba com hora marcada,    │
│   sem espera.                        │
│   [   Agendar horário  → ]           │ ← .cta-agendar v2 (navy metálico)
│   Ver meus agendamentos              │
│   [ foto aérea — cartão 16/9 ]       │ ← hero-poster.jpg tratado (opcional)
│ ── #fim-do-hero (sentinela) ──       │
│   .stripe + Serviços …               │
└──────────────────────────────────────┘
```

### 3.1 Faixa navy (a assinatura da fachada)

- Full-bleed (100vw), `background: linear-gradient(180deg, var(--navy-profundo) 0%, var(--navy) 100%)`;
  padding `pt-[calc(env(safe-area-inset-top)+2rem)] pb-8 px-6`; conteúdo centrado, `max-w-md mx-auto`.
- Logo: `logo-lockup.webp` (ou `public_info.logo_url`) a `min(64vw, 260px)` de largura,
  `drop-shadow(0 4px 16px rgba(0,0,0,0.5))`; clearspace e proporção do v1 §3.3 valem na íntegra.
- Eyebrow sob a logo (`mt-3`): "Barbearia · Palmas/TO", 12 px `uppercase tracking-[0.28em]
  text-prata-suave`.
- Base da faixa: borda inferior `1px solid rgba(236,238,241,0.12)` (fio cromado) — **sem** stripe
  aqui (a stripe do topo do body já é a borda da placa).
- A faixa é o **único** navy de área grande do site. Altura natural do conteúdo (~200–230 px);
  nunca `100svh`.

### 3.2 Bloco de abertura claro

- `pt-10 px-6`, `max-w-md mx-auto`, alinhado à esquerda (quebra o centrado da faixa — cara de app,
  não de cartão de visita).
- Headline: **"Renove seu estilo."** (o slogan da fachada promovido a headline — Tenor Sans,
  30 px/1.15, `text-tinta`). Ponto final incluso.
- Sub: "Corte e barba com hora marcada, sem espera." — 16 px/1.55 `text-tinta-suave`, `mt-2`,
  `max-w-[32ch]`.
- CTA: `.cta-agendar` v2 full-width `max-w-md`, `mt-6` — pílula, `px-6 py-4`, 18 px/700, seta
  (anatomia v1 intacta, filhos `relative z-10`).
- Sob o CTA (`mt-3`): `GhostLink` "Ver meus agendamentos", centrado.

### 3.3 Foto aérea (opcional, recomendada)

`hero-poster.jpg` deixa de ser poster e vira **cartão-postal** de prova de lugar:
- `mt-8`, `rounded-2xl overflow-hidden`, `aspect-[16/9] object-cover`, `--sombra-1` +
  `border-borda-sutil`.
- Tratamento (v1 §3.4 adaptado ao claro): overlay `color-mix(in srgb, var(--navy) 12%, transparent)`
  + `filter: saturate(0.85)` — assenta a foto na paleta sem escurecê-la.
- Sem texto sobre a foto (texto sobre mídia exigia o véu escuro do v1 — no claro, não sobrepor).
- `loading="lazy"`, `alt="Vista aérea da Taylor & Thedy"`. Se o dono dispensar a foto, o bloco sai
  sem rearranjo (é o último filho antes da sentinela).

### 3.4 `sticky-cta` no claro

`components/sticky-cta.tsx` — mesmas mecânica/sentinela/acessibilidade; só o tratamento muda:
- Contêiner: `border-t border-borda bg-superficie/85 backdrop-blur` + `--sombra-2` (a sombra
  agora projeta para cima — trocar por `0 -8px 24px rgba(27,32,41,0.12)`).
- Botão: `SolidButton` navy (`bg-navy text-prata hover:bg-navy-hover`) — **sem** glow/facho
  (exclusivos do hero, regra mantida).
- Link "Meus agendamentos": `text-tinta-suave hover:text-tinta`.
- Safe-area `env(safe-area-inset-bottom)` mantida.

### 3.5 Rodapé no claro

- Abre com `.stripe` v2 (2º e último uso em divisor na home).
- Fundo: `--superficie-2` full-bleed, `py-10 px-6` (o rodapé é o único bloco de área em
  `superficie-2` — fecha a página com meio-tom, ecoando a faixa do topo sem repetir navy).
- Endereço 14 px `text-tinta-suave`; chips de contato: `bg-superficie border-borda-sutil` +
  `--sombra-1`, `rounded-lg px-4 py-2`; WhatsApp `text-verde-tinta`, demais `text-tinta`.
- Última linha: `LogoMark` ("T" vetorial) 28 px `fill: var(--tinta-fraca)` + "Taylor & Thedy" 12 px
  `text-tinta-fraca` — único uso da marca sobre claro, e é o monograma, nunca o lockup cromado.

### 3.6 Hierarquia da home (v1 §3.2, revisada)

1. Faixa navy (logo) → 2. Abertura clara (headline + CTA) → 3. Foto aérea (opcional) →
4. `.stripe` + Serviços (`pt-12`) → 5. Quem atende → 6. Horários → 7. Rodapé (§3.5).
Grid, gutters, `max-w-md`, safe-areas: idênticos ao v1 §3.1/§3.5.

---

## 4. Movimento

Vocabulário do v1 §4 herdado por inteiro (150/240 ms, o que anima/não anima, reduced-motion).
Deltas: o scrub de vídeo **sai** (apagar `hero-cinematic.tsx` e os assets `hero-drone.mp4` quando o
dono confirmar); nenhuma animação nova entra no hero — a faixa navy e a headline aparecem estáticas
(`.anim-entrar` opcional na primeira pintura do bloco claro, 240 ms, uma vez). O único pulso
permanente segue sendo o glow do `.cta-agendar` (agora halo navy, §1.4).

---

## 5. Checklist de conformidade v2 (soma-se ao do v1)

- [ ] Nenhum `bg-grafite`/`bg-aco*`/`text-prata*` remanescente fora de faixa navy, CTA, seleção e spinner.
- [ ] Logo cromada **nunca** sobre fundo claro; sobre claro, só `LogoMark` recolorido.
- [ ] Verde/vermelho/âmbar v1 nunca como **texto** sobre claro — sempre os pares `-tinta`.
- [ ] Todo card branco tem sombra **e** fio `--borda-sutil`.
- [ ] Navy como fundo apenas em: faixa da logo, CTA, seleção, stripe, badges? não — badges usam pares §1.5.
- [ ] `themeColor #262c36` mantido; status bar funde com a faixa.
- [ ] Contrastes §1.3/§1.5 conferidos após qualquer ajuste de hex.
