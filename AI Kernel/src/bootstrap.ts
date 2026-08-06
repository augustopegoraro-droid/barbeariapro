/**
 * bootstrap.ts
 * -----------------------------------------------------------------------------
 * Composição da raiz: instancia e conecta todos os componentes.
 *
 * Adicionar um novo agente NÃO exige tocar no Kernel — basta registrá-lo aqui.
 * -----------------------------------------------------------------------------
 */

import * as path from 'path';
import { Infra } from './infra/store';
import { seed } from './infra/seed';
import { EventBus } from './kernel/eventBus';
import { MetricsEngine } from './kernel/metrics';
import { DefaultAIRouter } from './kernel/router';
import { AgentRegistry } from './kernel/registry';
import { loadAgentCards, applyCardsToRegistry } from './kernel/cards';
import { Kernel } from './kernel/kernel';
import { MockLLM } from './ai/llm';

import { AgendaAgent } from './agents/agenda';
import { FinanceAgent } from './agents/finance';
import { CrmAgent } from './agents/crm';
import { MarketingAgent } from './agents/marketing';
import { CaixaAgent } from './agents/caixa';
import { CobrancaAgent } from './agents/cobranca';
import { EstoqueAgent } from './agents/estoque';
import { MembershipAgent } from './agents/membership';

export interface System {
  kernel: Kernel;
  metrics: MetricsEngine;
  bus: EventBus;
  infra: Infra;
  registry: AgentRegistry;
}

export function bootstrap(): System {
  const infra = new Infra();
  seed(infra);

  const bus = new EventBus();
  const metrics = new MetricsEngine(bus);
  const ai = new DefaultAIRouter(new MockLLM());
  const registry = new AgentRegistry();

  // Registro de agentes especializados (descoberta via Registry).
  // Voltados ao cliente final (bot):
  registry.register(new AgendaAgent(infra));
  registry.register(new FinanceAgent(infra));
  registry.register(new CrmAgent(infra));
  registry.register(new MarketingAgent(infra));
  // Operacionais (painel interno — Raquel/gestora):
  registry.register(new CaixaAgent(infra));
  registry.register(new CobrancaAgent(infra));
  registry.register(new EstoqueAgent(infra));
  // Pacotes / Fidelidade / Assinaturas (cliente final):
  registry.register(new MembershipAgent(infra));

  // Agent cards: o descriptor publicado por cada agente vem do vault de
  // conhecimento (knowledge/agents/*.md) — markdown editável é a fonte de verdade.
  const cards = loadAgentCards(path.join(__dirname, '..', 'knowledge', 'agents'));
  applyCardsToRegistry(registry, cards);

  const kernel = new Kernel({ infra, bus, metrics, ai, registry });

  return { kernel, metrics, bus, infra, registry };
}
