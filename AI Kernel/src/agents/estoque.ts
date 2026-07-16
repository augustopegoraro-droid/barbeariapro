/**
 * agents/estoque.ts
 * -----------------------------------------------------------------------------
 * Estoque Agent — operacional (recepção). Consulta estoque baixo, dá baixa de
 * consumo no atendimento e registra reposição.
 * -----------------------------------------------------------------------------
 */

import { Infra } from '../infra/store';
import {
  Agent, AgentDescriptor, AgentExecuteInput, AgentExecuteOutput,
} from '../types';
import { estoqueBaixo, listarProdutos, registrarConsumo, reporEstoque } from '../tools/estoque.tools';

export class EstoqueAgent implements Agent {
  descriptor: AgentDescriptor = {
    name: 'EstoqueAgent',
    description: 'Controla produtos: estoque baixo, consumo e reposição.',
    capabilities: [
      { intent: 'consultar_estoque', description: 'Listar produtos e itens em falta' },
      { intent: 'registrar_consumo', description: 'Dar baixa de produto usado no atendimento' },
      { intent: 'repor_estoque', description: 'Registrar entrada/reposição de produto' },
    ],
    permissions: ['estoque:read', 'estoque:write'],
    tools: ['listarProdutos', 'estoqueBaixo', 'registrarConsumo', 'reporEstoque'],
    estimatedCostUsd: 0.0001,
    avgLatencyMs: 80,
    version: '1.0.0',
    health: 'healthy',
  };

  constructor(private infra: Infra) {}

  async execute(input: AgentExecuteInput): Promise<AgentExecuteOutput> {
    const { step } = input;
    const args = step.input as { produto?: string; qtd?: string };
    const qtd = args.qtd != null ? Number(args.qtd) : NaN;

    switch (step.action) {
      case 'consultar_estoque': {
        const baixos = estoqueBaixo(this.infra);
        if (baixos.length === 0) {
          const total = listarProdutos(this.infra).length;
          return this.reply(`Estoque ok — nenhum dos ${total} produtos abaixo do mínimo. 👍`);
        }
        const linhas = baixos
          .map((p) => `  ⚠️ ${p.name}: ${p.stockQty} ${p.unit} (mínimo ${p.minQty})`)
          .join('\n');
        return this.reply(`Produtos para repor (${baixos.length}):\n${linhas}`);
      }

      case 'registrar_consumo': {
        if (!Number.isFinite(qtd)) return this.reply('Quantas unidades foram usadas?', true);
        const r = registrarConsumo(this.infra, { termo: args.produto, qtd });
        if (!r.ok) return this.reply(r.erro!);
        const alerta = r.alerta ? ` ⚠️ atingiu o mínimo (${r.produto!.minQty}) — hora de repor.` : '';
        return this.reply(`Baixa de ${qtd} ${r.produto!.unit} de ${r.produto!.name}. Restam ${r.restante}.${alerta}`);
      }

      case 'repor_estoque': {
        if (!Number.isFinite(qtd)) return this.reply('Qual a quantidade que chegou?', true);
        const r = reporEstoque(this.infra, { termo: args.produto, qtd });
        if (!r.ok) return this.reply(r.erro!);
        return this.reply(`Reposição de ${qtd} ${r.produto!.unit} de ${r.produto!.name}. Total agora: ${r.total}.`);
      }

      default:
        return this.reply(`Ação desconhecida: ${step.action}`);
    }
  }

  private reply(reply: string, halt = false): AgentExecuteOutput {
    return { ok: true, reply, halt, costUsd: this.descriptor.estimatedCostUsd };
  }
}
