/**
 * kernel/workflow.ts
 * -----------------------------------------------------------------------------
 * Workflow Engine — coordena tarefas compostas (vários agentes).
 *
 * Executa os passos respeitando dependências. Se um passo falhar, aciona a
 * compensação (rollback) dos passos compensáveis já executados — padrão saga.
 * -----------------------------------------------------------------------------
 */

import { ExecutionPlan, RequestContext, StepResult } from '../types';
import { EventBus } from './eventBus';
import { TaskExecutor } from './executor';
import { AgentRegistry } from './registry';

export interface WorkflowResult {
  ok: boolean;
  results: StepResult[];
  rolledBack: boolean;
}

export class WorkflowEngine {
  constructor(
    private executor: TaskExecutor,
    private registry: AgentRegistry,
    private bus: EventBus,
  ) {}

  async run(plan: ExecutionPlan, ctx: RequestContext): Promise<WorkflowResult> {
    const correlationId = ctx.message.correlationId;
    const concluidos = new Set<string>();
    const results: StepResult[] = [];
    const compensaveis: { stepId: string; agent: string }[] = [];

    // Resolve ordem por dependências (Kahn simplificado).
    const pendentes = [...plan.steps];
    while (pendentes.length > 0) {
      const prontos = pendentes.filter((s) => s.dependsOn.every((d) => concluidos.has(d)));
      if (prontos.length === 0) {
        this.bus.emit('workflow.deadlock', correlationId, {});
        break;
      }

      for (const step of prontos) {
        const r = await this.executor.run(step, ctx);
        results.push(r);
        concluidos.add(step.id);
        pendentes.splice(pendentes.indexOf(step), 1);

        if (r.ok && step.compensable) {
          compensaveis.push({ stepId: step.id, agent: step.agent });
        }

        // Pausa conversacional: o agente fez uma pergunta. Para sem rollback.
        if (r.ok && r.halt) {
          this.bus.emit('workflow.pausado', correlationId, { step: step.action });
          return { ok: true, results, rolledBack: false };
        }

        if (!r.ok) {
          // Falhou: desfaz o que já foi feito e aborta.
          await this.compensar(compensaveis, plan, ctx);
          this.bus.emit('workflow.falhou', correlationId, { step: step.action, erro: r.error });
          return { ok: false, results, rolledBack: compensaveis.length > 0 };
        }
      }
    }

    this.bus.emit('workflow.concluido', correlationId, { passos: results.length });
    return { ok: true, results, rolledBack: false };
  }

  private async compensar(
    compensaveis: { stepId: string; agent: string }[],
    plan: ExecutionPlan,
    ctx: RequestContext,
  ): Promise<void> {
    // Compensa na ordem inversa.
    for (const c of [...compensaveis].reverse()) {
      const agent = this.registry.get(c.agent);
      const step = plan.steps.find((s) => s.id === c.stepId);
      if (agent?.compensate && step) {
        try {
          await agent.compensate(step, ctx);
          this.bus.emit('step.compensado', ctx.message.correlationId, {
            agent: c.agent, action: step.action,
          });
        } catch (e) {
          this.bus.emit('step.compensacao_falhou', ctx.message.correlationId, {
            agent: c.agent, erro: (e as Error).message,
          });
        }
      }
    }
  }
}
