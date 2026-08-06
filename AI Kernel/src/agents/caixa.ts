/**
 * agents/caixa.ts
 * -----------------------------------------------------------------------------
 * Caixa Agent — operacional (recepção). Abre, movimenta, confere e fecha o
 * caixa do dia. Não cria cobranças (isso é da [[finance-agent]]); apenas
 * controla o dinheiro em espécie e a conferência.
 * -----------------------------------------------------------------------------
 */

import { Infra } from '../infra/store';
import {
  Agent, AgentDescriptor, AgentExecuteInput, AgentExecuteOutput, CashMovementType,
} from '../types';
import { brl } from '../kernel/util';
import {
  abrirCaixa, fecharCaixa, registrarMovimento, resumoCaixa,
} from '../tools/caixa.tools';

export class CaixaAgent implements Agent {
  descriptor: AgentDescriptor = {
    name: 'CaixaAgent',
    description: 'Abre, movimenta, confere e fecha o caixa.',
    capabilities: [
      { intent: 'abrir_caixa', description: 'Abrir o caixa do dia com fundo de troco' },
      { intent: 'movimentar_caixa', description: 'Registrar sangria ou suprimento' },
      { intent: 'consultar_caixa', description: 'Saldo e movimentos do caixa' },
      { intent: 'fechar_caixa', description: 'Conferir e fechar o caixa' },
    ],
    permissions: ['caixa:read', 'caixa:write', 'financeiro:read'],
    tools: ['abrirCaixa', 'registrarMovimento', 'resumoCaixa', 'fecharCaixa'],
    estimatedCostUsd: 0.0001,
    avgLatencyMs: 80,
    version: '1.0.0',
    health: 'healthy',
  };

  constructor(private infra: Infra) {}

  async execute(input: AgentExecuteInput): Promise<AgentExecuteOutput> {
    const { step } = input;
    const args = step.input as { operador?: string; valor?: string; mov?: string };
    const valor = args.valor != null ? Number(args.valor) : NaN;

    switch (step.action) {
      case 'abrir_caixa': {
        const r = abrirCaixa(this.infra, {
          operador: args.operador ?? 'recepcao',
          fundo: Number.isFinite(valor) ? valor : 0,
        });
        if (!r.ok) return this.fail(r.erro!);
        return this.ok(`Caixa aberto com fundo de ${brl(r.session!.openingFloatBrl)}. Bom trabalho! 💈`);
      }

      case 'movimentar_caixa': {
        const tipo = (args.mov === 'suprimento' ? 'suprimento' : 'sangria') as CashMovementType;
        if (!Number.isFinite(valor)) return this.ok('Qual o valor da movimentação?', true);
        const r = registrarMovimento(this.infra, {
          tipo,
          valor,
          motivo: tipo === 'sangria' ? 'retirada' : 'reforço',
        });
        if (!r.ok) return this.fail(r.erro!);
        const rotulo = tipo === 'sangria' ? 'Sangria' : 'Suprimento';
        return this.ok(`${rotulo} de ${brl(valor)} no caixa. Saldo em caixa: ${brl(r.saldo!)}.`);
      }

      case 'consultar_caixa': {
        const r = resumoCaixa(this.infra);
        if (!r.ok) return this.fail(r.erro!);
        const s = r.session!;
        const linhas = s.movements
          .map((m) => `  • ${m.type}: ${brl(m.amountBrl)}${m.reason ? ` (${m.reason})` : ''}`)
          .join('\n');
        return this.ok(
          `Caixa aberto desde ${new Date(s.openedAt).toLocaleTimeString('pt-BR')}.\n${linhas}\nSaldo esperado: ${brl(r.saldo!)}.`,
        );
      }

      case 'fechar_caixa': {
        if (!Number.isFinite(valor)) return this.ok('Quanto deu na contagem para eu fechar o caixa?', true);
        const r = fecharCaixa(this.infra, { contado: valor });
        if (!r.ok) return this.fail(r.erro!);
        const dif = r.diferenca!;
        const status =
          dif === 0 ? 'bateu certinho ✅' : dif > 0 ? `sobra de ${brl(dif)}` : `falta de ${brl(-dif)}`;
        return this.ok(
          `Caixa fechado. Esperado ${brl(r.esperado!)}, contado ${brl(r.contado!)} — ${status}.`,
        );
      }

      default:
        return this.fail(`Ação desconhecida: ${step.action}`);
    }
  }

  private ok(reply: string, halt = false): AgentExecuteOutput {
    return { ok: true, reply, halt, costUsd: this.descriptor.estimatedCostUsd };
  }

  private fail(reply: string): AgentExecuteOutput {
    return { ok: true, reply, costUsd: this.descriptor.estimatedCostUsd };
  }
}
