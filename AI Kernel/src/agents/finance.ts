/**
 * agents/finance.ts
 * -----------------------------------------------------------------------------
 * Finance Agent — responsável APENAS por PIX, cobrança, caixa e faturamento.
 * -----------------------------------------------------------------------------
 */

import { Infra } from '../infra/store';
import {
  Agent, AgentDescriptor, AgentExecuteInput, AgentExecuteOutput, PlanStep, RequestContext,
} from '../types';
import { brl } from '../kernel/util';
import { cancelarCobranca, cobrancaPendente, emitirPix } from '../tools/finance.tools';
import { proximoAgendamento } from '../tools/agenda.tools';
import { resolverServico } from '../tools/agenda.tools';

export class FinanceAgent implements Agent {
  descriptor: AgentDescriptor = {
    name: 'FinanceAgent',
    description: 'Gera PIX, controla cobranças e faturamento.',
    capabilities: [{ intent: 'pagar', description: 'PIX e cobranças' }],
    permissions: ['financeiro:read', 'financeiro:write'],
    tools: ['emitirPix', 'cancelarCobranca'],
    estimatedCostUsd: 0.0002,
    avgLatencyMs: 150,
    version: '1.0.0',
    health: 'healthy',
  };

  private pixPorStep = new Map<string, string>();

  constructor(private infra: Infra) {}

  async execute(input: AgentExecuteInput): Promise<AgentExecuteOutput> {
    const { step, context } = input;
    const args = step.input as { operacao?: string; servico?: string };

    if (args.operacao === 'cancelar_cobranca') {
      return this.cancelar(context);
    }
    return this.gerar(step, context, args.servico);
  }

  private gerar(step: PlanStep, ctx: RequestContext, servicoArg?: string): AgentExecuteOutput {
    if (!ctx.customer) {
      return { ok: true, reply: 'Para gerar o PIX preciso identificar seu cadastro. Qual seu nome?', halt: true };
    }

    // Reaproveita cobrança pendente, se existir.
    const pendente = cobrancaPendente(this.infra, ctx.customer.id);
    if (pendente) {
      return {
        ok: true,
        output: { paymentId: pendente.id, valor: pendente.amountBrl },
        reply: `Você tem um PIX em aberto de ${brl(pendente.amountBrl)}.\nCopia e cola: ${pendente.pixCode}`,
        costUsd: this.descriptor.estimatedCostUsd,
      };
    }

    const servico = resolverServico(this.infra, servicoArg);
    const proximo = proximoAgendamento(this.infra, ctx.customer.id);
    const pay = emitirPix(this.infra, {
      customerId: ctx.customer.id,
      service: servico,
      appointmentId: proximo?.id,
    });
    this.pixPorStep.set(step.id, pay.id);

    return {
      ok: true,
      output: { paymentId: pay.id, valor: pay.amountBrl },
      reply: `PIX de ${brl(pay.amountBrl)} gerado (${servico.name}).\nCopia e cola: ${pay.pixCode}`,
      costUsd: this.descriptor.estimatedCostUsd,
    };
  }

  private cancelar(ctx: RequestContext): AgentExecuteOutput {
    if (!ctx.customer) return { ok: true, reply: '', halt: false };
    const proximo = proximoAgendamento(this.infra, ctx.customer.id);
    const cancelada = proximo ? cancelarCobranca(this.infra, proximo.id) : undefined;
    return {
      ok: true,
      output: { cancelada: Boolean(cancelada) },
      reply: cancelada ? 'A cobrança pendente do atendimento foi cancelada.' : '',
      costUsd: this.descriptor.estimatedCostUsd,
    };
  }

  /** Compensação: cancela o PIX gerado neste step. */
  async compensate(step: PlanStep): Promise<void> {
    const payId = this.pixPorStep.get(step.id);
    if (payId) {
      const p = this.infra.db.payments.get(payId);
      if (p) {
        p.status = 'cancelado';
        this.infra.db.payments.set(p.id, p);
      }
    }
  }
}
