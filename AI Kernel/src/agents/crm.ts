/**
 * agents/crm.ts
 * -----------------------------------------------------------------------------
 * CRM Agent — clientes, histórico, oportunidades e observações.
 * -----------------------------------------------------------------------------
 */

import { Infra } from '../infra/store';
import {
  Agent, AgentDescriptor, AgentExecuteInput, AgentExecuteOutput,
} from '../types';
import { buscarCliente, historicoAgendamentos, registrarInteracao } from '../tools/crm.tools';

export class CrmAgent implements Agent {
  descriptor: AgentDescriptor = {
    name: 'CrmAgent',
    description: 'Gerencia clientes, histórico e observações.',
    capabilities: [{ intent: 'consultar_cliente', description: 'Consulta e registro de cliente' }],
    permissions: ['crm:read', 'crm:write'],
    tools: ['buscarCliente', 'registrarInteracao'],
    estimatedCostUsd: 0.0001,
    avgLatencyMs: 90,
    version: '1.0.0',
    health: 'healthy',
  };

  constructor(private infra: Infra) {}

  async execute(input: AgentExecuteInput): Promise<AgentExecuteOutput> {
    const { step, context } = input;
    const tipo = (step.input as { tipo?: string }).tipo;
    const cliente = buscarCliente(this.infra, context.customer?.id);

    // Quando faz parte de um workflow (agendamento/remarcação), só registra.
    if (tipo && tipo !== 'consulta') {
      if (cliente) registrarInteracao(this.infra, cliente.id, `Interação: ${tipo}`);
      return { ok: true, output: { registrado: Boolean(cliente) }, costUsd: this.descriptor.estimatedCostUsd };
    }

    // Consulta direta do cliente.
    if (!cliente) {
      return { ok: true, reply: 'Não encontrei seu cadastro. Quer que eu crie um agora?', halt: true };
    }
    const visitas = historicoAgendamentos(this.infra, cliente.id);
    const obs = cliente.notes.slice(-2).join(' | ') || 'sem observações';
    return {
      ok: true,
      output: { cliente: cliente.id, visitas },
      reply: `Cadastro: ${cliente.name}${cliente.vip ? ' (VIP)' : ''}. Atendimentos: ${visitas}. Notas: ${obs}.`,
      costUsd: this.descriptor.estimatedCostUsd,
    };
  }
}
