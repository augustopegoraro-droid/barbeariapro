# UI_SPEC — Site Público Taylor & Thedy (`barbearia-public/`)

> **Papel deste documento:** fonte de verdade visual para o Front-end implementar **sem interpretação**.
> Sistematiza e estende a identidade já **aprovada e deployada** (D-79/D-80): grafite da placa da
> fachada + prata cromada, hero cinematográfico com vídeo de drone, CTA `.cta-agendar` metálico.
> **Nada aqui substitui o que está em produção — evolui a partir dele.** Tokens existentes em
> `app/globals.css` mantêm nome e valor; os novos são aditivos.
>
> Conceito da identidade: **"a placa da fachada"** — tudo no site é uma extensão da placa navy-grafite
> com letras cromadas 3D. Fundos = a chapa. Texto e acentos = o metal. A única cor viva é funcional
> (verde WhatsApp/sucesso, vermelho erro, âmbar aviso). A **listra `.stripe`** (prata escovada
> diagonal) é a assinatura — usada com parcimônia ritual (regras em §3.6).

---

## 1. Design tokens

Todos os tokens vivem em `:root` de `app/globals.css` e são expostos ao Tailwind v4 via `@theme inline`
(padrão já usado no projeto: `--color-grafite: var(--grafite)` → classe `bg-grafite` etc.).

### 1.1 Paleta — fundos em camadas (grafite)

| Token | Valor | oklch (ref.) | Uso |
|---|---|---|---|
| `--grafite-profundo` **(novo)** | `#1b2029` | `oklch(0.235 0.02 262)` | Camada 0: fundo do rodapé, base de skeleton, véu final do hero, fundo atrás de modais |
| `--grafite` *(existente)* | `#262c36` | `oklch(0.29 0.021 262)` | Camada 1: fundo da página (`html`) — **não alterar** |
| `--aco` *(existente)* | `#323a46` | `oklch(0.345 0.023 258)` | Camada 2: superfícies (cards, inputs, chips) |
| `--aco-claro` *(existente)* | `#3e4754` | `oklch(0.40 0.024 257)` | Camada 3: hover de superfície, avatar, trilho inativo do stepper |
| `--aco-brilho` **(novo)** | `#4a5464` | `oklch(0.455 0.026 256)` | Camada 4: hover sobre `--aco-claro`, borda de foco de card, shimmer do skeleton |

Regra de profundidade: **cada nível de aninhamento sobe exatamente 1 camada.** Card sobre página =
`--aco`; elemento dentro de card = `--aco-claro`; hover = +1 camada. Nunca pular camadas.

### 1.2 Paleta — bordas

| Token | Valor | Uso |
|---|---|---|
| `--borda-sutil` **(novo)** | `rgba(236, 238, 241, 0.08)` | Divisores internos, contorno opcional de card sobre grafite |
| `--borda` **(novo)** | `#4a5464` (= `--aco-brilho`) | Borda de input em repouso (hoje `border-aco-claro` — migrar para este token), divisores fortes |
| `--borda-ativa` **(novo)** | `#b4bcc8` (= `--prata-suave`) | Borda de input focado, card/slot selecionado |

### 1.3 Paleta — texto (3 níveis) + contraste WCAG AA verificado

| Token | Valor | Papel | Contraste s/ `--grafite` `#262c36` | s/ `--aco` `#323a46` |
|---|---|---|---|---|
| `--prata` *(existente)* | `#eceef1` | Texto primário, títulos, valores | **13,0:1** ✅ AA/AAA | **11,1:1** ✅ |
| `--prata-suave` *(existente)* | `#b4bcc8` | Texto secundário (datas, "com Fulano") | **7,5:1** ✅ AA/AAA | **6,4:1** ✅ |
| `--cinza` *(existente)* | `#8792a1` | Terciário/legenda | **4,4:1** ⚠️ | **3,8:1** ⚠️ |

**Regra obrigatória do `--cinza`:** contraste fica logo abaixo de 4,5:1 → usar **somente** em texto
≥ 18 px, ou ≥ 14 px com peso ≥ 600, ou em texto decorativo/uppercase de apoio ("Role para ver",
labels do stepper inativo). **Legenda essencial** (ex.: "Usamos seu número para confirmar…", regra de
cancelamento) migra de `text-cinza` para `text-prata-suave`. `--cinza` nunca em texto sobre `--aco-claro`.

### 1.4 Paleta — acento prata/cromado

| Token | Valor | Contraste | Uso |
|---|---|---|---|
| `--destaque` *(existente)* | `#dfe3e9` | 11,4:1 s/ grafite ✅ | Acento principal: preços, botão sólido, dia/slot selecionado |
| `--destaque-escuro` *(existente)* | `#c3cad4` | 8,9:1 ✅ | Hover do botão sólido, base do gradiente do CTA |
| Texto sobre `--destaque` | `var(--grafite)` `#262c36` | **11,4:1** ✅ | Par obrigatório — nunca texto claro sobre destaque |

Gradiente metálico do CTA (`.cta-agendar`) — **congelado, não alterar**:
`linear-gradient(180deg, #ffffff 0%, var(--prata) 20%, var(--destaque) 58%, var(--destaque-escuro) 100%)`, texto `var(--grafite)`.

### 1.5 Paleta — estados funcionais

| Token | Valor | Contraste s/ grafite | Uso |
|---|---|---|---|
| `--verde` *(existente)* | `#4ade80` | 8,0:1 ✅ | Sucesso, WhatsApp, status "Agendado" confirmado |
| `--vermelho` *(existente)* | `#f87171` | 5,1:1 ✅ | Erro, cancelamento, status "Cancelado" |
| `--ambar` **(novo)** | `#fbbf24` | 8,4:1 ✅ | Aviso (janela de cancelamento acabando, slot quase cheio) |

Fundos de badge de estado (padrão já usado em `/meus-agendamentos`): cor a **15%** de opacidade
(`bg-verde/15 text-verde`, `bg-vermelho/15 text-vermelho`, `bg-ambar/15 text-ambar`), texto ≥ 12 px peso 500.

### 1.6 `@theme inline` — bloco pronto (aditivo ao existente)

```css
:root {
  /* …tokens existentes inalterados… */
  --grafite-profundo: #1b2029;
  --aco-brilho: #4a5464;
  --ambar: #fbbf24;
  --borda-sutil: rgba(236, 238, 241, 0.08);
  --borda: #4a5464;
  --borda-ativa: #b4bcc8;
  --radius-sm: 0.5rem;   /* inputs, slots, chips */
  --radius: 0.75rem;      /* existente — cards, botões grandes */
  --radius-lg: 1rem;      /* modais/sheets */
  --sombra-1: 0 2px 8px rgba(0, 0, 0, 0.25);
  --sombra-2: 0 8px 24px rgba(0, 0, 0, 0.4);
  --sombra-3: 0 16px 48px rgba(0, 0, 0, 0.55);
  --dur-rapida: 150ms;
  --dur-media: 240ms;
  --dur-lenta: 400ms;
  --ease-padrao: cubic-bezier(0.2, 0, 0, 1);
  --ease-saida: cubic-bezier(0, 0, 0.2, 1);
}

@theme inline {
  /* …mapeamentos existentes inalterados… */
  --color-grafite-profundo: var(--grafite-profundo);
  --color-aco-brilho: var(--aco-brilho);
  --color-ambar: var(--ambar);
}
```

### 1.7 Tipografia

Famílias **já carregadas** em `app/layout.tsx` — não adicionar novas:
- **Display:** `Tenor Sans` (`--font-tenor`), peso único **400**. Fallback `Georgia, serif`. É a voz da
  placa — usar em títulos, preços e números de dia. **Nunca** em parágrafo corrido nem abaixo de 16 px.
- **Corpo/UI:** `Quicksand` (`--font-quicksand`), pesos 400/500/600/700. Fallback `system-ui, sans-serif`.

Escala (mobile-first; base 16 px):

| Papel | Família | Tamanho / line-height | Peso | Tracking | Uso |
|---|---|---|---|---|---|
| `display-xl` | Tenor Sans | 30 px / 1.15 (`text-3xl`) | 400 + `font-semibold`* | 0 | "Horário marcado!", tela de erro da home |
| `display` | Tenor Sans | 24 px / 1.25 (`text-2xl`) | 400* | 0 | H1 de cada passo/página ("O que vai fazer hoje?") |
| `titulo` | Tenor Sans | 20 px / 1.3 (`text-xl`) | 400 | 0 | Preço em destaque no card de resumo |
| `preco` | Tenor Sans | 18 px / 1.3 (`text-lg`) + `tnum` | 400 | 0 | Preços em listas, número do dia no strip |
| `corpo` | Quicksand | 16 px / 1.55 | 400 (500 p/ nomes) | 0 | Texto padrão, nome de serviço/profissional |
| `corpo-sm` | Quicksand | 14 px / 1.5 | 400–500 | 0 | Secundário: duração, data, links "Voltar" |
| `legenda` | Quicksand | 12 px / 1.4 | 500 | 0 | Badges, notas de rodapé (cor: `--prata-suave`, ver §1.3) |
| `micro-caps` | Quicksand | 11 px / 1.2 | 500 | `0.08em`, uppercase | Dia da semana no strip, "Manhã/Tarde/Noite" |
| `eyebrow` | Quicksand | 14 px / 1.2 | 400 | `0.28em`, uppercase | "Barbearia · Palmas/TO" (só no hero) |

\* Tenor Sans só existe em 400 — o `font-semibold` atual no display é faux-bold do browser. **Padronizar:
remover `font-semibold` dos títulos `font-display`** (o traço flareado do Tenor já carrega presença;
faux-bold suja o desenho). A hierarquia vem do tamanho, não do peso.

Números **sempre** com `.tnum` (tabular) em horários, preços, dias e telefones.

### 1.8 Espaçamento

Escala de 4 px (padrão Tailwind). Valores canônicos do site:

| Token | Valor | Uso |
|---|---|---|
| `space-1` | 4 px | Gap entre label do stepper e trilho |
| `space-2` | 8 px | Gap entre chips/slots/dias, `space-y-2` entre cards de lista |
| `space-3` | 12 px | Gap interno ícone↔texto, `space-y-3` entre cards de agendamento |
| `space-4` | 16 px | Padding horizontal de card (`px-4`), gap entre campos de form |
| `space-5` | 20 px | Padding de card de resumo (`p-5`) |
| `space-6` | 24 px | Margem lateral da página (`px-6`), `mt-6` blocos |
| `space-10` | 40 px | Entre seções da home (`mt-10`) |
| `space-12` | 48 px | Respiro após o hero (`pt-12`) |
| `space-16` | 64 px | `pb-16` no fim de toda página |

Altura mínima de **qualquer alvo de toque: 44 px** (slots, dias, botões, links de ação).

### 1.9 Raios

| Token | Valor | Uso |
|---|---|---|
| `--radius-sm` | 8 px (`rounded-lg`) | Inputs, slots de horário, chips de contato |
| `--radius` | 12 px (`rounded-xl`) | Cards, botões grandes, dias do strip |
| `--radius-lg` | 16 px (`rounded-2xl`) | Sheets/modais, toast |
| `rounded-full` | pílula | CTA principal, badges de status, avatares, trilho do stepper |

### 1.10 Sombras / elevação

Sobre fundo escuro, elevação = sombra **+ subida de camada de fundo** (§1.1). Sombra sozinha não basta.

| Nível | Token | Valor | Uso |
|---|---|---|---|
| 0 | — | nenhuma | Cards de lista em repouso (profundidade via `bg-aco`) |
| 1 | `--sombra-1` | `0 2px 8px rgba(0,0,0,0.25)` | Card de resumo, dia selecionado |
| 2 | `--sombra-2` | `0 8px 24px rgba(0,0,0,0.4)` | Toast, install banner, barra fixa |
| 3 | `--sombra-3` | `0 16px 48px rgba(0,0,0,0.55)` | Modal/sheet de confirmação |
| CTA | *(congelada)* | `0 10px 30px rgba(0,0,0,0.45) + inset 0 1px 0 rgba(255,255,255,0.8)` + glow animado | Exclusiva do `.cta-agendar` |

### 1.11 Transições

| Token | Valor | Uso |
|---|---|---|
| `--dur-rapida` | 150 ms | Hover/active de cor e fundo (padrão de quase tudo) |
| `180 ms` *(congelado)* | ease | Transform/filter do `.cta-agendar` — não alterar |
| `--dur-media` | 240 ms | Entrada de passo do fluxo, toast, badge |
| `--dur-lenta` | 400 ms | Só o shimmer de skeleton e fades de mídia |
| `--ease-padrao` | `cubic-bezier(0.2, 0, 0, 1)` | Padrão para tudo que entra/muda |
| `--ease-saida` | `cubic-bezier(0, 0, 0.2, 1)` | Elementos saindo de cena |

---

## 2. Componentes

Estados obrigatórios em todo componente interativo: `default / hover / active / focus-visible /
disabled / loading`. Foco visível global já existe e **vale para todos**:
`outline: 2px solid var(--prata); outline-offset: 2px` — nunca `outline: none` sem substituto.
Disabled global: `opacity: 0.6; pointer-events: none` (padrão atual `disabled:opacity-60` mantido).

### 2.1 Botão primário — `.cta-agendar` (hero) e variante sólida (fluxo)

**Nível 1 — `.cta-agendar` (congelado, só no hero e destinos de conversão máxima):** classe existente
em `globals.css`. Gradiente metálico + glow pulsante 3,2 s + facho de luz 3,6 s. Anatomia: pílula
(`rounded-full`), `px-6 py-4`, texto 18 px peso 700 `tracking-wide`, seta 20 px que desliza +4 px no
hover. **Máximo 1 por tela.** Filhos de texto/ícone precisam de `relative z-10` (o facho `::after` fica em z 1).

**Nível 2 — botão sólido prata (ações de commit do fluxo: "Confirmar agendamento", "Agendar horário"
em empty states):** evolução do padrão já usado no `booking-flow.tsx`, agora nomeado `.btn-solido`:

| Estado | Especificação |
|---|---|
| Default | `bg-destaque text-grafite`, `rounded-xl`, `px-6 py-4` (full-width no fluxo) ou `px-6 py-3` (inline), 16–18 px peso 600 |
| Hover | `bg-destaque-escuro` (transição 150 ms) |
| Active | `transform: scale(0.985)` |
| Focus | outline global |
| Disabled | `opacity-60`, sem hover |
| Loading | Texto vira gerúndio da ação ("Agendando…", "Cancelando…") + spinner 16 px (anel `border-2 border-grafite/30 border-t-grafite`, rotação 800 ms linear) à esquerda; largura do botão **não muda** (reservar `min-w` do texto mais longo) |

**Sem glow nem facho no nível 2** — o brilho animado é exclusivo do `.cta-agendar`.

### 2.2 Botão secundário / fantasma

| Variante | Anatomia | Estados |
|---|---|---|
| **Secundário (contorno)** — ações alternativas visíveis ("Ver meus agendamentos" pós-confirmação) | `rounded-xl px-6 py-3`, `border border-borda text-prata bg-transparent`, 16 px peso 500 | hover: `bg-aco border-borda-ativa`; active: `scale(0.985)`; disabled: `opacity-60` |
| **Fantasma (link)** — "← Voltar", "não é você?", "Voltar ao início" | Sem caixa; `text-cinza` (≥14 px, ver §1.3) `underline underline-offset-4` quando for ação, seta quando for navegação | hover: `text-prata-suave` 150 ms |
| **Destrutivo-fantasma** — "Cancelar" agendamento | `text-vermelho underline underline-offset-4`, 14 px | hover: `text-vermelho` + `opacity-80`; loading: "Cancelando…" + `opacity-60` |

Cancelamento destrutivo exige **confirmação** (§2.10, toast/sheet) — nunca cancela em 1 toque.

### 2.3 Card de serviço

Botão de largura total (passo 1) ou linha de lista (home).

Anatomia (passo 1 — interativo):
```
┌─────────────────────────────────────────────┐
│ Corte masculino                    R$ 45,00 │  ← nome: corpo 16px peso 500, prata
│ 30 min                                      │  ← duração: corpo-sm 14px, cinza→prata-suave se <18px? usar cinza ok (decorativo curto) 
└─────────────────────────────────────────────┘
```
- Container: `rounded-xl bg-aco px-4 py-4`, layout `flex items-baseline justify-between gap-4`, alvo ≥ 56 px.
- Nome: 16 px peso 500 `text-prata`. Duração: 14 px `text-cinza` (informação redundante/apoio — permitido).
- Preço: `font-display text-lg text-destaque tnum`, alinhado à baseline do nome.
- Hover: `bg-aco-claro` 150 ms. Active: `bg-aco-claro` + `scale(0.99)`. Focus: outline global.
- Selecionado (quando exibido como resumo): borda esquerda de 3 px `var(--destaque)` **ou** o card de resumo (§2.9) — nunca os dois.
- Na home (não interativo): sem caixa — linha `py-3` com `divide-y divide-aco-claro` (padrão atual mantido).

### 2.4 Card / avatar de profissional

- Avatar: círculo **40 px** (`h-10 w-10`, fluxo) ou **36 px** (home), `bg-aco-claro`, inicial em
  `font-display font-semibold text-destaque` 16 px. Quando houver foto real: `object-cover rounded-full`
  + `border border-borda-sutil`; fallback permanece a inicial.
- Card (passo 2): `rounded-xl bg-aco px-4 py-4 flex items-center gap-3`, nome 16 px peso 500,
  especialidade 12 px `text-cinza` (decorativa). Estados = idênticos ao card de serviço (§2.3).
- Chip (home): `rounded-xl bg-aco px-4 py-3`, não interativo.

### 2.5 Seletor de data — strip horizontal de dias

- Trilho: `overflow-x auto` sangrando até a borda da tela (`-mx-6 px-6`), `flex gap-2 pb-2`,
  `scroll-snap-type: x proximity` **(novo)**, cada dia com `scroll-snap-align: start`.
- Dia (pílula vertical): `min-w-[3.5rem]` (56 px), `rounded-xl px-2 py-2`, alvo ≥ 64 px de altura. Conteúdo:
  - dia da semana: `micro-caps` 11 px uppercase;
  - número: `font-display text-lg tnum` (18 px);
  - mês: 10 px uppercase.
- Estados:

| Estado | Especificação |
|---|---|
| Default | `bg-aco text-prata-suave` |
| Hover | `bg-aco-claro` |
| Selecionado | `bg-destaque text-grafite font-semibold` + `--sombra-1`; `aria-selected="true"` |
| Hoje (não selecionado) **(novo)** | ponto de 4 px `bg-destaque rounded-full` centrado sob o mês |
| Sem horários (após consulta) **(novo)** | `opacity-50`, permanece clicável (mostra empty do dia) |
| Focus | outline global |

- Ao selecionar, o dia rola para ficar totalmente visível (`scrollIntoView({ inline: "nearest" })` — sem `smooth` se `prefers-reduced-motion`).

### 2.6 Grid de slots de horário

- Grid: `grid-cols-4 gap-2` (mobile ≤ 400 px); `grid-cols-5` a partir de 420 px. Agrupado por
  período com header `micro-caps text-cinza` ("Manhã / Tarde / Noite").
- Slot: `rounded-lg px-2 py-2.5` (alvo 44 px), horário em `font-medium tnum` 15–16 px.

| Estado | Especificação |
|---|---|
| Livre | `bg-aco text-prata` |
| Hover | `bg-destaque text-grafite` 150 ms |
| Selecionado | `bg-destaque text-grafite font-semibold` + `--sombra-1` + `aria-pressed="true"` (persistente quando o passo 4 mostrar o grid de revisão) |
| Indisponível | `bg-transparent text-cinza/50 line-through border border-borda-sutil`, `disabled`, sem hover — **só renderizar se a API passar a devolver ocupados; hoje ela devolve apenas livres → não inventar** |
| Conflito 409 | O slot que falhou entra no estado Indisponível na volta ao passo 3 + toast de erro (§2.10) |

### 2.7 Stepper / progresso do fluxo

Padrão atual do `StepHeader` mantido e refinado — 4 segmentos iguais (`flex gap-1`, cada `flex-1`):

| Segmento | Trilho | Label (11 px) |
|---|---|---|
| Ativo | **`.stripe` `rounded-full`** (4 px — a assinatura, único uso no fluxo) | `text-prata` peso 500 |
| Concluído | `h-1 bg-destaque rounded-full` | `text-prata-suave` |
| Futuro | `h-1 bg-aco-claro rounded-full` | `text-cinza` |

- Semântica: `<ol aria-label="Etapas do agendamento">`; passo ativo com `aria-current="step"` **(novo)**.
- Labels concluídos são clicáveis para voltar (**novo, opcional v1.1**): área de toque do segmento inteiro.
- Transição de passo: conteúdo novo entra com `fade + translateY(8px→0)` 240 ms `--ease-padrao`; o
  trilho anima a largura do preenchimento em 240 ms. Sem animação de saída (troca seca do conteúdo anterior).

### 2.8 Campos de formulário (nome / telefone)

- Label: 14 px peso 500 `text-prata`, `block`, 4 px acima do campo.
- Input: `w-full rounded-lg bg-aco px-3 py-3` (alvo 48 px), texto 16 px `text-prata` (**nunca < 16 px** —
  evita zoom do iOS), `placeholder:text-cinza`, borda `1px solid var(--borda)`.
- Telefone: `inputMode="tel" autoComplete="tel-national"` + máscara `(63) 99999-9999` (já existe em
  `lib/format.ts::maskPhone`) + `.tnum`. Nome: `autoComplete="name"`.
- Texto de apoio: 12 px **`text-prata-suave`** (migração §1.3), 4 px abaixo.

| Estado | Especificação |
|---|---|
| Default | borda `--borda` |
| Focus | borda `--borda-ativa` + outline global (borda muda junto, 150 ms) |
| Erro | borda `--vermelho`, mensagem 14 px `text-vermelho` abaixo com `role="alert"`, ícone opcional 16 px |
| Disabled | `opacity-60` |
| Preenchido válido | sem decoração extra (não usar check verde — ruído) |

Mensagens de erro dizem o que fazer: "Preencha seu nome e um telefone com DDD." (padrão atual, manter tom).

### 2.9 Card de agendamento (`/meus-agendamentos` + resumo do passo 4 + confirmação)

Anatomia (um único componente, 3 contextos):
```
┌───────────────────────────────────────────────┐
│ Corte masculino               [ Agendado ]    │ ← nome 16px/500 + badge
│ sábado, 26 de julho às 09:30                  │ ← corpo-sm prata-suave, hora tnum
│ com Taylor                                    │
│ ───────────────────────────────────────────── │ ← divisor --borda-sutil (só se houver rodapé)
│ R$ 45,00                          Cancelar    │ ← preço display 18px destaque · ação vermelha
└───────────────────────────────────────────────┘
```
- Container: `rounded-xl bg-aco p-5`; no resumo do passo 4/confirmação, adicionar `--sombra-1`.
- Badge de status (pílula `rounded-full px-2.5 py-1 text-xs font-medium`):

| Status | Estilo |
|---|---|
| Agendado | `bg-verde/15 text-verde` (**mudança**: hoje usa `destaque/15` — verde comunica "confirmado" melhor que prata; prata fica para seleção) |
| Concluído | `bg-aco-claro text-prata-suave` |
| Cancelado | `bg-vermelho/15 text-vermelho` + nome do serviço com `opacity-70` |
| Não compareceu | `bg-ambar/15 text-ambar` |

- Ordenação: futuros primeiro (mais próximo no topo), depois passados. Agendamento passado inteiro com
  `opacity` normal (histórico é informação, não lixo) — só o cancelado esmaece o título.
- "Cancelar" aparece apenas se `cancelable` (regra das 2h vem da API — o front não recalcula).

### 2.10 Toast / feedback

Hoje o feedback é inline (`<p class="text-vermelho">`). Sistematizar em **toast** para ações
assíncronas (cancelamento, 409 de slot) mantendo o inline para validação de formulário:

- Posição: fixo no rodapé, `bottom: calc(env(safe-area-inset-bottom) + 16px)`, `inset-x-4`,
  `max-w-md mx-auto`, acima de qualquer barra fixa.
- Anatomia: `rounded-2xl bg-grafite-profundo border border-borda-sutil p-4 flex gap-3 items-start`
  + `--sombra-2`; barra de acento esquerda 3 px na cor do estado; ícone 20 px; texto 14 px `text-prata`;
  ação opcional ("Tentar de novo") como fantasma sublinhado.
- Cores: sucesso `--verde` · erro `--vermelho` · aviso `--ambar`.
- Movimento: entra `translateY(12px→0) + fade` 240 ms `--ease-padrao`; sai com fade 150 ms `--ease-saida`.
- Duração: sucesso 4 s auto-dismiss; erro **persiste** até ação ou dismiss manual (X 44 px de alvo).
- Acessibilidade: `role="status"` (sucesso) / `role="alert"` (erro); um toast por vez (o novo substitui).
- Voz: nome da ação ecoa o botão — "Confirmar agendamento" → "Horário marcado!"; "Cancelar" → "Agendamento cancelado."

### 2.11 Empty states

Padrão único (já iniciado em `/meus-agendamentos` — sistematizar):
- Container: `rounded-xl bg-aco p-5 text-center` (ou página inteira centrada em `min-h-[80dvh]` quando
  a tela toda está vazia).
- Estrutura: frase do estado (16 px `text-prata-suave`, 1 linha, diz o que está acontecendo) + **1 ação**
  (`.btn-solido` inline `px-6 py-3`) + ação secundária opcional como fantasma.
- Sem ilustração/emoji decorativo nos empties (o ✂️ fica exclusivo da tela de sucesso "Horário marcado!").
- Textos canônicos (manter voz atual, direta e sem culpa):
  - Sem sessão: "Você ainda não tem agendamentos neste aparelho." → **Agendar horário**
  - Lista vazia: "Nenhum agendamento por aqui ainda." → **Agendar horário**
  - Dia sem slots: "Sem horários livres neste dia. Escolha outro dia acima." (sem botão — a ação é o strip)
  - Falha de rede: "Não foi possível carregar agora." → **Tentar de novo** (fantasma)

### 2.12 Skeleton de carregamento

Substitui os textos "Carregando…"/"Buscando horários…" atuais:
- Base: `bg-grafite-profundo rounded-lg` com shimmer: gradiente
  `90deg, transparent 0%, var(--aco-brilho) 50%, transparent 100%` a 30% de opacidade varrendo em
  **1,2 s linear infinite** (`background-size: 200% 100%`).
- Formas espelham o layout real (mesmas alturas/raios do componente final — zero layout shift):
  - Lista de slots: 2 headers de 12×64 px + grid 4×3 de blocos 44 px `rounded-lg`;
  - Meus agendamentos: 2 cards de 120 px `rounded-xl`;
  - Strip de dias: nunca tem skeleton (é síncrono).
- Exibir skeleton só após **150 ms** de espera (evita flash em respostas rápidas); mínimo 300 ms visível.
- `aria-busy="true"` no container + texto `sr-only` "Carregando horários".
- Em `prefers-reduced-motion`: shimmer desligado, bloco estático em `--grafite-profundo`.

---

## 3. Regras de composição

### 3.1 Grid mobile-first

- **Coluna única, `max-w-md` (448 px), centrada** (`mx-auto`) — padrão atual, mantido em todas as
  páginas. O site é um app de bolso; em desktop ele permanece uma coluna elegante centrada sobre o
  grafite (não criar layout desktop multi-coluna na v1).
- Gutter lateral: `px-6` (24 px) fixo. Conteúdo que sangra (strip de dias): `-mx-6 px-6`.
- Rodapé de página: `pb-16` (64 px) + em barras/toasts fixos usar sempre
  `calc(env(safe-area-inset-bottom) + Xrem)` (padrão já aplicado no hero — obrigatório em qualquer fixed bottom).
- Topo: `pt-6` nas páginas internas; o hero usa `pt-16` + `100svh`/`200svh` (unidades `svh`, nunca `vh`, por causa da barra do Safari iOS).
- Breakpoint único relevante: `min-width: 420px` → slots em 5 colunas (§2.6). Nada mais muda.

### 3.2 Hierarquia da home abaixo do hero

Ordem fixa (decisão de conversão — o CTA já converteu no hero; o resto é confiança):
1. **`.stripe`** (divisor de assinatura) + **Serviços** (`pt-12`) — prova de valor com preço;
2. **Quem atende** (`mt-10`) — prova social interna;
3. **Horário de funcionamento** (`mt-10`) — utilidade;
4. **`.stripe`** + rodapé de contato (`mt-10`): endereço + chips WhatsApp (verde) / Instagram / Ligar.

Entre o fim do hero (véu escurecido a ~0,75 de `--grafite`) e a seção Serviços não há transição dura:
o véu do hero já termina em grafite — a página "continua" a placa. Não inserir novas seções entre
1 e 2 sem decisão do dono (qualquer bloco novo — avaliações, promoções — entra entre 2 e 3).

### 3.3 Uso da logo (`/public/logo-lockup.webp`)

- Arquivo: webp transparente, cromado, proporção **1000×472** (≈ 2,12:1). É a arte fiel da fachada —
  **nunca** recriar em texto/fonte (o SVG `LogoLockup` de `logo.tsx` está aposentado no site; `LogoMark`
  ["T" isolado] permanece válido para favicon/avatar/PWA).
- Tamanhos: hero `min(84vw, 340px)` (congelado). Uso mínimo em qualquer contexto: **120 px** de largura
  (abaixo disso o script "Taylor" degrada — usar `LogoMark`).
- Clearspace: margem livre em volta ≥ **altura do "T" monumental ÷ 2** (na prática: ≥ 12% da largura
  usada, nos 4 lados). Nada encosta na logo.
- **Nunca:** distorcer (width e height sempre proporcionais), recolorir, aplicar filtros além do
  `drop-shadow(0 6px 20px rgba(0,0,0,0.6))` do hero, ou pousar sobre fundo que não seja
  grafite/aço/fotografia escurecida (a logo é prata — precisa de fundo escuro; contraste mínimo do
  fundo por trás: luminância ≤ a de `--aco-claro`).
- `public_info.logo_url` (quando cadastrado no admin) tem precedência sobre o arquivo local — mesmas regras.

### 3.4 Fotografia e vídeo

- **Tratamento único:** toda mídia recebe véu grafite para sentar na placa. Receita do hero (congelada):
  `linear-gradient(to top, var(--grafite) 0%, 55% → 42%, 18% → 78%, 45% → 100%)` com opacidade base
  0,4 escalando a 0,75 no fim do scrub. Fotos estáticas futuras (perfil de barbeiro, galeria): overlay
  plano `color-mix(in srgb, var(--grafite) 25%, transparent)` + leve dessaturação (`saturate(0.85)`)
  para unificar temperaturas de câmera.
- Texto sobre mídia: sempre com `text-shadow: 0 1px 8px rgba(0,0,0,0.6)` (padrão do hero) **e**
  posicionado na zona mais escura do véu. Nunca texto essencial sobre a área clara do vídeo.
- Vídeo: mudo, `playsInline`, `poster` obrigatório, `object-cover`. O scrub por scroll é exclusivo do
  hero da home — não replicar em outras páginas.
- Peso: qualquer mídia nova segue o teto do D-80 — vídeo ≤ 3 MB, poster ≤ 120 KB, fotos ≤ 80 KB (webp).

### 3.5 Safe areas iOS / PWA

- `viewport-fit=cover` implícito pelo PWA `black-translucent`: todo elemento fixo no rodapé soma
  `env(safe-area-inset-bottom)`; headers fixos (se criados) somam `env(safe-area-inset-top)`.
- `themeColor: #262c36` (mantido) — a placa continua na status bar.

### 3.6 A listra `.stripe` (assinatura)

Orçamento ritual — **exatamente estes usos, nunca mais que 3 por tela**:
1. Filete no topo do `<body>` (layout raiz) — a borda da placa;
2. Divisores da home (abertura de Serviços e do rodapé);
3. Passo ativo do stepper no fluxo.
Proibido: stripe em botões, cards, badges, toasts ou como decoração de título.

---

## 4. Microinterações

### 4.1 Vocabulário de movimento

| O quê | Duração / easing | Detalhe |
|---|---|---|
| Hover/active de cor e fundo | 150 ms / `--ease-padrao` | `transition-colors` — o padrão de 90% do site |
| CTA hero (transform/filter/glow/facho) | 180 ms / 3,2 s / 3,6 s *(congelados)* | Não tocar |
| Troca de passo do fluxo | 240 ms / `--ease-padrao` | fade + `translateY(8px→0)` do conteúdo entrante |
| Toast entra / sai | 240 ms entra, 150 ms sai | `translateY(12px→0)` + fade / fade |
| Seta do CTA e links com seta | 200 ms | `translate-x-1` no hover (padrão atual) |
| Skeleton shimmer | 1 200 ms linear infinite | §2.12 |
| Spinner de loading | 800 ms linear infinite | §2.1 |
| Scrub do vídeo | 0 ms (amarrado ao scroll via rAF) | Congelado (D-80) |

### 4.2 O que anima — e o que não

**Anima:** cor/fundo em hover; escala sutil em active (0.985–0.99); entrada de passo, toast e badge de
status recém-mudado; o hero (scrub, parallax da marca −28 px, cue de rolagem); shimmer/spinner.

**Não anima nunca:** layout (altura/largura de containers com conteúdo — usar skeletons do mesmo
tamanho); texto correndo/letter-spacing; preços e horários (aparecem prontos — número que "conta" é
ruído aqui); a logo (além do parallax do hero); scroll da página (sem smooth-scroll global); nada em
loop infinito fora de glow do CTA, shimmer e spinner.

Regra de ouro: movimento comunica **mudança de estado ou hierarquia de atenção**. O único elemento com
atenção permanente é o `.cta-agendar`. Se dois elementos pulsam ao mesmo tempo, um está errado.

### 4.3 `prefers-reduced-motion`

Mecanismo global já existe em `globals.css` (zera `animation-duration`/`transition-duration`) — mantido.
Complementos obrigatórios:
- Hero: sem scrub — primeiro quadro/poster estático (já implementado);
- `scrollIntoView`/rolagens programáticas: sem `behavior: "smooth"`;
- Skeleton: bloco estático sem shimmer;
- Toast/passos: aparecem sem deslocamento (o fade de 0,01 ms do reset global cobre isso).
Nenhuma informação pode existir **apenas** no movimento (ex.: o slot 409 fica riscado, não só "pisca").

---

## 5. Checklist de conformidade (para PR de frontend)

- [ ] Nenhum hex novo fora deste documento; toda cor via token.
- [ ] `--cinza` nunca em texto essencial < 18 px (ou < 14 px/600).
- [ ] Texto sobre `--destaque`/prata é sempre `--grafite`.
- [ ] Alvos de toque ≥ 44 px; inputs com fonte ≥ 16 px.
- [ ] `.stripe` ≤ 3 usos por tela, só nos contextos do §3.6.
- [ ] Fixed bottom sempre com `env(safe-area-inset-bottom)`.
- [ ] Loading não muda largura de botão; skeleton não causa layout shift.
- [ ] `focus-visible` visível em todo interativo; `role`/`aria` conforme §2.
- [ ] `prefers-reduced-motion` verificado nas 3 páginas.
- [ ] Logo: proporção intacta, ≥ 120 px, clearspace §3.3.
