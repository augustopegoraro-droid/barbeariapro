# Knowledge — vault do AI Kernel

Base de conhecimento **editável por humano** e **lida pelo Kernel**. Abra esta
pasta como vault no Obsidian: o graph view mostra como os agentes se conectam e
os `[[wikilinks]]` viram navegação.

Princípio: este vault é a **camada de autoria** (partitura). O Kernel parseia
markdown puro (frontmatter + corpo) — não depende do app Obsidian em runtime.

## Agent cards

Cada agente publica seu descriptor (capacidades, permissões, ferramentas, custo,
latência, versão, saúde) no frontmatter de um card. O `AgentRegistry` carrega
esses cards no bootstrap; **o card é a fonte de verdade** e vence o descriptor
hardcoded no código (que vira fallback + alvo de detecção de drift).

**Cliente final (bot):**

- [[agenda-agent]] — horários e agendamentos (+ reagendamento em massa)
- [[finance-agent]] — PIX, cobranças e faturamento
- [[crm-agent]] — clientes, histórico e observações
- [[marketing-agent]] — campanhas e segmentação
- [[membership-agent]] — pacotes, fidelidade (pontos) e assinaturas

**Operacionais (painel interno — Raquel/gestora):**

- [[caixa-agent]] — abrir/fechar/movimentar o caixa
- [[cobranca-agent]] — inadimplentes, reativação e lembretes
- [[estoque-agent]] — estoque baixo, consumo e reposição

> Ações operacionais são **restritas ao operador interno** (canal `api`) pela
> Policy Engine — um cliente no WhatsApp nunca abre caixa nem dá baixa.

## Como o Kernel consome

```
knowledge/agents/*.md  ──loadAgentCards()──►  AgentDescriptor[]
                       ──applyCardsToRegistry()──►  AgentRegistry
```

Inspecionar os cards carregados: `npm run cards`.

## Próximo passo (não implementado)

As notas de conhecimento (FAQ, políticas, scripts da Raquel) podem virar a fonte
da **memória de longo prazo** do `MemoryEngine`: `nota .md → chunk → embed →
busca vetorial`. Hoje o vetorial está simulado em `infra/seed.ts`.
