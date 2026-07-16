/**
 * types.ts
 * -----------------------------------------------------------------------------
 * Contratos centrais do BarbeariaPro.
 *
 * Princípio: o Kernel só conhece interfaces. Nenhum componente conhece a
 * implementação concreta do outro. Trocar Redis por outra coisa, ou Claude por
 * Gemini, não deve exigir mudança no núcleo.
 * -----------------------------------------------------------------------------
 */

// ===========================================================================
// Canais e entrada
// ===========================================================================

export type Channel =
  | 'whatsapp'
  | 'site'
  | 'instagram'
  | 'telegram'
  | 'api'
  | 'app';

/** Entrada já normalizada pelo Gateway (qualquer canal vira este formato). */
export interface InboundMessage {
  id: string;
  correlationId: string; // id da requisição inteira (para auditoria)
  channel: Channel;
  customerRef: string; // telefone / handle / id externo
  customerId?: string; // resolvido se o cliente já existe
  text: string;
  receivedAt: number;
  locale?: string;
}

// ===========================================================================
// Intenção
// ===========================================================================

export type IntentName =
  // Voltadas ao cliente final (bot)
  | 'consultar_horarios'
  | 'agendar'
  | 'remarcar'
  | 'cancelar'
  | 'pagar'
  | 'consultar_cliente'
  | 'campanha'
  | 'saudacao'
  | 'duvida'
  | 'desconhecido'
  // Operacionais (painel interno — Raquel/gestora)
  | 'abrir_caixa'
  | 'fechar_caixa'
  | 'movimentar_caixa'
  | 'consultar_caixa'
  | 'cobrar_inadimplentes'
  | 'reativar_clientes'
  | 'enviar_lembretes'
  | 'consultar_estoque'
  | 'registrar_consumo'
  | 'repor_estoque'
  | 'reagendar_em_massa'
  // Pacotes / Fidelidade / Assinaturas (cliente final — sobre os PRÓPRIOS dados)
  | 'consultar_pacote'
  | 'consultar_assinatura'
  | 'consultar_pontos'
  | 'consultar_nivel'
  | 'quanto_economizei'
  | 'renovar_assinatura'
  | 'comprar_pacote'
  | 'cancelar_assinatura'
  | 'usar_pacote'
  | 'resgatar_pontos';

/** Intenções que só a equipe interna (operador) pode disparar. */
export const INTENTS_OPERACIONAIS: IntentName[] = [
  'abrir_caixa',
  'fechar_caixa',
  'movimentar_caixa',
  'consultar_caixa',
  'cobrar_inadimplentes',
  'reativar_clientes',
  'enviar_lembretes',
  'consultar_estoque',
  'registrar_consumo',
  'repor_estoque',
  'reagendar_em_massa',
];

export type Urgency = 'baixa' | 'media' | 'alta';
export type Sentiment = 'positivo' | 'neutro' | 'negativo';

export interface Intent {
  name: IntentName;
  confidence: number; // 0..1
  urgency: Urgency;
  sentiment: Sentiment;
  locale: string;
  entities: Record<string, string>; // ex.: { servico: 'corte', quando: 'amanha' }
}

// ===========================================================================
// Domínio: barbearia
// ===========================================================================

export interface Customer {
  id: string;
  name: string;
  phone: string;
  vip: boolean;
  inadimplente: boolean;
  notes: string[];
  createdAt: number;
}

export interface Barber {
  id: string;
  name: string;
  active: boolean;
}

export interface Service {
  id: string;
  name: string;
  durationMin: number;
  priceBrl: number;
}

export type AppointmentStatus = 'confirmado' | 'cancelado' | 'concluido';

export interface Appointment {
  id: string;
  customerId: string;
  barberId: string;
  serviceId: string;
  start: number; // epoch ms
  end: number;
  status: AppointmentStatus;
}

export interface Payment {
  id: string;
  customerId: string;
  appointmentId?: string;
  amountBrl: number;
  method: 'pix';
  status: 'pendente' | 'pago' | 'cancelado';
  pixCode?: string;
  createdAt: number;
}

export interface Slot {
  barberId: string;
  barberName: string;
  start: number;
  end: number;
}

// ===========================================================================
// Caixa (operacional — recepção)
// ===========================================================================

export type CashStatus = 'aberto' | 'fechado';

/** Entradas e saídas do caixa. `amountBrl` positivo entra, negativo sai. */
export type CashMovementType = 'abertura' | 'venda' | 'sangria' | 'suprimento';

export interface CashMovement {
  id: string;
  type: CashMovementType;
  amountBrl: number;
  reason: string;
  at: number;
}

export interface CashSession {
  id: string;
  openedBy: string;
  openedAt: number;
  openingFloatBrl: number; // fundo de troco
  status: CashStatus;
  movements: CashMovement[];
  closedAt?: number;
  closingCountedBrl?: number; // valor contado no fechamento
}

// ===========================================================================
// Estoque / Produtos (operacional)
// ===========================================================================

export interface Product {
  id: string;
  name: string;
  priceBrl: number;
  stockQty: number;
  minQty: number; // gatilho de alerta de reposição
  unit: string; // 'un', 'ml', 'frasco'...
}

// ===========================================================================
// Pacotes / Assinaturas (membership) — cliente final
// ===========================================================================

export type MembershipKind = 'pacote' | 'assinatura';
export type MembershipStatus = 'ativa' | 'expirada' | 'cancelada';

export interface Membership {
  id: string;
  customerId: string;
  planName: string; // ex.: "10 Cortes", "Mensal Premium"
  kind: MembershipKind;
  serviceIds: string[]; // combo do plano (serviços consumidos juntos por uso) — snapshot
  includedUses: number | null; // null = ilimitado (assinatura)
  usedUses: number;
  pricePaidBrl: number; // snapshot do preço pago
  unitValueBrl: number; // valor reconhecido por uso (rateio)
  refUnitPriceBrl: number; // preço avulso de referência de 1 uso (p/ calcular economia)
  startAt: number;
  endAt: number; // validade
  status: MembershipStatus;
  autoRenew: boolean;
  canceledReason?: string;
}

// ===========================================================================
// Fidelidade por pontos (points-driven — o nível DERIVA do saldo de pontos)
// ===========================================================================

export type PointsEventType = 'earn' | 'redeem' | 'expire' | 'adjust' | 'reversal';

/** Lançamento do ledger de pontos. APPEND-ONLY: o saldo nunca é mutado direto. */
export interface PointsEntry {
  id: string;
  customerId: string;
  type: PointsEventType;
  delta: number; // + ganha, - gasta/expira
  balanceAfter: number; // saldo resultante (auditoria)
  reason: string;
  refAppointmentId?: string;
  at: number;
}

/** Nível configurável: o cliente fica no maior tier cujo minPoints ele alcança. */
export interface LoyaltyTier {
  name: string; // Bronze, Prata, Ouro, Diamante, Black
  minPoints: number;
  discountPct: number; // 0..1 (benefício de desconto)
  perks: string[];
}

/** Crédito gerado por resgate de pontos — durável, consumido no checkout (fase futura). */
export interface Voucher {
  id: string;
  customerId: string;
  amountBrl: number;
  reason: string;
  createdAt: number;
  consumedAt?: number;
}

// ===========================================================================
// Memória
// ===========================================================================

export type MemoryRole = 'customer' | 'assistant' | 'system';

export interface MemoryItem {
  role: MemoryRole;
  text: string;
  at: number;
}

// ===========================================================================
// Contexto da requisição
// ===========================================================================

export interface RequestContext {
  message: InboundMessage;
  intent: Intent;
  customer?: Customer;
  recentHistory: MemoryItem[]; // curto prazo (Redis)
  knowledge: string[]; // longo prazo (vetorial) — trechos recuperados
  flags: Record<string, boolean>; // vip, inadimplente, autorizado_marketing...
}

// ===========================================================================
// Policy Engine (determinístico — IA nunca substitui)
// ===========================================================================

export interface PolicyDecision {
  allow: boolean;
  reason?: string;
  requireHumanHandoff: boolean;
  priorityBoost: number; // 0..n
  appliedRules: string[];
}

// ===========================================================================
// Agentes e Registry
// ===========================================================================

export interface Capability {
  intent: IntentName;
  description: string;
}

export type Health = 'healthy' | 'degraded' | 'down';

export interface AgentDescriptor {
  name: string;
  description: string;
  capabilities: Capability[];
  permissions: string[];
  tools: string[];
  estimatedCostUsd: number;
  avgLatencyMs: number;
  version: string;
  health: Health;
}

// ===========================================================================
// Planner / Workflow
// ===========================================================================

export interface PlanStep {
  id: string;
  agent: string; // nome do agente no Registry
  action: string; // capacidade que será executada
  description: string;
  input: Record<string, unknown>;
  dependsOn: string[]; // ids de outros steps
  compensable: boolean; // se falhar adiante, precisa desfazer?
}

export interface ExecutionPlan {
  goal: string;
  steps: PlanStep[];
}

export interface StepResult {
  stepId: string;
  agent: string;
  action: string;
  ok: boolean;
  output?: unknown;
  reply?: string;
  error?: string;
  latencyMs: number;
  retries: number;
  modelUsed?: string;
  costUsd: number;
  compensated?: boolean;
  halt?: boolean;
}

// ===========================================================================
// AI Router
// ===========================================================================

export type AITaskKind =
  | 'classificacao'
  | 'resposta'
  | 'resumo'
  | 'planejamento'
  | 'complexo';

export interface AITask {
  kind: AITaskKind;
  prompt: string;
  preferQuality?: boolean;
}

export interface ModelChoice {
  model: string;
  provider: 'anthropic' | 'google' | 'openai' | 'local';
  estCostUsd: number;
  estLatencyMs: number;
  reason: string;
}

export interface AICompletion {
  text: string;
  model: string;
  costUsd: number;
  latencyMs: number;
}

export interface AIRouter {
  choose(task: AITask): ModelChoice;
  complete(task: AITask): Promise<AICompletion>;
}

// ===========================================================================
// Interface de execução dos agentes
// ===========================================================================

export interface AgentExecuteInput {
  step: PlanStep;
  context: RequestContext;
  ai: AIRouter;
  emit: (type: string, payload?: Record<string, unknown>) => void;
}

export interface AgentExecuteOutput {
  ok: boolean;
  output?: unknown;
  reply?: string; // fragmento em linguagem natural para o cliente
  error?: string;
  costUsd?: number;
  modelUsed?: string;
  /** Pausa o workflow sem rollback (ex.: agente fez uma pergunta ao cliente). */
  halt?: boolean;
}

/**
 * Resultado de uma retomada multi-turn (o agente interpreta a resposta a uma
 * pergunta pendente que ele mesmo criou):
 *  - Intent: reexecutar com essa intenção;
 *  - 'cancelado': abandonar a ação pendente;
 *  - { reprompt }: re-perguntar mantendo o pendente;
 *  - undefined: soltar o pendente e classificar normalmente.
 */
export type ResumeOutcome = Intent | 'cancelado' | { reprompt: string } | undefined;

export interface Agent {
  descriptor: AgentDescriptor;
  execute(input: AgentExecuteInput): Promise<AgentExecuteOutput>;
  /** Desfaz o efeito de um step (saga / rollback). */
  compensate?(step: PlanStep, context: RequestContext): Promise<void>;
  /**
   * Interpreta a resposta do cliente a uma ação pendente que ESTE agente criou
   * (multi-turn). O Kernel guarda o estado e delega o parsing de domínio aqui —
   * assim o núcleo não carrega regra de negócio de nenhum agente.
   */
  resume?(pending: unknown, text: string): ResumeOutcome;
}

// ===========================================================================
// Resposta do Kernel
// ===========================================================================

export interface KernelResponse {
  correlationId: string;
  text: string;
  handoff: boolean;
  handoffReason?: string;
  ok: boolean;
  trace: string[]; // eventos legíveis
  steps: StepResult[];
  totalCostUsd: number;
  totalLatencyMs: number;
}
