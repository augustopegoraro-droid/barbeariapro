/**
 * kernel/kernel.ts
 * -----------------------------------------------------------------------------
 * AI Kernel — o núcleo de orquestração.
 *
 * O Kernel NÃO executa regra de negócio. Ele: recebe -> entende a intenção ->
 * monta contexto -> aplica políticas -> planeja -> seleciona agentes ->
 * acompanha a execução -> registra métricas -> devolve a resposta.
 *
 * Também decide quando envolver um humano (handoff) e permite que a IA retome
 * a conversa depois.
 * -----------------------------------------------------------------------------
 */

import { Infra } from '../infra/store';
import { AIRouter, Intent, KernelResponse, RequestContext, StepResult } from '../types';
import { ContextBuilder } from './context';
import { CapabilityDiscovery } from './discovery';
import { EventBus } from './eventBus';
import { Gateway, RawInput } from './gateway';
import { IntentClassifier } from './intent';
import { MemoryEngine } from './memory';
import { MetricsEngine } from './metrics';
import { Planner } from './planner';
import { PolicyEngine } from './policy';
import { AgentRegistry } from './registry';
import { TaskExecutor } from './executor';
import { WorkflowEngine } from './workflow';

/**
 * Ação aguardando o próximo turno do cliente. O Kernel guarda apenas QUEM (agent)
 * é dono e um payload OPACO (data) — a interpretação é delegada ao agente
 * (agent.resume), mantendo o núcleo livre de regra de negócio.
 */
interface PendingAction {
  agent: string;
  data: unknown;
}

interface ConversationState {
  handoffAtivo: boolean;
  pending?: PendingAction;
}

export interface KernelDeps {
  infra: Infra;
  bus: EventBus;
  metrics: MetricsEngine;
  ai: AIRouter;
  registry: AgentRegistry;
}

export class Kernel {
  private gateway = new Gateway();
  private intent: IntentClassifier;
  private context: ContextBuilder;
  private policy = new PolicyEngine();
  private discovery: CapabilityDiscovery;
  private planner = new Planner();
  private workflow: WorkflowEngine;
  private memory: MemoryEngine;
  private estados = new Map<string, ConversationState>();

  constructor(private deps: KernelDeps) {
    this.memory = new MemoryEngine(deps.infra);
    this.intent = new IntentClassifier(deps.ai);
    this.context = new ContextBuilder(deps.infra, this.memory);
    this.discovery = new CapabilityDiscovery(deps.registry, deps.metrics);
    const executor = new TaskExecutor(deps.registry, deps.ai, deps.bus);
    this.workflow = new WorkflowEngine(executor, deps.registry, deps.bus);
  }

  /** O operador humano devolve a conversa para a IA. */
  retomarIA(customerRef: string): void {
    const st = this.estados.get(customerRef);
    if (st) st.handoffAtivo = false;
  }

  async handle(raw: RawInput): Promise<KernelResponse> {
    const t0 = Date.now();
    const msg = this.gateway.normalizar(raw);
    const cid = msg.correlationId;
    const bus = this.deps.bus;

    bus.emit('requisicao.iniciada', cid, { canal: msg.channel, texto: msg.text });
    this.memory.registrar(msg.customerRef, 'customer', msg.text);

    const estado = this.estados.get(msg.customerRef) ?? { handoffAtivo: false };
    this.estados.set(msg.customerRef, estado);

    // Se um humano está conduzindo, a IA não responde (apenas registra).
    if (estado.handoffAtivo) {
      bus.emit('handoff.em_andamento', cid, {});
      return this.responder(cid, msg.customerRef, 'Um atendente humano está cuidando do seu caso. 👤', {
        handoff: true, handoffReason: 'atendimento humano em andamento', ok: true, steps: [], t0,
      });
    }

    // 1) Intenção — se há uma ação pendente, o AGENTE dono interpreta a resposta
    // (multi-turn). O Kernel só roteia; nenhuma regra de domínio vive aqui.
    let intent: Intent;
    if (estado.pending) {
      const dono = this.deps.registry.get(estado.pending.agent);
      const outcome = dono?.resume?.(estado.pending.data, msg.text);
      if (outcome === 'cancelado') {
        estado.pending = undefined;
        return this.responder(cid, msg.customerRef, 'Tudo bem, deixei isso de lado. 🙂', {
          handoff: false, ok: true, steps: [], t0,
        });
      }
      if (outcome && typeof outcome === 'object' && 'name' in outcome) {
        estado.pending = undefined; // o agente resolveu a continuação
        intent = outcome;
      } else {
        // resume não resolveu. Gestão de diálogo (genérica): se a mensagem for um
        // NOVO assunto confiante, deixa seguir; senão re-pergunta mantendo o pendente.
        const classificada = await this.intent.classify(msg);
        const novoAssunto =
          classificada.confidence >= 0.62 &&
          !['saudacao', 'duvida', 'desconhecido'].includes(classificada.name);
        if (!novoAssunto && outcome && typeof outcome === 'object' && 'reprompt' in outcome) {
          return this.responder(cid, msg.customerRef, outcome.reprompt, {
            handoff: false, ok: true, steps: [], t0,
          });
        }
        estado.pending = undefined;
        intent = classificada;
      }
    } else {
      intent = await this.intent.classify(msg);
    }
    bus.emit('intent.identificada', cid, {
      intent: intent.name, confianca: intent.confidence,
      sentimento: intent.sentiment, urgencia: intent.urgency,
    });

    // 2) Contexto
    const ctx: RequestContext = this.context.build(msg, intent);

    // 3) Políticas (determinístico)
    const decisao = this.policy.evaluate(ctx);
    bus.emit('policy.avaliada', cid, { permitido: decisao.allow, regras: decisao.appliedRules });

    if (!decisao.allow) {
      return this.responder(cid, msg.customerRef, decisao.reason ?? 'Não posso seguir com isso agora.', {
        handoff: false, ok: true, steps: [], t0,
      });
    }

    if (decisao.requireHumanHandoff) {
      return this.acionarHandoff(cid, msg.customerRef, ctx, estado, t0);
    }

    // 4) Conversa simples (sem plano automatizável)
    if (['saudacao', 'duvida', 'desconhecido'].includes(intent.name)) {
      const reply = this.respostaConversacional(ctx);
      return this.responder(cid, msg.customerRef, reply, { handoff: false, ok: true, steps: [], t0 });
    }

    // 5) Descoberta de capacidade
    const planPreview = this.planner.plan(ctx);
    const semAgente = planPreview.steps.some((s) => !this.discovery.descobrir(s.action as any).length && !this.deps.registry.get(s.agent));
    if (planPreview.steps.length === 0 || semAgente) {
      return this.acionarHandoff(cid, msg.customerRef, ctx, estado, t0, 'nenhum agente capaz');
    }

    // 6) Planeja e executa o workflow
    bus.emit('plano.criado', cid, { objetivo: planPreview.goal, passos: planPreview.steps.length });
    const wf = await this.workflow.run(planPreview, ctx);

    // 7) Compõe a resposta a partir dos fragmentos dos agentes
    const fragments = wf.results.map((r) => r.reply).filter(Boolean) as string[];
    let texto = fragments.join('\n\n');

    if (!wf.ok) {
      // Falha real -> handoff com contexto.
      if (wf.rolledBack) texto = 'Tive um problema e desfiz as etapas iniciadas. ';
      return this.acionarHandoff(cid, msg.customerRef, ctx, estado, t0, 'falha na execução', wf.results);
    }

    // Marca ação pendente (confirmação/esclarecimento) para o próximo turno, se algum step a sinalizou.
    const pendStep = wf.results.find(
      (r) => r.output != null && (r.output as { pending?: PendingAction }).pending != null,
    );
    estado.pending = pendStep ? (pendStep.output as { pending: PendingAction }).pending : undefined;

    if (!texto) texto = 'Tudo certo por aqui.';
    return this.responder(cid, msg.customerRef, texto, { handoff: false, ok: true, steps: wf.results, t0 });
  }

  // -------------------------------------------------------------------------

  private respostaConversacional(ctx: RequestContext): string {
    if (ctx.intent.name === 'saudacao') {
      const nome = ctx.customer ? `, ${ctx.customer.name.split(' ')[0]}` : '';
      return `Olá${nome}! 👋 Posso te ajudar com agendamento, horários ou pagamento. O que você precisa?`;
    }
    // dúvida -> responde com conhecimento recuperado (longo prazo), se houver
    if (ctx.knowledge.length > 0) return ctx.knowledge.join('\n');
    return 'Boa pergunta! Posso ajudar com horários, agendamento, remarcação, cancelamento e pagamento. Como prefere seguir?';
  }

  private acionarHandoff(
    cid: string, customerRef: string, ctx: RequestContext,
    estado: ConversationState, t0: number, motivo = 'política/contexto', steps: StepResult[] = [],
  ): KernelResponse {
    estado.handoffAtivo = true;
    // O atendente recebe todo o histórico (princípio do projeto).
    const historico = this.memory.recente(customerRef, 10)
      .map((m) => `${m.role}: ${m.text}`).join(' | ');
    this.deps.bus.emit('handoff.acionado', cid, { motivo, historico });
    const texto = 'Vou te transferir para um atendente humano para cuidar disso com mais atenção. Um instante! 🙌';
    return this.responder(cid, customerRef, texto, {
      handoff: true, handoffReason: motivo, ok: true, steps, t0,
    });
  }

  private responder(
    cid: string, customerRef: string, texto: string,
    opts: { handoff: boolean; handoffReason?: string; ok: boolean; steps: StepResult[]; t0: number },
  ): KernelResponse {
    this.memory.registrar(customerRef, 'assistant', texto);
    const totalCostUsd = opts.steps.reduce((s, r) => s + r.costUsd, 0);
    const totalLatencyMs = Date.now() - opts.t0;
    this.deps.bus.emit('resposta.enviada', cid, {
      ok: opts.ok, handoff: opts.handoff, totalCostUsd, totalLatencyMs,
    });
    return {
      correlationId: cid,
      text: texto,
      handoff: opts.handoff,
      handoffReason: opts.handoffReason,
      ok: opts.ok,
      trace: this.deps.bus.trace(cid),
      steps: opts.steps,
      totalCostUsd,
      totalLatencyMs,
    };
  }
}
