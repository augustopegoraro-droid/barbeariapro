/**
 * agents/cobranca.ts
 * -----------------------------------------------------------------------------
 * Cobrança & Relacionamento Agent — operacional (recepção). Identifica
 * inadimplentes, clientes inativos e agendamentos de amanhã, e dispara as
 * mensagens. NÃO cria cobranças (isso é da [[finance-agent]]); reaproveita os
 * PIX já pendentes e envia a comunicação.
 * -----------------------------------------------------------------------------
 */

import { Infra } from '../infra/store';
import {
  Agent, AgentDescriptor, AgentExecuteInput, AgentExecuteOutput,
} from '../types';
import { brl, fmtData } from '../kernel/util';
import {
  agendamentosDeAmanha, clientesInativos, enviarMensagem, listarInadimplentes,
} from '../tools/relacionamento.tools';

export class CobrancaAgent implements Agent {
  descriptor: AgentDescriptor = {
    name: 'CobrancaAgent',
    description: 'Cobra inadimplentes, reativa clientes sumidos e envia lembretes.',
    capabilities: [
      { intent: 'cobrar_inadimplentes', description: 'Listar e cobrar quem está devendo' },
      { intent: 'reativar_clientes', description: 'Trazer de volta clientes inativos' },
      { intent: 'enviar_lembretes', description: 'Lembrar os agendamentos de amanhã' },
    ],
    permissions: ['financeiro:read', 'crm:read', 'notificacao:write'],
    tools: ['listarInadimplentes', 'clientesInativos', 'agendamentosDeAmanha', 'enviarMensagem'],
    estimatedCostUsd: 0.0002,
    avgLatencyMs: 140,
    version: '1.0.0',
    health: 'healthy',
  };

  constructor(private infra: Infra) {}

  async execute(input: AgentExecuteInput): Promise<AgentExecuteOutput> {
    switch (input.step.action) {
      case 'cobrar_inadimplentes':
        return this.cobrar();
      case 'reativar_clientes':
        return this.reativar();
      case 'enviar_lembretes':
        return this.lembrar();
      default:
        return this.reply(`Ação desconhecida: ${input.step.action}`);
    }
  }

  private cobrar(): AgentExecuteOutput {
    const lista = listarInadimplentes(this.infra);
    if (lista.length === 0) return this.reply('Nenhum inadimplente no momento. 🎉');

    let total = 0;
    const linhas = lista.map(({ customer, pendente }) => {
      const valor = pendente?.amountBrl ?? 0;
      total += valor;
      enviarMensagem(
        this.infra,
        customer.phone,
        `Olá ${customer.name.split(' ')[0]}, consta um PIX em aberto de ${brl(valor)}. ${pendente?.pixCode ?? ''}`,
      );
      return `  • ${customer.name}: ${brl(valor)}`;
    });
    return this.reply(
      `Cobrança enviada para ${lista.length} cliente(s) — total ${brl(total)}:\n${linhas.join('\n')}`,
    );
  }

  private reativar(): AgentExecuteOutput {
    const inativos = clientesInativos(this.infra, 30);
    if (inativos.length === 0) return this.reply('Nenhum cliente inativo há mais de 30 dias.');

    for (const c of inativos) {
      enviarMensagem(
        this.infra,
        c.phone,
        `Oi ${c.name.split(' ')[0]}! Sentimos sua falta na Taylor & Thedy. Que tal agendar um corte? 💈`,
      );
    }
    const nomes = inativos.map((c) => c.name).join(', ');
    return this.reply(`Reativação enviada para ${inativos.length} cliente(s): ${nomes}.`);
  }

  private lembrar(): AgentExecuteOutput {
    const amanha = agendamentosDeAmanha(this.infra);
    if (amanha.length === 0) return this.reply('Não há agendamentos para amanhã.');

    const linhas = amanha.map(({ appt, customer, barber }) => {
      enviarMensagem(
        this.infra,
        customer?.phone ?? '',
        `Lembrete: seu horário é ${fmtData(appt.start)} com ${barber?.name ?? 'a equipe'}.`,
      );
      return `  • ${fmtData(appt.start)} — ${customer?.name ?? '??'} com ${barber?.name ?? '??'}`;
    });
    return this.reply(`Lembretes enviados para amanhã (${amanha.length}):\n${linhas.join('\n')}`);
  }

  private reply(reply: string): AgentExecuteOutput {
    return { ok: true, reply, costUsd: this.descriptor.estimatedCostUsd };
  }
}
