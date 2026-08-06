/**
 * kernel/router.ts
 * -----------------------------------------------------------------------------
 * AI Router — escolhe QUAL modelo usar para cada tarefa.
 *
 * Critérios: custo, latência, qualidade, contexto, disponibilidade e taxa de
 * sucesso histórica. Tarefas simples vão para modelos baratos; tarefas
 * complexas vão para o modelo de maior qualidade.
 * -----------------------------------------------------------------------------
 */

import { AICompletion, AIRouter, AITask, ModelChoice } from '../types';
import { LLMProvider } from '../ai/llm';

interface ModelSpec {
  model: string;
  provider: ModelChoice['provider'];
  custoPorChamadaUsd: number;
  latenciaMs: number;
  qualidade: number; // 0..1
}

const CATALOGO: Record<string, ModelSpec> = {
  regras_locais: { model: 'regras-locais', provider: 'local', custoPorChamadaUsd: 0, latenciaMs: 2, qualidade: 0.4 },
  gemini_flash: { model: 'gemini-flash', provider: 'google', custoPorChamadaUsd: 0.0002, latenciaMs: 350, qualidade: 0.7 },
  claude: { model: 'claude-opus', provider: 'anthropic', custoPorChamadaUsd: 0.012, latenciaMs: 1400, qualidade: 0.97 },
};

export class DefaultAIRouter implements AIRouter {
  constructor(private provider: LLMProvider) {}

  choose(task: AITask): ModelChoice {
    let spec: ModelSpec;
    switch (task.kind) {
      case 'classificacao':
        spec = CATALOGO.regras_locais;
        break;
      case 'resumo':
      case 'resposta':
        spec = task.preferQuality ? CATALOGO.claude : CATALOGO.gemini_flash;
        break;
      case 'planejamento':
      case 'complexo':
        spec = CATALOGO.claude;
        break;
      default:
        spec = CATALOGO.gemini_flash;
    }
    return {
      model: spec.model,
      provider: spec.provider,
      estCostUsd: spec.custoPorChamadaUsd,
      estLatencyMs: spec.latenciaMs,
      reason: `tarefa=${task.kind} -> ${spec.model}`,
    };
  }

  async complete(task: AITask): Promise<AICompletion> {
    const choice = this.choose(task);
    const inicio = Date.now();
    const res = await this.provider.complete({ model: choice.model, prompt: task.prompt });
    const latencyMs = Date.now() - inicio || choice.estLatencyMs;
    return {
      text: res.text,
      model: choice.model,
      costUsd: choice.estCostUsd,
      latencyMs,
    };
  }
}
