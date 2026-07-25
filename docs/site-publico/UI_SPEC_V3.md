# UI_SPEC_V3 — Site público "A placa à noite, em ouro"

> **Fonte de verdade visual do site público a partir de 2026-07-24.**
> **✅ EM PRODUÇÃO** desde 2026-07-24 no apex `taylorethedy.com` (D-82, commit `455842d`).
> Substitui a `UI_SPEC_V2.md` ("A placa à luz do dia", tema claro, 2026-07-22),
> que fica no repo apenas como registro histórico. As regras de UX de fluxo do
> `UX_PLAN.md` continuam valendo — só a pele mudou.

## 0. Decisão

O dono pediu o site público **em formato landing page, escuro e dourado, com o
agendamento mantido como ação principal**. A vitrine institucional e o app de
agendamento passam a ser **um só produto** com um só sistema visual: quem cai
no apex vê a landing e converte ali mesmo; `/agendar` e `/meus-agendamentos`
são continuação da mesma página, não outro site.

## 1. A marca (imutável)

A marca vem da **fachada real**: `assets/images/fachada-real.png` (foto do
letreiro em Palmas). Ver `assets/images/README.md` — há um mockup gerado por IA
no mesmo diretório que **não** é a marca e já custou três rodadas de retrabalho.

Anatomia do wordmark (`components/wordmark.tsx`):

- **placa marfim com o "t" VAZADO** = `public/t-fachada.png` (746×1334, alfa
  real). O "t" **nunca** é fonte nem SVG desenhado à mão;
- palavras **"aylor" / "hedy"** empilhadas à direita, em Cormorant Garamond
  light, `line-height: 0.78`, `letter-spacing: 0.02em`;
- a placa mede **1,86× o `font-size`** das palavras e alinha por `flex-start`,
  de modo que ultrapassa o "aylor" em cima e a linha do "hedy" embaixo;
- o recorte do "t" mostra o fundo da página → **o wordmark exige fundo escuro**.

## 2. Tokens (`app/globals.css`)

| Papel | Token | Valor |
| --- | --- | --- |
| Fundo da página | `--fundo` | `#0a0b0d` |
| Card / superfície | `--superficie` | `#121316` |
| Superfície 2 / 3 | `--superficie-2` / `-3` | `#1a1c20` / `#24262b` |
| Texto principal | `--marfim` / `--tinta` | `#f2efe9` |
| Texto secundário | `--tinta-suave` | `#b4b0a8` |
| Texto terciário | `--tinta-fraca` | `#918d85` |
| Tinta sobre ouro | `--tinta-invertida` | `#14120d` |
| **Ação** | `--ouro` | `#c9a86a` |
| Ação (hover / profundo) | `--ouro-claro` / `--ouro-profundo` | `#e2c68f` / `#a8874a` |
| Fios | `--borda-sutil` / `--borda` | `rgba(234,230,222,.09)` / `.16` |

**Regra de ouro (literal):** o dourado é reservado à ação e ao acento de
seção. Nada mais no site é dourado sólido — se tudo brilha, o CTA não brilha.

Tipografia: **Cormorant Garamond** (marca, títulos, preços) + **Jost** (texto,
versaletes, dados). Variáveis `--font-cormorant` / `--font-jost`.

## 3. Anatomia da landing (`app/page.tsx`)

1. **`SiteHeader`** — fixo, wordmark + âncoras (some no mobile) + pílula
   "Agendar" sempre visível.
2. **`Hero`** — wordmark grande → "Renove seu estilo." → promessa →
   prova (4,8 ★ · 400 avaliações) → **CTA `.cta-agendar`** → link discreto para
   "meus agendamentos" → régua de números (nota / profissionais / horário).
   Halo dourado radial atrás da marca = a placa iluminada à noite.
3. **Serviços** — agrupados por categoria; cada linha é um atalho que já leva
   o serviço escolhido (`/agendar?servico={id}`).
4. **Nossa casa** — fotos reais (fachada + vista aérea do drone). A foto da
   fachada leva **legenda de localização colada nela** (`components/ui/endereco.tsx`:
   endereço + "Abrir no Google Maps"), porque é olhando a fachada que nasce a
   pergunta "onde fica?". A mesma legenda acompanha a foto no hero do desktop.
   Repetir o endereço da seção "Onde e quando" é deliberado.
5. **Clientes** — depoimentos **verbatim** do Google (`components/depoimentos.tsx`).
6. **Equipe**, 7. **Onde e quando**, 8. **Fechamento** (segundo `.cta-agendar`),
   9. **Rodapé**.
10. **`StickyCta`** — entra só **depois** que o hero sai por cima da viewport
    (sentinela `#fim-do-hero`), para não duplicar o CTA na primeira tela.

## 4. Níveis de ação

| Nível | Onde | Tratamento |
| --- | --- | --- |
| 1 | Hero e fechamento da landing | `.cta-agendar` — ouro com facho e glow (timings congelados: 180ms / 3,2s / 3,6s) |
| 2 | Passos do fluxo, sticky bar, banner de instalação | ouro sólido + `--tinta-invertida` |
| 3 | Alternativas | contorno; hover vira ouro |
| 4 | Navegação | texto em `--tinta-suave`, hover marfim |

## 4.1 Obrigatórios de página (auditados em 2026-07-25)

- `aria-labelledby` de cada `<section>` aponta para o **id do `<h2>`**, nunca
  para a própria section.
- JSON-LD `HairSalon`: `dayOfWeek` em **inglês** (`WEEKDAYS_SCHEMA`) — em
  português o Google descarta o horário; `address` como `PostalAddress`.
- `og:image` = `public/og.jpg` (1200×630). Sem ele o link no WhatsApp, que é
  como o negócio divulga, sai sem imagem.
- `app/robots.ts` + `app/sitemap.ts`; `/meus-agendamentos` fora do índice.
- Skip link para `/agendar` como primeiro alvo de tabulação.
- Contraste verificado por cálculo, não a olho: mínimo do sistema é 5,2:1.

## 5. Prova social

`components/depoimentos.tsx` guarda a nota, o total e os textos. Só entram
avaliações **públicas e verbatim** do Google (fonte: `Avaliaçoesgoogle.pdf`,
exportado em 24/07/2026 — 4,8 em 400 avaliações). Nada parafraseado, nada
inventado. Se um depoimento sair do ar, sai daqui também.

## 6. Pendências conhecidas

- **Validação num celular real** — o que foi ao ar passou só por captura
  headless (430×932 e 1280) e smoke HTTP.
- Galeria interna (cadeiras, equipe trabalhando) — só existem duas fotos hoje.
- Tabs de categoria em vez de lista agrupada (exigiria client component).
- Reagendar com pré-seleção continua bloqueado pela API (devolve nomes, não ids).
