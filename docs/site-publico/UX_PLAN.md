# UX_PLAN — Site Público de Agendamento (taylorethedy.com)

> **Papel:** UX Designer da equipe do site público (`barbearia-public/`).
> **Escopo desta rodada:** do hero para baixo + fluxos `/agendar` e `/meus-agendamentos`.
> O hero cinematográfico (D-80) está aprovado e **não** é redesenhado aqui.
> **Restrições respeitadas:** sem OTP (sessão cookie 400 dias que só vê o que ela criou),
> backend congelado (só os endpoints de `app/api/public.py`), conversão em 1º lugar.
> Data: 2026-07-22.

---

## 1. Auditoria de usabilidade do fluxo atual (heurísticas de Nielsen)

Fluxo real: `/` (home SSR) → CTA → `/agendar` (`BookingFlow`, 4 passos: serviço →
profissional → dia/horário → identificação+confirmação) → tela de sucesso →
`/meus-agendamentos`. Sessão: cookie HttpOnly `tt_session`; o front só guarda o nome em
`localStorage` (`tt_client_name`, `booking-flow.tsx:32`).

### 1.1 Achados — fluxo de agendamento (`components/booking-flow.tsx`)

| # | Achado | Heurística | Onde | Severidade |
|---|--------|-----------|------|------------|
| A1 | **Erro de "horário ocupado" (409) fica invisível.** No 409 o código seta `error` e volta ao passo 3 (`booking-flow.tsx:172-174`), mas `error` só é renderizado dentro do passo 4 (`booking-flow.tsx:413` e `:437`). O usuário é jogado de volta à grade de horários **sem nenhuma explicação** — parece bug do site. | Visibilidade do estado do sistema | `booking-flow.tsx:172-174` vs `:413/:437` | **Alta** |
| A2 | **Régua de dias mostra dias em que a barbearia está fechada.** Os 14 dias são gerados sem consultar `info.hours` (`booking-flow.tsx:94-101`); tocar num domingo fechado leva a "Sem horários livres neste dia" — tentativa e erro. Os horários de funcionamento já chegam no payload (`lib/api.ts:42`), dá para desabilitar/marcar "Fechado" sem backend. | Prevenção de erros | `booking-flow.tsx:94-101, 296-312` | **Alta** |
| A3 | **Dia sem vaga é beco sem saída.** Estado vazio diz "Escolha outro dia acima" (`booking-flow.tsx:327-331`) mas não oferece ação — o usuário volta a caçar dia por dia. | Eficiência de uso / controle do usuário | `booking-flow.tsx:327-331` | **Alta** |
| A4 | **Cancelamento sem confirmação.** Em `/meus-agendamentos`, "Cancelar" executa direto no toque (`meus-agendamentos/page.tsx:116-121`) — ação destrutiva e irreversível pelo site (reagendar = refazer o fluxo) num link de texto pequeno. | Prevenção de erros | `meus-agendamentos/page.tsx:112-122` | **Alta** |
| A5 | **Um único profissional elegível ainda custa um passo inteiro.** `eligiblePros` é calculado (`booking-flow.tsx:105-111`) mas o passo 2 sempre é exibido, mesmo com 1 opção — toque desperdiçado no caminho crítico. | Eficiência de uso | `booking-flow.tsx:248-285` | Média |
| A6 | **A home não pré-seleciona o serviço.** A lista de serviços da home é estática (`app/page.tsx:75-85`); o cliente lê "Corte — R$ 45", decide, toca no CTA… e escolhe o serviço de novo no passo 1. `BookingFlow` não lê query param nenhum. | Reconhecimento em vez de memorização | `app/page.tsx:75-85`, `booking-flow.tsx:70-84` | **Alta** |
| A7 | **Depois do hero, não há mais nenhum CTA de agendar na home.** Rolo até o rodapé (Contato, `app/page.tsx:138-173`) e o único caminho é voltar 2 telas de scroll. Conversão vaza no fim da página. | Visibilidade / conversão | `app/page.tsx:68-174` | **Alta** |
| A8 | **Loading de slots é texto puro** ("Buscando horários…", `booking-flow.tsx:316-318`) — em 4G o salto de layout entre "texto de 1 linha" e "grade de 12 botões" desorienta e convida a toques duplos no dia. | Visibilidade do estado do sistema | `booking-flow.tsx:316-318` | Média |
| A9 | **Sessão expirada no meio da confirmação recomeça mudo.** No 401, o formulário de identificação reaparece com "Confirme seus dados…" (`booking-flow.tsx:166-171`) — correto, mas o usuário "conhecido" (`knownName`) não entende por que foi deslogado. Mensagem ok; falta reforçar que **o horário escolhido continua reservado na tela** (está, mas nada diz isso). | Ajuda a reconhecer/recuperar erros | `booking-flow.tsx:166-171` | Baixa |
| A10 | **Validação de telefone só no submit.** Máscara existe (`booking-flow.tsx:402`), mas nome/telefone inválidos só avisam depois do toque em "Confirmar agendamento" (`booking-flow.tsx:152-157`), num fluxo em que esse é o toque emocional mais caro. | Prevenção de erros | `booking-flow.tsx:151-157` | Média |
| A11 | Lista de 14 dias é congelada no mount (`useMemo` com `[]`, `booking-flow.tsx:94-101`) — num PWA que fica dias aberto em background, a régua envelhece e "hoje" vira ontem. | Consistência / estado do sistema | `booking-flow.tsx:94-101` | Baixa |
| A12 | Passo 2 vazio ("Nenhum profissional disponível…", `booking-flow.tsx:278-282`) não oferece saída (voltar é link pequeno). Raro (o `/info` já filtra serviço sem profissional — `app/api/public.py:307-308`), mas possível se a visibilidade mudar entre o SSR (revalidate 60 s) e o toque. | Controle do usuário | `booking-flow.tsx:278-283` | Baixa |

### 1.2 Achados — home e meus agendamentos

| # | Achado | Onde | Severidade |
|---|--------|------|------------|
| B1 | **Erro de rede na home não tem retry** — só texto "Tente novamente em instantes" (`app/page.tsx:42-52`). Idem `/agendar`, que ainda sugere "chame a gente no WhatsApp" **sem link** (`agendar/page.tsx:17-30` — o número existe em `public_info.whatsapp`, mas nesse ramo o `info` é null; usar link estático do tenant). | `app/page.tsx:42-52`, `agendar/page.tsx:17-30` | Média |
| B2 | Sem sessão, `/meus-agendamentos` explica bem ("neste aparelho", `meus-agendamentos/page.tsx:57-69`) — **bom**. Mas quem agendou noutro aparelho não tem pista de recuperação (esperado na v1 sem OTP; microcopy deve dizer "futuro" sem prometer). | `meus-agendamentos/page.tsx:57-69` | Baixa |
| B3 | Quando o cancelamento não é mais possível (<2h ou status ≠ agendado), o botão simplesmente **some** (`meus-agendamentos/page.tsx:114`); a regra só aparece numa nota de rodapé (`:128-133`). Melhor: estado desabilitado com o motivo no card. | `meus-agendamentos/page.tsx:112-133` | Média |
| B4 | `banner` chega no payload (`lib/api.ts:43`) e nunca é renderizado — promoções configuradas pelo gestor (D-73) não aparecem. | `app/page.tsx` | Baixa (v1) |
| B5 | Tela de sucesso não oferece "adicionar ao calendário" (`.ics`) nem o endereço da barbearia — dois reforços clássicos de comparecimento. | `booking-flow.tsx:183-214` | Baixa |

### 1.3 Estados hoje (resumo verificado no código)

- **Loading:** slots = texto (`booking-flow.tsx:316`); meus-agendamentos = "Carregando…" (`:73-75`); home SSR (sem loading percebido).
- **Vazio:** dia sem slots (`booking-flow.tsx:327`); sem sessão / lista vazia (`meus-agendamentos/page.tsx:57-87`) — ambos com CTA, bom.
- **Erro de rede:** slots tem "Tentar de novo" (`booking-flow.tsx:319-326`) — bom; home e /agendar não têm retry (B1).
- **409 (corrida de slot):** tratado no backend duas vezes (`public.py:480-485`) e no front (`booking-flow.tsx:172-174`), mas com feedback invisível (A1).
- **401 (sem sessão):** agendar → volta à identificação (`booking-flow.tsx:166-171`); meus-agendamentos → estado "neste aparelho" (`:26`).
- **Cancelamento <2h:** backend devolve 422 com mensagem pronta (`public.py:625-630`); o front a exibe genérica no topo — mas o botão nem aparece nesses casos (B3).

---

## 2. Jornada ideal do usuário

Meta global: **primeira visita agenda em ≤ 6 toques + 2 campos digitados; retorno agenda
em ≤ 4 toques; cancelar em ≤ 3 toques.** Contagem = toques de decisão (scroll não conta).

### 2.1 Primeira visita → agendou

| Etapa | Tela | Toques | Observação |
|---|---|---|---|
| 1. Chega pelo link do WhatsApp/Instagram | Hero | 0 | CTA "Agendar horário" na faixa do polegar (já deployado) |
| 2. Toca no CTA (ou num serviço da home) | `/` → `/agendar` | 1 | Se tocou num **serviço** da home, pula o passo 1 (A6) |
| 3. Escolhe serviço | Passo 1 | 1 | 0 se veio pré-selecionado |
| 4. Escolhe profissional | Passo 2 | 1 | 0 se só há 1 elegível (A5) |
| 5. Escolhe dia + horário | Passo 3 | 1–2 | Dia "hoje" já ativo; dias fechados desabilitados (A2); atalho "próximo dia com vaga" (A3) |
| 6. Identifica-se | Passo 4 | 2 campos + 1 | Nome + WhatsApp, uma única vez neste aparelho |
| **Total** | | **4–6 toques + 2 campos** | |

Pós-sucesso: tela "Horário marcado!" → InstallBanner (PWA) → "Ver meus agendamentos".

### 2.2 Retorno (sessão viva) → agendou de novo

CTA (1) → serviço (0–1, com pré-seleção) → profissional (0–1) → horário (1–2) →
"Agendando como Fulano" + Confirmar (1) = **3–5 toques, zero digitação**. É o payoff da
sessão de 400 dias — a microcopy do InstallBanner já promete "agenda em 2 toques"
(`install-banner.tsx:49-50`); a jornada precisa chegar perto disso.

### 2.3 Retorno → cancelou / reagendou

- Cancelar: hero "Ver meus agendamentos" (1) → "Cancelar" no card (1) → confirmar no
  diálogo (1, novo — A4) = **3 toques**.
- Reagendar (não existe endpoint de remarcação): após confirmar o cancelamento, oferecer
  **"Agendar novo horário"** já com o mesmo serviço+profissional pré-selecionados
  (deep-link interno) → cai direto no passo 3. Reagendamento efetivo em **3 + 2 toques**,
  sem backend novo.

---

## 3. Arquitetura de informação

### 3.1 Home `/` (abaixo do hero) — ordem e porquê

1. **Serviços** (já é a 1ª seção — manter): é a pergunta nº 1 de quem chega ("quanto custa
   o corte?") e vira atalho de conversão — cada linha passa a ser **tocável** →
   `/agendar?servico={id}` (A6).
2. **Quem atende**: prova social interna, prepara a escolha do passo 2. Manter cards; sem
   ação nesta v1 (tocar num profissional para filtrar é P2).
3. **Promoções/banner** *(condicional — só se `banner` tiver conteúdo)*: entre equipe e
   horários; hoje o dado chega e é descartado (B4).
4. **Horário de funcionamento**: informação de suporte à decisão, não de conversão — fica
   depois; destaque para "hoje" (linha do dia atual em negrito, "Aberto agora/Fechado").
5. **Contato + endereço** (rodapé): WhatsApp/Instagram/Ligar já existem; adicionar link
   "Como chegar" (Google Maps a partir de `public_info.address`).
6. **CTA de fechamento** (novo — A7): botão "Agendar horário" largo ao fim do rodapé +
   **barra fixa inferior** (aparece após o hero sair da viewport, some em `/agendar`):
   `[ Agendar horário ]  [ Meus agendamentos ]`. Ninguém deveria precisar rolar de volta.

Avaliações: fora da v1 (flag existe no D-73, sem conteúdo — `ARQUITETURA_SITE_PUBLICO.md §7`).

### 3.2 `/agendar` — mantém o stepper de 4 passos

A ordem serviço → profissional → horário está certa (o serviço define duração e
profissionais elegíveis; o backend exige `service_id`+`barber_id` para `/slots`). Mudanças
são de **atalho**, não de ordem: pré-seleção via query, auto-skip do passo 2 com 1
profissional, resumo compacto persistente da seleção no topo dos passos 3–4 (hoje é um
subtítulo — promover a "chips" tocáveis que voltam ao passo correspondente).

### 3.3 `/meus-agendamentos`

Ordem da lista: **próximos primeiro** (hoje vem `start_at DESC` cru da API —
`public.py:568` — o que põe o agendamento mais futuro no topo, mas mistura histórico).
Reagrupar no cliente: seção "Próximos" (agendado, futuro, ASC) e seção "Histórico"
(resto, DESC, colapsada após 3 itens). Card: serviço, data/hora, profissional, status,
preço, ação de cancelar (com motivo quando bloqueada — B3). Rodapé: regra das 2h + link
WhatsApp para exceções.

---

## 4. Especificação de interação por tela

> Tokens existentes: `grafite` (fundo), `aco`/`aco-claro` (cards), `prata`/`prata-suave`/
> `cinza` (texto), `destaque` (CTA), `vermelho`, `verde`. Sem cor nova.

### 4.1 Home — barra fixa de conversão (nova)

```
┌─────────────────────────────────────┐
│  (conteúdo rolando…)                │
├─────────────────────────────────────┤
│ ┌───────────────────────────────┐   │  barra fixa, fundo grafite
│ │      Agendar horário  →       │   │  translúcido + blur, safe-area
│ └───────────────────────────────┘   │  bottom, altura ≥ 56px
│        Meus agendamentos            │  link secundário 44px
└─────────────────────────────────────┘
```
- **Aparece** quando o hero (wrapper `h-[200svh]`) sai da viewport (IntersectionObserver);
  entra com fade curto; **respeita `prefers-reduced-motion`** (sem animação).
- Serviço tocável: linha inteira vira link com chevron `›`; leva a `/agendar?servico={id}`.

### 4.2 `/agendar` — passo 3 (horário) com os fixes

```
┌─────────────────────────────────────┐
│ ← Taylor & Thedy                    │
│ ▓▓▓ ── ── ──   Serviço Profis Horá… │  stepper atual (ok)
│ Escolha o horário                   │
│ [Corte ✕] [Marcos ✕]                │  chips da seleção (voltam ao passo)
│ ┌────┐┌────┐┌────┐┌────┐┌────┐ →    │  régua de dias (scroll-x)
│ │TER ││QUA ││QUI ││SEX ││SÁB │      │  dia fechado: cinza + "Fechado",
│ │ 22 ││ 23 ││ 24 ││ 25 ││ 26 │      │  disabled (não navegável)
│ └────┘└────┘└────┘└────┘└────┘      │
│ MANHÃ                               │
│ [ 09:00 ][ 09:30 ][ 10:00 ][10:30]  │  grade 4 col, botões ≥44px
│ TARDE                               │
│ [ 14:00 ][ 14:30 ] …                │
└─────────────────────────────────────┘
```
Estados do passo 3:
- **Loading:** skeleton — 2 títulos de período + 8 pílulas cinza pulsando (mesma grade,
  sem salto de layout). Substitui o texto de `booking-flow.tsx:316-318`.
- **Vazio:** "Sem horários com {Profissional} neste dia." + botão primário
  **"Ver próximo dia com horário"** (itera `dayOffset+1` sobre dias abertos, busca
  `/slots` até achar; máx. 14 dias; se nada: "Sem horários nos próximos 14 dias — chame a
  gente no WhatsApp" + link `wa.me`).
- **Erro de rede:** manter retry atual (`booking-flow.tsx:319-326`), com botão de 44px.
- **Volta por 409 (A1):** ao regressar do passo 4, exibir banner no topo da grade:
  ⚠ "Esse horário acabou de ser reservado por outra pessoa. Os horários abaixo estão
  atualizados." (a recarga já acontece via `useEffect` — só falta o aviso ser visível).
  O slot anteriormente escolhido, se ainda listado, não fica pré-marcado.

### 4.3 `/agendar` — passo 4 (confirmar)

```
┌─────────────────────────────────────┐
│ Confirme                            │
│ ┌─────────────────────────────────┐ │
│ │ Corte degradê                   │ │
│ │ terça, 22 de julho às 14:30     │ │
│ │ com Marcos          R$ 45,00    │ │
│ │ Pagamento na barbearia          │ │  (nova linha — evita dúvida)
│ └─────────────────────────────────┘ │
│ Seu nome                            │
│ [__________________________]        │
│ WhatsApp / celular                  │
│ [ (63) 9____-____ ]                 │
│ Usamos seu número só para confirmar │
│ e lembrar do horário.               │
│ ┌───────────────────────────────┐   │
│ │     Confirmar agendamento     │   │  56px, destaque
│ └───────────────────────────────┘   │
└─────────────────────────────────────┘
```
- Validação **no blur** de cada campo (A10): nome <2 chars → "Digite seu nome."; telefone
  <10 dígitos → "Digite um celular com DDD, ex.: (63) 99999-9999." O botão permanece
  habilitado (erro no submit continua como rede de segurança).
- Usuário conhecido: manter "Agendando como {nome} — não é você?" (`booking-flow.tsx:424-436`).
- 401 (A9): acima do formulário reaberto: "Sua identificação expirou neste aparelho.
  Confirme seus dados — **seu horário continua selecionado**."
- Duplo toque: `submitting` já desabilita (`booking-flow.tsx:416`) — manter.

### 4.4 Tela de sucesso

Manter estrutura atual (`booking-flow.tsx:183-213`): resumo + InstallBanner + CTAs.
Acrescentar: endereço da barbearia (de `public_info.address`) + link "Como chegar" (B5).
Microcopy do título: manter "Horário marcado!"; subtítulo novo: "Te esperamos lá.
Chegando perto do horário, a gente te lembra no WhatsApp." (o lembrete 24h já cobre o
site — D-79).

### 4.5 `/meus-agendamentos` — card + diálogo de cancelamento

```
┌─────────────────────────────────────┐
│ PRÓXIMOS                            │
│ ┌─────────────────────────────────┐ │
│ │ Corte degradê        [Agendado] │ │
│ │ terça, 22 de julho às 14:30     │ │
│ │ com Marcos          R$ 45,00    │ │
│ │ ┌───────────────┐               │ │
│ │ │   Cancelar    │  (44px)       │ │
│ │ └───────────────┘               │ │
│ └─────────────────────────────────┘ │
│ ┌─────────────────────────────────┐ │
│ │ Barba                [Agendado] │ │
│ │ hoje às 15:00 · com Thiago      │ │
│ │ Cancelamento pelo site encerrou │ │  <2h: sem botão, motivo no card
│ │ (menos de 2h). Fale no WhatsApp.│ │  + link wa.me
│ └─────────────────────────────────┘ │
│ HISTÓRICO (3)              ver tudo │
└─────────────────────────────────────┘
```
Diálogo de confirmação (A4 — bottom sheet simples):
- Título: **"Cancelar este horário?"**
- Corpo: "{Serviço} · {data} às {hora} com {profissional}."
- Botões: `[ Manter horário ]` (secundário) / `[ Cancelar agendamento ]` (vermelho).
- Sucesso: toast/linha "Horário cancelado." + botão **"Agendar novo horário"** →
  `/agendar?servico={id}&profissional={id}` (o "reagendar" da v1, §2.3).
- Erro 422 do backend (corrida com a janela de 2h): exibir `detail` da API no diálogo
  ("Cancelamento pelo site só até 2h antes…" — `public.py:625-630`) e recarregar a lista.
- Erro de rede: "Sem conexão. Seu horário **não** foi cancelado — tente de novo."

### 4.6 Erros de rede globais (B1)

- Home sem `info`: manter texto + **botão "Tentar de novo"** (recarrega) + link WhatsApp
  estático do tenant.
- `/agendar` sem `info`: idem, com `wa.me` linkado de verdade.

### Microcopy consolidada (pronta para uso)

| Contexto | Texto |
|---|---|
| Passo 1 título | "O que vai fazer hoje?" *(manter)* |
| Passo 2 título | "Quem vai te atender?" *(manter)* |
| Passo 3 vazio | "Sem horários com {nome} neste dia." / botão "Ver próximo dia com horário" |
| Passo 3 exaurido | "Sem horários nos próximos 14 dias. Chame a gente no WhatsApp que a Raquel dá um jeito. 😉" |
| Banner 409 | "Esse horário acabou de ser reservado por outra pessoa. Escolha outro — a lista já está atualizada." |
| 401 na confirmação | "Sua identificação expirou neste aparelho. Confirme seus dados — seu horário continua selecionado." |
| Validação nome | "Digite seu nome." |
| Validação telefone | "Digite um celular com DDD, ex.: (63) 99999-9999." |
| Sucesso | "Horário marcado!" + "Te esperamos lá. Chegando perto do horário, a gente te lembra no WhatsApp." |
| Diálogo cancelar | "Cancelar este horário?" / "Manter horário" / "Cancelar agendamento" |
| Cancelado | "Horário cancelado." / botão "Agendar novo horário" |
| Cancelamento bloqueado (<2h) | "Cancelamento pelo site encerrou (menos de 2h para o horário). Fale com a gente no WhatsApp." |
| Erro de rede genérico | "Sem conexão agora. Tente de novo em instantes." / botão "Tentar de novo" |
| Barra fixa | "Agendar horário" / "Meus agendamentos" |

---

## 5. Acessibilidade e mobile

1. **Alvos de toque ≥ 44×44px:** hoje ficam abaixo: slots (`py-2.5`, ~41px —
   `booking-flow.tsx:347`), "← Voltar" (texto sm — `:454-462`), "Cancelar"
   (`meus-agendamentos/page.tsx:116-121`), "não é você?" (`booking-flow.tsx:426-435`),
   "Tentar de novo" (`:322`). Padding mínimo `py-3`/área de toque expandida em todos.
2. **Semântica da régua de dias:** `role="tablist"`/`role="tab"` sem navegação por setas
   nem `tabpanel` associado (`booking-flow.tsx:295-312`) — trocar por grupo de botões com
   `aria-pressed` (mais honesto e barato que implementar o padrão tabs completo). Slots:
   anunciar seleção; grade com `aria-live="polite"` no resultado da busca ("12 horários
   disponíveis" / "nenhum horário").
3. **Foco:** ao trocar de passo, mover o foco para o `h1` do passo (com `tabIndex={-1}`);
   no diálogo de cancelamento, focar o botão "Manter horário" (opção segura) e prender o
   foco no diálogo; `Esc` fecha.
4. **Contraste:** revisar `text-cinza` sobre `grafite`/`aco` nos textos informativos
   (duração "45 min", notas de rodapé) — alvo WCAG AA 4.5:1 para texto <18px; se falhar,
   promover para `prata-suave`.
5. **Reduced motion:** hero já respeita (`hero-cinematic.tsx:33-52`); estender a regra à
   barra fixa (sem fade), skeleton (sem pulso) e bottom sheet (sem slide).
6. **Offline/PWA básico:** SW já registrado (`register-sw.tsx`). Comportamento esperado:
   shell da home servido do cache com aviso "Você está offline — os horários serão
   atualizados quando a conexão voltar"; `/slots` e ações POST **nunca** respondem do
   cache (risco de slot fantasma); falha de POST offline usa a microcopy de rede do §4.
   Nada de fila offline de agendamento nesta v1.
7. **Teclado/inputs:** `inputMode="tel"` e autocompletes já corretos
   (`booking-flow.tsx:388-404`); garantir que a barra fixa não cubra o botão de submit
   com o teclado aberto (ocultar a barra em `/agendar`).

---

## 6. Priorização para o Front-end (esta rodada)

**P0 — conversão máxima, esforço baixo (fazer primeiro):**
1. Feedback visível do 409 no passo 3 (A1) — banner + microcopy §4.2. *(bug de UX real)*
2. Serviços da home tocáveis + `?servico=` pré-selecionando o passo 1 (A6).
3. Barra fixa "Agendar horário" na home após o hero (A7).
4. Diálogo de confirmação de cancelamento + toast + "Agendar novo horário" (A4, §4.5).
5. Dias fechados desabilitados na régua usando `info.hours` (A2).
6. Alvos de toque ≥44px nos pontos listados no §5.1.

**P1 — fricção do caminho crítico:**
7. "Ver próximo dia com horário" no estado vazio do passo 3 (A3).
8. Auto-skip do passo 2 quando há 1 profissional elegível (A5).
9. Skeleton de slots (A8) + validação on-blur no passo 4 (A10).
10. Motivo do cancelamento bloqueado no card + link WhatsApp (B3); Próximos × Histórico.
11. Retry + link WhatsApp real nos erros de rede da home e do `/agendar` (B1).
12. Chips de seleção nos passos 3–4 (voltar tocando no chip).
13. Foco por passo + `aria-pressed`/`aria-live` (§5.2–5.3).

**P2 — polimento / próxima rodada:**
14. Renderizar `banner`/promoções na home (B4); "Aberto agora" nos horários.
15. "Adicionar ao calendário" (.ics) e endereço na tela de sucesso (B5).
16. Regenerar a régua de dias ao voltar do background (A11); estado vazio do passo 2 com CTA (A12).
17. Tocar num profissional da home → `/agendar?profissional=` (par do item 2).
18. Aviso offline do shell PWA (§5.6).

**Fora do escopo (não implementar):** OTP/login por WhatsApp ou SMS (futuro, Cloud API),
remarcação nativa (exigiria endpoint novo), avaliações, fidelidade no site, qualquer
mudança em `app/api/public.py`, qualquer alteração no hero (D-80, aprovado).
