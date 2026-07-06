# Análise Estratégica — Aproveitamento dos Dados do Trinks e Evolução do Dashboard

> **Documento de análise — NÃO é implementação.** Nenhum código ou banco foi
> alterado na produção deste relatório. Gerado em **2026-07-04**.
> Org analisada: **Taylor & Thedy (org 1, produção)**.
> Escopo: importação/modelagem/aproveitamento de dados do Trinks + Dashboard.
> Fora de escopo (por decisão): restauração do WhatsApp e correção do CRM.
>
> Fontes de verdade vivas (não duplicar — referenciar): `CLAUDE.md`,
> `DECISIONS.md`, `docs/TRINKS_IMPORT.md`, `Relatorio_Funcionalidades_Trinks.md`,
> `gestaointeligente/Estrategia_Transicao_Receita_Recorrente_BarbeariaPro.md`.

---

## Decisões tomadas (2026-07-04)

1. **Ponto de partida do roadmap:** **Fase 1 (P0) — "Acender o que já temos"**
   (camada de leitura analítica sobre os dados já importados + import do histórico
   de agendamentos + import do catálogo de serviços). Maior ROI, reaproveita código.
2. **Verdade da receita (modelagem):**
   - `appointments` com `status='concluido'` → **verdade operacional** (receita por
     barbeiro / serviço / cliente, ticket, ocupação).
   - `payment_transactions` → **verdade financeira** (forma de pagamento, taxa de
     operadora, recebível).
   - `cash_daily_closings` → **caixa diário**.
   - **Nunca somar as fontes.** (A formalizar em `DECISIONS.md` ao iniciar a Fase 1.)
3. Este relatório é salvo como documento versionado (este arquivo).

---

## Sumário executivo — as 5 descobertas que mudam o roadmap

**① O dashboard está "cego" para o dinheiro que já está no banco.**
A barbearia faturou **R$ 414.137** (jan–jul/2026, 3.714 transações) e tem **149 dias
de caixa** já importados — mas os dois painéis (`/admin/dashboard` e `/admin/gestor`)
leem **exclusivamente** `AppointmentItem.price_charged` de agendamentos com
`status='concluido'`. Como os 47 agendamentos importados entraram como `agendado` e
ninguém concluiu atendimento pelo sistema ainda, **o dashboard mostra ~R$ 0 de
receita** para um negócio que faturou R$ 72 mil só em junho. O histórico real mora em
`payment_transactions` e `cash_daily_closings`, tabelas que **nenhum painel consulta**.
Gap de maior impacto e menor esforço.

**② Falta o "atalho" que acende o dashboard inteiro: o histórico de agendamentos.**
O Trinks permite exportar o **histórico completo de atendimentos** (`Consultar
Agendamentos`: Data, Profissional, Serviço, Valor, Cliente, **Status=Finalizado**). O
importador **já existe** (`app/services/trinks_appointments.py`) — hoje só rodou sobre
os 47 futuros de julho e **grava tudo como `agendado`**. Rodá-lo sobre o histórico e
mapear `Finalizado→concluido` **reacende, com código já pronto**, TODOS os KPIs
existentes (receita, ranking de barbeiros, top serviços, ticket, ocupação) **e** cria o
cruzamento cliente×barbeiro×serviço×valor que as tabelas analíticas não têm.

**③ O ativo mais rico e mais subaproveitado já está importado: `client_loyalty`.**
**2.197 clientes** com `total_spent`, `visit_count`, `last_visit_at` e `status`
(640 ativos / 290 em risco / 1.267 inativos). Retenção, churn, frequência, LTV e
segmentação RFM — mas o dashboard só usa o `status`. Muito valor, esforço quase nulo.

**④ O DRE do Trinks vai até 03/2020 — 6+ anos de histórico mensal.**
Receitas por tipo e despesas itemizadas, mês a mês. Destrava evolução mensal,
sazonalidade e comparativos ano-a-ano **no dia 1**.

**⑤ Metade da verdade financeira — as despesas — está 100% ausente.**
A tabela `Expense` está **vazia**. Sem ela, "Resultado/Líquido" é falso (só
receita − comissão). O Trinks tem despesas em 83 tipos / 5 categorias + DRE.

> **Recomendação central (base da Fase 1):** começar por **tornar visível o que já
> foi importado** (camada de leitura analítica) e por **um import de altíssima
> alavancagem — o histórico de agendamentos** — antes de qualquer feature nova.

---

## Parte 1 — Estado atual do Dashboard

Dois painéis, ambos com SQL real (nada mockado); o "vazio" vem de tabelas de origem
sem escrita.

### 1.1 Painel `/admin/dashboard` (operacional) — `GET /dashboard` + `/dashboard/operacional`

| KPI | Fonte | Real em prod hoje? |
|---|---|---|
| Receita do período | `Σ AppointmentItem.price_charged` (concluído) | ❌ ~0 (nada concluído no sistema) |
| Ticket médio | receita ÷ nº concluídos | ❌ ~0 |
| Novos clientes / total | `COUNT(Client)` por `created_at` | ⚠️ **distorcido** (import setou `created_at`=01/07 → infla julho, zera resto) |
| Clientes em risco | `ClientLoyalty.status='em_risco'` | ✅ real (D-62) |
| Receita por dia (barras) | idem receita, por dia | ❌ ~0 |
| Ocupação (concluído/agendado/cancelado/faltou) | `COUNT(Appointment)` por status | ⚠️ só os 47 de julho, todos `agendado` |
| Ranking de barbeiros (receita/comissão/conversão) | `AppointmentItem` por `barber_id` | ❌ ~0 |
| Top 5 serviços | `AppointmentItem`+`Service` | ❌ ~0 |
| Fidelidade — nível (VIP/Fiel/Ativo/Novo) | `ClientLoyalty.nivel` | ⚠️ **quase tudo "Novo"** (import populou `status`, não `nivel`) |
| Fidelidade — engajamento (Ativo/Risco/Inativo) | `ClientLoyalty.status` | ✅ real (~640/290/1267) |
| Leads / Funil / Fluxo comercial×fora | tabela `Lead` | ❌ vazio (import não cria leads; bot desligado) |
| Faturamento gerado pela IA | `Appointment.booking_channel='whatsapp'` | ❌ ~0 (bot bloqueado D-41) |
| Picos de demanda (por hora) | `COUNT(Appointment)` por hora, **todos status** | ⚠️ usa os 47 importados |
| Serviços realizados (lista) | idem top serviços sem limite | ❌ ~0 |

### 1.2 Painel `/admin/gestor` (gestão) — `app/services/management.py`

| KPI | Fonte | Real em prod hoje? |
|---|---|---|
| Receita / Comissões / Atendimentos | `AppointmentItem` concluído | ❌ ~0 |
| **Líquido** (receita − comissão − despesas) | + `Expense` por `competence_month` | ❌ falso (`Expense` vazia) |
| MRR (assinaturas) | `ClientMembership` ativas | ❌ 0 (nenhuma assinatura vendida) |
| Gerado pela IA | `booking_channel='whatsapp'` | ❌ ~0 |
| **Folha × Receita recorrente** (cobre a folha?) | MRR vs `Barber.monthly_cost/chair_rent` | ❌ trivial (MRR=0, custos não configurados) |
| Ranking de profissionais | `AppointmentItem` concluído | ❌ ~0 |
| Clientes inativos (+ disparar) | `ClientLoyalty.status IN (risco,inativo)` | ✅ real (~1.557 alvos); envio bloqueado (D-41) |
| Buracos na agenda (hoje) | `BusinessHours` − agenda − `TimeOff` | ⚠️ depende de horário cadastrado + agenda do dia |

### 1.3 Calculado no backend mas **sem tela** (dado morto na UI)
- **`by_method`** (mix de formas de pagamento) — calculado, tipado no front,
  **nenhum componente renderiza**. E lê `Payment` (vazia), enquanto o mix real está em
  `payment_transactions`.
- **`daily_digest`** (`noshows`, `tomorrow_idle_min`) — só via cron/WhatsApp.
- **`revenue_alerts`** (meta do mês, projeção, queda) — só via cron; **não há
  visualização de "meta vs realizado"** no dashboard.

### 1.4 Placeholders puros
`/admin/campanhas` e `/admin/usuarios` — telas estáticas "Em breve".

> **Diagnóstico:** o dashboard está **bem construído por design, mas alimentado por
> tabelas vazias**. A engenharia não é o gargalo — os **dados na tabela certa** são.

---

## Parte 2 — Análise da importação Trinks já realizada

### 2.1 O que foi importado (8 fluxos em prod; débitos descartados)

| # | Export Trinks | Tabela destino | Volume em prod | Dedup / Idempotência | Qualidade |
|---|---|---|---|---|---|
| 1 | Clientes | `clients` (+email/nasc/notes, migr. 0022) | **2.913** | por telefone (insert-only) | ✅ boa; ⚠️ `created_at`=data do import; CPF/gênero/endereço não vieram |
| 2 | Ranking de clientes → enrich | `clients` (preenche lacunas) | — | nunca sobrescreve | ✅ |
| 3 | Ranking → fidelidade (D-62) | `client_loyalty` + `loyalty_point_ledger` | **2.197** clientes / 965k pts | upsert snapshot + pontos 1×/cliente | ✅ ótima; ⚠️ populou `status`, não `nivel` |
| 4 | Agendamentos | `appointments`+`items` | **47** (julho futuro) | **sem dedup**; **todos `agendado`** | ⚠️ **crítico** (não é histórico, não é `concluido`) |
| 5 | ~~Débitos~~ **DESCARTADO** (D-65) | `client_debts` (migr. 0023) | **fonte inválida** → não importar; **0 linhas na org 1 em prod** (carga nunca rodou — nada a remover) | — | dono confirmou inválido (2026-07-06) |
| 6 | Movimentação Financeira (caixa) | `cash_daily_closings` (migr. 0026) | **149 dias** (05/01–02/07) | upsert por (org,dia) | ✅ boa; sem FK p/ cliente/barbeiro |
| 7 | Pagamentos/Estornos (D-63) | `payment_transactions` (migr. 0035) | **3.714** (R$ 414k / −R$ 6.823 taxa) | substituição de período | ✅ boa; **sem FK p/ cliente/barbeiro/serviço** |
| 8 | **DRE mensal (D-65)** | `dre_monthly_lines` (migr. 0036) | **2.752** linhas / 75 meses (mai/20–jul/26) | substituição de meses; **self-check** `checksum_ok` | ✅ ótima; **competência** (≠ recebimento); folha real |

### 2.2 Lacunas e inconsistências (o que impede o aproveitamento)

1. **Agendamentos importados são "futuros fictícios", não histórico.** Entram como
   `agendado` (`trinks_appointments.py:299`) → **nunca contam como receita**. Maior
   impacto.
2. **O histórico financeiro real está "órfão" de dimensões.** `payment_transactions` e
   `cash_daily_closings` **não têm FK** para cliente/barbeiro/serviço. Dá para ver
   receita por **dia/forma de pagamento/conta**, mas **não** por profissional/serviço/
   categoria/cliente.
3. **Nenhum painel lê as tabelas analíticas.** O dado existe, mas está invisível à UI.
4. **`created_at` dos clientes = data do import** → "Novos clientes" e coortes por data
   de cadastro distorcidos. A data real existe no export (`Data de cadastro`), não foi
   persistida.
5. **`nivel` de fidelidade ficou no default "novo"** → gráfico de nível enganoso; só
   `status` é confiável.
6. **`Expense` / despesas: 100% ausentes** → "Resultado" é meio-resultado.
7. **Dedup heterogêneo** (telefone / nome / período / nenhum). O import de agendamentos
   **sem chave** vai duplicar se re-rodado sobre histórico (precisa de estratégia de
   período, como pagamentos).
8. **`ServiceCategory` (enum: cabelo|barba|combo|quimica|estetica)** não cobre o salão
   real (Depilação, Mãos e Pés, Sobrancelha, Maquiagem, Estética) → análise por
   categoria incompleta.

---

## Parte 3 — Estudo das exportações Trinks disponíveis

Baseado em `Relatorio_Funcionalidades_Trinks.md`. Todos os módulos têm "Exportar".
Abaixo, **as oportunidades ainda não aproveitadas**, do maior para o menor valor.

### 🥇 A. Histórico completo de Agendamentos (`Consultar Agendamentos`)
- **Contém:** Data, Hora, Profissional, Serviço, Duração, Cliente, Valor, **Status
  (Finalizado/Confirmado/etc.)**, Observações, Data de cadastramento. Filtro por período
  livre → exportável desde a origem da barbearia.
- **Destino:** `appointments` + `appointment_items` (esquema e importador já existem).
- **Enriquece:** **todo o dashboard atual** — receita, ranking, top serviços, ticket,
  ocupação, picos, conversão, no-show.
- **Novas features:** frequência real, intervalo entre visitas, coorte de retenção,
  ticket por cliente/serviço/barbeiro.
- **KPIs destravados:** receita histórica, produtividade por barbeiro, desempenho por
  serviço, no-show/cancelamento, ocupação histórica, sazonalidade.
- **Automação:** previsão de demanda, alertas de queda por barbeiro, sugestão de
  reagendamento.
- **Valor p/ gestor:** ⭐⭐⭐⭐⭐ — **acende o produto inteiro com o código que já
  existe.** Import #1.
- **Requer:** mapear `Finalizado→concluido`; chave de dedup/substituição de período;
  **importar o catálogo de Serviços real antes** (de-para hoje só cobre 12 nomes).

### 🥇 B. DRE / Demonstrativo de Resultado (`DemonstrativoDeResultado`, desde 03/2020)
- **Contém:** Receitas (Serviços, Produtos, Pacotes, Vale-Presente, Crédito, Dívidas,
  Clube) e Despesas (Fixas, Variáveis, Pessoal, Impostos, Outros), **mês a mês, 6+ anos**.
- **Destino:** nova tabela `financial_monthly_summary` (org, mês, tipo, valor) — molde
  analítico D-59/D-63.
- **Enriquece:** evolução mensal, resultado real, composição de receita/despesa.
- **Novas features:** evolução multi-ano, comparativo YoY, sazonalidade, projeção.
- **KPIs:** Resultado real, margem, % receita recorrente vs avulsa, crescimento MoM/YoY.
- **Automação:** alerta de meta com **baseline histórico real**; projeção de fechamento.
- **Valor:** ⭐⭐⭐⭐⭐ — histórico executivo **no dia 1**.

### 🥈 C. Despesas / Contas a Pagar (`Despesas`, 83 tipos / 5 categorias)
- **Contém:** lançamentos (vencimento/pagamento), tipo, categoria (Fixas/Variáveis/
  Pessoal/Impostos/Outros), fornecedor, recorrência.
- **Destino:** `expense_categories` + `expenses` (**existem, vazias**) — encaixe direto.
- **Enriquece:** "Líquido/Resultado" verdadeiro; painel de despesas.
- **KPIs:** Resultado real, fixo vs variável, maiores despesas, despesa/receita %.
- **Automação:** alerta de conta a vencer; estouro de categoria.
- **Valor:** ⭐⭐⭐⭐.

### 🥈 D. Rankings de Profissionais e de Serviços
- **Contém:** produção por profissional / serviço no período (qtd, R$).
- **Destino:** **derivável** do histórico A; senão tabelas `professional_performance` /
  `service_performance`.
- **KPIs:** receita/atend. por barbeiro, mix de serviços, serviços "puxadores".
- **Valor:** ⭐⭐⭐⭐ (⭐⭐ se A já feito — vira redundante).

### 🥉 E. Produtos + Estoque + Movimentação (`Produtos`, `Estoque`, 244 itens)
- **Contém:** catálogo (nome, fabricante, categoria, preço, custo), posição (qtd, mínimo,
  custo médio), entradas/saídas.
- **Destino:** **novas tabelas** `products`, `stock_positions`, `stock_movements`,
  `suppliers`, `manufacturers`.
- **Enriquece:** abre o **módulo de Estoque/Produtos** (inexistente, no roadmap).
- **KPIs:** giro, ruptura, margem por produto, ticket com produto, mix serviço×produto.
- **Automação:** alerta de estoque mínimo, sugestão de compra.
- **Valor:** ⭐⭐⭐ (módulo novo, esforço alto).

### 🥉 F. Pacotes (`Pacotes`: venda, saldo, ranking, cadastrados)
- **Destino:** `membership_plans`/`membership_plan_items` (catálogo existe) +
  `client_memberships` (saldo vigente).
- **KPIs:** receita de pacotes, saldo a consumir (passivo), % receita recorrente.
- **Valor:** ⭐⭐⭐ — alinhado à **estratégia de receita recorrente** (`gestaointeligente`).

### G. Crédito do Cliente, Gorjetas, Comissões, Fluxo por Forma de Pagamento
- **Crédito do cliente (pré-pago):** nova `client_credits` (passivo). ⭐⭐
- **Gorjetas:** `Payment.tip_amount` existe (vazio) ou coluna em `payment_transactions`. ⭐⭐
- **Comissões/Pagamento de Profissionais:** relação (CLT/Aluguel/Parceria/Sociedade) e
  valores → alimenta `Barber.work_model/monthly_cost` (D-57) com dados reais. ⭐⭐⭐
  (destrava "Folha × Receita" com números reais).
- **Fluxo por Forma de Pagamento:** **grande sobreposição com `payment_transactions`**
  (D-63 já capturou). ⭐ (redundante).

### H. Baixo valor / fora de escopo agora
Formulários/Anamneses, Feriados/Horários Especiais (→ `business_hours`/`time_off`),
Fornecedores/Fabricantes (só com Estoque).

---

## Parte 4 — Análise de aderência ao BarbeariaPro

### 4.1 Encaixa sem mudança de schema
- **Despesas** → `expense_categories` + `expenses` (existem, vazias). Encaixe perfeito.
- **Histórico de agendamentos** → `appointments`/`appointment_items`. Só precisa de
  **mapa de status** e **chave de dedup**.
- **Pacotes** → catálogo `membership_*` (existe).
- **Comissões/regime** → `Barber.work_model/monthly_cost/chair_rent` (D-57).

### 4.2 Novas tabelas recomendadas (molde analítico D-59/D-63: RLS, sem FK operacional, `source='trinks'`)
| Tabela nova | Para | Prioridade |
|---|---|---|
| `financial_monthly_summary` | DRE mensal (receita/despesa por tipo) | Alta |
| `products` (+ `suppliers`, `manufacturers`) | catálogo de produtos | Média |
| `stock_positions` + `stock_movements` | estoque e movimentação | Média |
| `client_credits` | crédito pré-pago (passivo) | Baixa |
| `professional_performance` / `service_performance` | só se **não** importar histórico A | Condicional |

### 4.3 Novos campos/relacionamentos recomendados
- **`clients.trinks_created_at`** (ou corrigir `created_at` na carga) — data real de
  cadastro (destrava coortes de aquisição).
- **`clients.gender`, `clients.cpf_hash`** — gênero (segmentação) e, no futuro, CPF
  **hasheado** (nunca em claro; LGPD).
- **Chave de idempotência para agendamentos** — `appointments.external_ref` (id/comanda
  Trinks) OU substituição de período (como `payment_transactions`).
- **`appointment_items.category` desnormalizada** (snapshot) — análise por categoria
  robusta a mudanças de catálogo.

### 4.4 Problemas de normalização / arquitetura a resolver
1. **Duas verdades de receita** — resolvido pela **Decisão 2** (topo): `appointments
   concluído` = operacional; `payment_transactions` = financeiro; nunca somar.
2. **`ServiceCategory` estreito demais** para salão completo → estender enum
   (depilação, maos_pes, sobrancelha, maquiagem) ou migrar categoria p/ tabela.
3. **De-para de serviços frágil** (`_SERVICE_MAP`, 12 nomes hardcoded) → não escala.
   Recomendo **importar o catálogo de Serviços do Trinks** e casar por nome normalizado
   + tabela de aliases.
4. **`Payment` vs `payment_transactions`.** O dashboard lê `Payment` (vazia) p/ o mix; o
   real está em `payment_transactions`. O dashboard deve passar a ler a analítica.

### 4.5 Compatibilidade com futuras importações (o que já está certo)
Padrão vigente **excelente**: parser puro + serviço idempotente + rota self-service +
CLI na VM + `source='trinks'` + RLS + PII minimizada. Recomendo **padronizar a
idempotência** e **reusar `_read_rows`** (o import de agendamentos tem cópia própria).

---

## Parte 5 — Proposta de novo Dashboard

Legenda: 🟢 já dá com o que temos · 🟡 precisa de 1 import · 🔴 import + modelagem nova.

### 5.1 Financeiro
| KPI | Fonte | Disp. |
|---|---|---|
| Receita / Despesa / **Resultado real** | `payment_transactions`/DRE + `expenses` | 🟡 |
| Faturamento bruto vs líquido (após taxa de cartão) | `payment_transactions.operator_discount_amount` | 🟢 |
| Mix de formas de pagamento | `payment_transactions.payment_type` | 🟢 |
| Recebíveis (a receber por data prevista) | `payment_transactions.expected_receipt_date` | 🟢 |
| Custo de cartão (R$ e %) | `payment_transactions` | 🟢 |
| Fechamento de caixa diário (série) | `cash_daily_closings` | 🟢 |
| **Resultado e margem por mês (DRE)** | `dre_monthly_lines` | 🟢 (prod; falta tela) |
| **Custo fixo × variável** | `dre_monthly_lines.subgroup` | 🟢 (prod) |
| **Despesa por categoria + folha real** | `dre_monthly_lines` (subgrupo `pessoal`) | 🟢 (prod; alinha D-57) |
| Evolução receita × despesa (~6 anos) | `dre_monthly_lines` | 🟢 (prod) |
| ~~Contas a receber (débitos em aberto)~~ | ~~`client_debts`~~ | 🗑️ **descartado** (fonte inválida, D-65) |

### 5.2 Retenção / Churn / Frequência / LTV
| KPI | Fonte | Disp. |
|---|---|---|
| Clientes ativos/risco/inativos | `client_loyalty.status` | 🟢 |
| **Churn** (inativos ÷ base) e taxa de retorno | `client_loyalty` | 🟢 |
| **Frequência** (visitas/cliente, intervalo médio) | `client_loyalty.visit_count` + histórico A | 🟢/🟡 |
| **LTV** (gasto acumulado, projeção) | `client_loyalty.total_spent` | 🟢 |
| Recência / segmentação **RFM** | `last_visit_at`+`visit_count`+`total_spent` | 🟢 |
| Coorte de aquisição por mês | `clients` + data real de cadastro | 🟡 |
| **CAC** | — | 🔴 (exige custo de marketing; **não vem do Trinks** — input manual) |

### 5.3 Operacional / Agenda / Produtividade
| KPI | Fonte | Disp. |
|---|---|---|
| Ticket médio (geral / barbeiro / serviço) | histórico A | 🟡 |
| Ocupação da agenda (real, histórica) | histórico A + `business_hours` | 🟡 |
| Produtividade por profissional | histórico A | 🟡 |
| Desempenho por serviço / categoria | histórico A + catálogo serviços | 🟡 |
| Taxa de no-show / cancelamento | histórico A (status) | 🟡 |
| Buracos / ociosidade (hoje e amanhã) | `management.agenda_gaps` (existe) | 🟢 |

### 5.4 Comparativos / Evolução / Preditivo / Alertas
| KPI | Fonte | Disp. |
|---|---|---|
| Evolução mensal (receita/resultado) | DRE | 🟡 |
| Comparativo YoY / MoM, sazonalidade | DRE + histórico A | 🟡 |
| Meta do mês vs realizado + **projeção** | `revenue_alerts` (existe) + baseline DRE | 🟡 (só falta tela) |
| Previsão de demanda / horários de pico | histórico A | 🟡 |
| **MRR e "cobre a folha?"** | `client_memberships` + `Barber.*` | 🟡 |
| Alertas: queda, cliente sumindo, estoque mínimo, conta a vencer | várias | 🟡/🔴 |

> **Reorganização de UX sugerida (sem inventar dado):** (1) card **"Reconciliação"**
> confrontando receita operacional (agendamentos) × recebido (pagamentos) × caixa;
> (2) trazer à tela os 3 "dados mortos" já calculados: **mix de pagamento**,
> **meta/projeção** e **no-shows/ociosidade de amanhã**.

---

## Parte 6 — Priorização e roadmap

**Esforço:** B ≤ ~2 dias · M ~3–5 dias · A > 1 semana.

| # | Funcionalidade | Origem | Esforço | Impacto | Prioridade |
|---|---|---|---|---|---|
| 1 | **Camada de leitura analítica** (`payment_transactions` + `cash_daily_closings`): bruto/líquido, mix, custo de cartão, caixa | Trinks (já imp.) | **B** | **Altíssimo** | **P0** |
| 2 | **Import do histórico de agendamentos** (`Finalizado→concluido`) — acende receita/ranking/serviços/ocupação | Trinks | M | **Altíssimo** | **P0** |
| 3 | **Import do catálogo de Serviços** (pré-req. de #2) + estender `ServiceCategory` | Trinks | B | Alto | **P0** |
| 4 | **Painel Retenção/Churn/LTV/RFM** sobre `client_loyalty` | Trinks (já imp.) | B | Alto | **P1** |
| 5 | **Import do DRE** (evolução mensal, YoY, resultado histórico) | Trinks | M | Alto | **P1** |
| 6 | **Import de Despesas** → `expenses` (torna "Resultado" real) | Trinks | M | Alto | **P1** |
| 7 | Corrigir `created_at`/data de cadastro + `nivel` de fidelidade | BarbeariaPro | B | Médio | **P1** |
| 8 | **Tela Meta vs Realizado + projeção** (`revenue_alerts` existe) | BarbeariaPro | B | Médio | **P2** |
| 9 | Trazer "dados mortos" à tela: mix de pagamento, no-shows, ociosidade de amanhã | BarbeariaPro | B | Médio | **P2** |
| 10 | Import de Comissões/regime → "Folha × Receita" com números reais | Trinks | M | Médio | **P2** |
| 11 | **Módulo Produtos + Estoque** (novas tabelas + import) | Trinks | A | Médio-Alto | **P3** |
| 12 | Import de Pacotes → base de receita recorrente | Trinks | M | Médio | **P3** |
| 13 | Confirmar/rodar import de Débitos + painel de contas a receber | Trinks | B | Médio | **P3** |
| 14 | Crédito do cliente, Gorjetas | Trinks | M | Baixo | **P4** |
| 15 | Card de **Reconciliação** (agendamentos × pagamentos × caixa) | Trinks | M | Alto (confiança) | **P2** |

### Roadmap faseado
- **Fase 1 — "Acender o que já temos" (P0):** #1 + #3 + #2. Dashboard sai de ~R$ 0 para
  **6 meses de receita/ranking/serviços/caixa/mix de pagamento reais**.
- **Fase 2 — "Cliente e Resultado" (P1):** #4 + #5 + #6 + #7.
- **Fase 3 — "Gestão preditiva" (P2):** #8 + #9 + #15 + #10.
- **Fase 4 — "Novos módulos" (P3+):** Estoque/Produtos, Pacotes, Débitos, Crédito.

---

## Fase 1 (P0) — plano de execução acordado (ainda NÃO implementado)

> Detalhamento do ponto de partida escolhido. **Nenhuma linha foi escrita.** Ordem de
> dependência: **3 → 2** (serviços antes de agendamentos) e **1** em paralelo.

### Passo 1 — Camada de leitura analítica (esforço B, sem migration)
- Novos endpoints **somente-leitura** (ex.: sob `financeiro`/`dashboard`) que agregam
  `payment_transactions` (bruto, líquido, taxa de operadora, mix por `payment_type`,
  recebíveis por `expected_receipt_date`) e `cash_daily_closings` (série de caixa).
- Cards novos no frontend consumindo esses endpoints (React Query, padrão do gestor).
- **Não** altera schema. Torna visível o que já está no banco (R$ 414k + 149 dias).

### Passo 2 — Import do catálogo de Serviços + `ServiceCategory` (esforço B)
- Novo parser/serviço para o export **Serviços** do Trinks (nome, categoria, preço,
  duração), no molde `trinks_*`.
- Estender `ServiceCategory` (ou migrar para tabela) para cobrir Depilação, Mãos e Pés,
  Sobrancelha, Maquiagem, Estética — **migration aditiva**.
- Substituir/expandir o `_SERVICE_MAP` por casamento por nome normalizado + aliases.

### Passo 3 — Import do histórico de agendamentos (esforço M)
- Ajustar `trinks_appointments.py`: (a) **mapa de status** real
  (`Finalizado→concluido`, `Cancelado→cancelado`, `Faltou→faltou`); (b) **idempotência**
  por chave externa (comanda/id Trinks em `external_ref`) **ou** substituição de período
  (molde `payment_transactions`) para reimportar sem duplicar.
- Rodar sobre o **export de histórico completo** (`Consultar Agendamentos`, período
  amplo), não só os futuros de julho.
- Resultado: `appointments concluído` populado → **todo o dashboard existente acende**
  (receita, ranking de barbeiros, top serviços, ticket, ocupação, picos, conversão).

### Formalização a fazer ao iniciar (documentação)
- Registrar em `DECISIONS.md` a **Decisão 2** (verdade da receita: operacional =
  agendamentos; financeiro = pagamentos; caixa = fechamento; nunca somar).
- Atualizar `CLAUDE.md §6` e `docs/TRINKS_IMPORT.md` com os novos imports.

### Riscos / pontos de atenção da Fase 1
- **Volume:** histórico multi-ano pode ter dezenas de milhares de agendamentos (o
  Dashboard do Trinks mostra ~4.767 agendamentos/semestre). Postgres aguenta; atenção à
  performance do import batch e do `display_number` sequencial.
- **De-para de serviços:** sem o catálogo real (Passo 2), muitas linhas cairiam em
  `skipped_no_service`. Por isso 2 vem antes de 3.
- **Reconciliação:** receita de agendamentos concluídos deve **bater aproximadamente**
  com `payment_transactions` no mesmo período — divergência é sinal de dado faltante,
  não de erro de soma (as fontes não se somam).
- **Datas/fuso:** manter a conversão local→UTC já existente no importador.
