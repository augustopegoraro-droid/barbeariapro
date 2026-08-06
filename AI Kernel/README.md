# BarbeariaPro — Sistema Operacional de IA (AI Kernel)

Implementação executável do **AI Kernel** aplicada a uma barbearia. O Kernel é
um núcleo de orquestração que coordena agentes de IA, modelos, ferramentas,
pessoas e fluxos — **sem conter regra de negócio**. Toda a lógica do negócio
vive nos agentes especializados; o Kernel só recebe, entende, planeja, delega,
acompanha, mede e responde.

Roda **100% offline, sem dependências externas em runtime** (Redis, Postgres,
banco vetorial e LLM são simulados em memória atrás de interfaces). Trocar
qualquer um por uma implementação real não muda o núcleo.

---

## Como rodar

```bash
npm install      # instala typescript, ts-node e @types/node (devDeps)
npm run demo     # executa a demonstração com 9 conversas reais
npm run typecheck
```

A demo simula conversas de WhatsApp/painel e imprime, para cada uma, a resposta,
a **trilha de auditoria** (todos os eventos internos) e, ao final, as métricas
globais (custo, latência, uso por agente/intenção).

---

## O que a demo demonstra

1. Cliente VIP consulta horários (prioridade aplicada pela Policy Engine).
2. Agendamento completo orquestrando **3 agentes** (Agenda → Finance → CRM) com
   dependências entre passos.
3. Cliente inadimplente é **bloqueado** ao tentar agendar (regra determinística).
4. O mesmo cliente **pode** pedir o PIX para regularizar (a mesma regra permite).
5. Dúvida respondida com **conhecimento de longo prazo** (busca vetorial).
6. Cliente irritado → **handoff humano** automático (por sentimento).
7. Operador devolve a conversa: a **IA retoma** e remarca.
8. Campanha disparada pelo painel interno (canal autorizado).
9. Campanha negada para cliente comum (não autorizado).

---

## Arquitetura

```
            Canais (WhatsApp, site, app, API, Instagram...)
                              │
                          ┌───▼────┐
                          │ Gateway│  normaliza qualquer canal
                          └───┬────┘
   ┌──────────────────────────▼───────────────────────────┐
   │                       AI KERNEL                       │
   │                                                       │
   │  Intent → Context → Policy → Discovery → Planner →    │
   │  Workflow → Task Executor                             │
   │                                                       │
   │  Transversais: Memory · AI Router · Event Bus ·       │
   │                Metrics · Human Handoff                │
   └───────────────┬───────────────────────┬──────────────┘
                   │ delega via Registry    │ eventos
        ┌──────────▼──────────┐      ┌──────▼───────┐
        │  Agentes            │      │ Event Bus →  │
        │  Agenda · Finance · │      │ Metrics      │
        │  CRM · Marketing    │      │ (auditoria)  │
        └──────────┬──────────┘      └──────────────┘
                   │ usam
            ┌──────▼───────┐
            │ Ferramentas  │ (PIX, agenda, CRM, notificação)
            └──────┬───────┘
                   │
       Infra simulada: Curto prazo (Redis) · Estruturado (Postgres) ·
                       Longo prazo (Vetorial)
```

---

## Mapa: especificação → implementação

| Componente do spec      | Arquivo                          | Papel |
|-------------------------|----------------------------------|-------|
| Gateway                 | `kernel/gateway.ts`              | Normaliza qualquer canal em `InboundMessage` |
| Intent Classifier       | `kernel/intent.ts`               | Regras leves primeiro; LLM só em baixa confiança |
| Context Builder         | `kernel/context.ts`              | Monta o contexto mínimo necessário |
| Policy Engine           | `kernel/policy.ts`               | Regras **determinísticas** (VIP, inadimplência, autorização, handoff) |
| Agent Registry          | `kernel/registry.ts`             | Catálogo de agentes; o Kernel nunca os conhece direto |
| Capability Discovery    | `kernel/discovery.ts`            | Acha o melhor agente para a intenção (usa métricas) |
| Planner                 | `kernel/planner.ts`              | Transforma a solicitação em plano multi-agente |
| Workflow Engine         | `kernel/workflow.ts`             | Executa por dependências; **rollback/saga** em falha |
| Task Executor           | `kernel/executor.ts`             | Retries, timeout, custo/latência por passo |
| Memory Engine           | `kernel/memory.ts`               | Curto (Redis) / Estruturado (PG) / Longo (vetorial) |
| AI Router               | `kernel/router.ts`               | Escolhe o modelo por custo/latência/qualidade |
| Event Bus               | `kernel/eventBus.ts`             | Toda ação vira evento → auditoria |
| Metrics Engine          | `kernel/metrics.ts`              | Custo, latência, sucesso, uso por agente/modelo |
| Human Handoff           | `kernel/kernel.ts`               | Transfere ao humano e permite a IA retomar |
| Orquestrador (Kernel)   | `kernel/kernel.ts`               | Costura todo o fluxo |
| Agentes especializados  | `agents/*.ts`                    | Agenda, Finance, CRM, Marketing |
| Ferramentas             | `tools/*.ts`                     | PIX, agenda, CRM, notificação |
| Infra (3 camadas + LLM) | `infra/store.ts`, `ai/llm.ts`    | Simulações atrás de interface |

---

## Princípios respeitados

- **Responsabilidade única**: cada agente cuida do seu domínio (Agenda nunca
  toca no financeiro, etc.).
- **Auditabilidade**: tudo passa pelo Event Bus; cada requisição tem trilha.
- **IA não substitui regra determinística**: prioridade, bloqueios e
  autorizações vivem na Policy Engine.
- **Humano assume quando necessário** e a IA pode retomar depois.
- **Extensível sem tocar no Kernel**: novo agente = registrar no `bootstrap.ts`.
- **Multi-modelo**: o AI Router troca de modelo por tarefa; o adaptador real
  (Claude/Gemini) está esquematizado em `ai/llm.ts`.
- **Desacoplado e testável**: tudo conversa por interfaces.

---

## Como estender

**Adicionar um agente novo** (ex.: `EstoqueAgent`):

1. Crie `src/agents/estoque.ts` implementando a interface `Agent`
   (descriptor + `execute`, e `compensate` se precisar de rollback).
2. Declare as capacidades no `descriptor.capabilities`.
3. Registre em `bootstrap.ts`: `registry.register(new EstoqueAgent(infra))`.
4. Se a intenção for nova, acrescente o template no `Planner`.

O Kernel não muda.

**Plugar um LLM real**: implemente/instancie `RealLLM` em `ai/llm.ts` com suas
chaves e troque o `MockLLM` no `bootstrap.ts`. O contrato é o mesmo para Claude
e Gemini.

**Plugar infra real**: implemente `ShortTermStore` (Redis), `StructuredStore`
(Postgres) e `VectorStore` (pgvector/Qdrant) com as mesmas interfaces de
`infra/store.ts`.

---

## Estrutura

```
src/
  index.ts            Demonstração (9 conversas)
  bootstrap.ts        Composição da raiz (liga tudo, registra agentes)
  types.ts            Contratos centrais
  kernel/             Os 13 componentes do núcleo + orquestrador
  agents/             Agenda, Finance, CRM, Marketing
  tools/              Ferramentas (PIX, agenda, CRM, notificação)
  infra/              Memória em 3 camadas + dados de exemplo (seed)
  ai/                 Provedores de LLM (mock + esqueleto real)
```
