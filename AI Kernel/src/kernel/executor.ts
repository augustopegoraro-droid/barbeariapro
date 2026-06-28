/**
 * kernel/executor.ts
 * -----------------------------------------------------------------------------
 * Task Executor — executa um passo do plano.
 *
 * Responsabilidades: retries, timeout, medição de custo/latência e emissão de
 * eventos. A compensação/rollback é coordenada pelo Workflow Engine.
 * -----------------------------------------------------------------------------
 */

import { AIRouter, PlanStep, RequestContext, StepResult } from '../types';
import { EventBus } from './eventBus';
import { AgentRegistry } from './registry';
import { now } from './util';

const MAX_RETRIES = 2;
const TIMEOUT_MS = 5000;

function comTimeout<T>(p: Promise<T>, ms: number): Promise<T> {
  return Promise.race([
    p,
    new Promise<T>((_, rej) => setTimeout(() => rej(new Error('timeout')), ms)),
  ]);
}

export class TaskExecutor {
  constructor(
    private registry: AgentRegistry,
    private ai: AIRouter,
    private bus: EventBus,
  ) {}

  async run(step: PlanStep, ctx: RequestContext): Promise<StepResult> {
    const correlationId = ctx.message.correlationId;
    const agent = this.registry.get(step.agent);
    const inicio = now();

    if (!agent) {
      const r: StepResult = {
        stepId: step.id, agent: step.agent, action: step.action,
        ok: false, error: `Agente não encontrado: ${step.agent}`,
        latencyMs: 0, retries: 0, costUsd: 0,
      };
      this.bus.emit('step.concluido', correlationId, { ...resumoEvento(r) });
      return r;
    }

    let retries = 0;
    let ultimoErro = '';
    while (retries <= MAX_RETRIES) {
      try {
        this.bus.emit('step.iniciado', correlationId, {
          agent: step.agent, action: step.action, tentativa: retries + 1,
        });
        const out = await comTimeout(
          agent.execute({
            step,
            context: ctx,
            ai: this.ai,
            emit: (type, payload) => this.bus.emit(type, correlationId, payload ?? {}),
          }),
          TIMEOUT_MS,
        );
        const r: StepResult = {
          stepId: step.id, agent: step.agent, action: step.action,
          ok: out.ok, output: out.output, reply: out.reply, error: out.error,
          latencyMs: now() - inicio, retries,
          modelUsed: out.modelUsed, costUsd: out.costUsd ?? 0,
          halt: out.halt,
        };
        this.bus.emit('step.concluido', correlationId, resumoEvento(r));
        if (out.ok) return r;
        ultimoErro = out.error ?? 'falha';
      } catch (e) {
        ultimoErro = (e as Error).message;
        this.bus.emit('step.erro', correlationId, { agent: step.agent, erro: ultimoErro });
      }
      retries++;
    }

    const r: StepResult = {
      stepId: step.id, agent: step.agent, action: step.action,
      ok: false, error: ultimoErro,
      latencyMs: now() - inicio, retries: retries - 1, costUsd: 0,
    };
    this.bus.emit('step.concluido', correlationId, resumoEvento(r));
    return r;
  }
}

function resumoEvento(r: StepResult): Record<string, unknown> {
  return {
    agent: r.agent, action: r.action, ok: r.ok,
    costUsd: r.costUsd, latencyMs: r.latencyMs, modelUsed: r.modelUsed,
  };
}
