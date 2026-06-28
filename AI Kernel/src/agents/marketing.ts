/**
 * agents/marketing.ts
 * -----------------------------------------------------------------------------
 * Marketing Agent — campanhas, segmentação e automações.
 * O controle de autorização é feito no Policy Engine (antes de chegar aqui).
 * -----------------------------------------------------------------------------
 */

import { Infra } from '../infra/store';
import {
  Agent, AgentDescriptor, AgentExecuteInput, AgentExecuteOutput,
} from '../types';

export class MarketingAgent implements Agent {
  descriptor: AgentDescriptor = {
    name: 'MarketingAgent',
    description: 'Cria campanhas e segmenta clientes.',
    capabilities: [{ intent: 'campanha', description: 'Campanhas e segmentação' }],
    permissions: ['marketing:write'],
    tools: ['criarCampanha', 'segmentarClientes'],
    estimatedCostUsd: 0.0003,
    avgLatencyMs: 200,
    version: '1.0.0',
    health: 'healthy',
  };

  constructor(private infra: Infra) {}

  async execute(input: AgentExecuteInput): Promise<AgentExecuteOutput> {
    // Segmenta inativos (sem agendamento futuro) como exemplo.
    const todos = [...this.infra.db.customers.values()];
    const alvo = todos.filter((c) => !c.inadimplente);
    return {
      ok: true,
      output: { alcance: alvo.length },
      reply: `Campanha criada. Segmento "ativos não inadimplentes": ${alvo.length} clientes prontos para disparo.`,
      costUsd: this.descriptor.estimatedCostUsd,
    };
  }
}
