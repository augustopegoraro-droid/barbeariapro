/**
 * kernel/intent.ts
 * -----------------------------------------------------------------------------
 * Intent Classifier — identifica intenção, urgência, idioma e sentimento.
 *
 * Conforme o princípio do projeto, usa regras/classificadores leves ANTES de
 * recorrer a um modelo maior. Só cai para o LLM quando a confiança é baixa.
 * -----------------------------------------------------------------------------
 */

import { AIRouter, InboundMessage, Intent, IntentName, Sentiment, Urgency } from '../types';

interface Regra {
  intent: IntentName;
  termos: string[];
  peso: number;
}

const REGRAS: Regra[] = [
  { intent: 'consultar_horarios', termos: ['horário', 'horarios', 'tem vaga', 'disponível', 'disponivel', 'que horas'], peso: 1 },
  { intent: 'agendar', termos: ['agendar', 'marcar', 'quero um', 'reservar', 'agenda pra mim'], peso: 1.2 },
  { intent: 'remarcar', termos: ['remarcar', 'mudar o horário', 'mudar horario', 'trocar o dia', 'adiar'], peso: 1.3 },
  { intent: 'cancelar', termos: ['cancelar', 'desmarcar', 'não vou poder', 'nao vou poder'], peso: 1.3 },
  { intent: 'pagar', termos: ['pagar', 'pix', 'cobrança', 'cobranca', 'pagamento', 'quanto fica', 'valor'], peso: 1 },
  { intent: 'consultar_cliente', termos: ['meu cadastro', 'meus dados', 'meu histórico', 'meu historico'], peso: 1 },
  { intent: 'campanha', termos: ['campanha', 'promoção', 'promocao', 'disparar', 'segmentar'], peso: 1 },
  { intent: 'saudacao', termos: ['oi', 'olá', 'ola', 'bom dia', 'boa tarde', 'boa noite', 'e aí', 'e ai'], peso: 0.5 },

  // Operacionais (painel interno — Raquel/gestora)
  { intent: 'abrir_caixa', termos: ['abrir o caixa', 'abrir caixa', 'abertura de caixa'], peso: 1.5 },
  { intent: 'fechar_caixa', termos: ['fechar o caixa', 'fechar caixa', 'fechamento de caixa', 'fechar o dia'], peso: 1.5 },
  { intent: 'movimentar_caixa', termos: ['sangria', 'suprimento', 'retirada do caixa', 'reforço de caixa', 'reforco de caixa', 'retirar do caixa'], peso: 1.5 },
  { intent: 'consultar_caixa', termos: ['saldo do caixa', 'resumo do caixa', 'consultar caixa', 'quanto tem no caixa', 'como esta o caixa'], peso: 1.4 },
  { intent: 'cobrar_inadimplentes', termos: ['inadimplente', 'inadimplentes', 'quem esta devendo', 'quem está devendo', 'cobrar os clientes', 'pendencias', 'pendências'], peso: 1.4 },
  { intent: 'reativar_clientes', termos: ['reativar', 'clientes sumidos', 'clientes inativos', 'quem sumiu', 'trazer de volta'], peso: 1.5 },
  { intent: 'enviar_lembretes', termos: ['lembrete', 'lembretes', 'confirmar os agendamentos', 'avisar os clientes de amanha', 'avisar os clientes de amanhã'], peso: 1.4 },
  { intent: 'consultar_estoque', termos: ['estoque', 'estoque baixo', 'produtos em falta', 'o que esta acabando', 'o que está acabando', 'consultar produtos'], peso: 1.3 },
  { intent: 'registrar_consumo', termos: ['dar baixa', 'baixa no estoque', 'registrar consumo', 'consumi', 'usei', 'gastei'], peso: 1.5 },
  { intent: 'repor_estoque', termos: ['repor', 'repoe', 'repõe', 'chegou produto', 'chegou', 'abastecer', 'entrada de produto', 'comprei'], peso: 1.5 },
  { intent: 'reagendar_em_massa', termos: ['reagendar todos', 'remarcar todos', 'remarca todos', 'reagenda todos', 'faltou', 'nao vai vir', 'não vai vir', 'nao vem', 'reorganizar a agenda'], peso: 1.6 },

  // Pacotes / Fidelidade / Assinaturas (cliente final)
  { intent: 'consultar_pacote', termos: ['quantos cortes', 'quantas barbas', 'cortes tenho', 'cortes restantes', 'meu pacote', 'saldo do pacote', 'pacote tenho', 'quantos usos'], peso: 1.4 },
  { intent: 'consultar_assinatura', termos: ['minha assinatura', 'assinatura vence', 'quando vence', 'vencimento da assinatura', 'minha mensalidade', 'mensalidade vence'], peso: 1.4 },
  { intent: 'consultar_pontos', termos: ['tenho pontos', 'meus pontos', 'saldo de pontos', 'quantos pontos', 'tenho ponto'], peso: 1.4 },
  { intent: 'consultar_nivel', termos: ['que nivel', 'qual meu nivel', 'meu nivel', 'falta para', 'falta pra', 'virar ouro', 'virar prata', 'virar diamante', 'proximo nivel', 'subir de nivel'], peso: 1.4 },
  { intent: 'quanto_economizei', termos: ['quanto economizei', 'economizei', 'quanto poupei', 'minha economia'], peso: 1.5 },
  { intent: 'renovar_assinatura', termos: ['renovar', 'renovacao', 'renovação', 'estender', 'quero renovar', 'renovar minha assinatura', 'renovar meu pacote'], peso: 1.5 },
  { intent: 'comprar_pacote', termos: ['comprar pacote', 'comprar um pacote', 'quero comprar', 'novo pacote', 'contratar pacote', 'assinar plano', 'quero assinar'], peso: 1.5 },
  { intent: 'cancelar_assinatura', termos: ['cancelar pacote', 'cancelar meu pacote', 'cancelar assinatura', 'cancelar minha assinatura', 'cancelar mensalidade', 'cancelar plano'], peso: 1.6 },
  { intent: 'resgatar_pontos', termos: ['resgatar', 'resgate', 'confirmar resgate', 'usar pontos', 'usar meus pontos', 'trocar pontos', 'desconto com pontos', 'pontos de desconto'], peso: 1.6 },
  { intent: 'usar_pacote', termos: ['usar o pacote', 'usar meu pacote', 'usar um corte', 'usar um corte do pacote', 'gastar um corte', 'baixar um corte', 'dar baixa no pacote', 'usar pacote'], peso: 1.7 },
];

const NEGATIVO = ['absurdo', 'péssimo', 'pessimo', 'ridículo', 'ridiculo', 'irritado', 'cansei', 'reclamação', 'reclamacao', 'horrível', 'horrivel', 'nunca mais', 'palhaçada', 'palhacada'];
const POSITIVO = ['obrigado', 'obrigada', 'ótimo', 'otimo', 'perfeito', 'adorei', 'valeu', 'show'];
const URGENTE = ['agora', 'urgente', 'já', 'imediatamente', 'hoje mesmo', 'rápido', 'rapido'];

function norm(s: string): string {
  return s.toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '');
}

function extrairEntidades(texto: string): Record<string, string> {
  const t = norm(texto);
  const e: Record<string, string> = {};

  if (t.includes('combo')) e.servico = 'combo';
  else if (t.includes('barba')) e.servico = 'barba';
  else if (t.includes('corte') || t.includes('cabelo')) e.servico = 'corte';

  if (t.includes('amanha')) e.quando = 'amanha';
  else if (t.includes('hoje')) e.quando = 'hoje';
  else if (t.includes('depois de amanha')) e.quando = 'depois_amanha';

  const hora = t.match(/(\d{1,2})\s*(?:h|:00|horas)/);
  if (hora) e.hora = hora[1];

  if (t.includes('rafael')) e.barbeiro = 'Rafael';
  else if (t.includes('diego')) e.barbeiro = 'Diego';

  // --- entidades operacionais (recepção) ---

  // valor monetário (fundo de troco, sangria, suprimento) — só sob contexto de caixa
  if (/caixa|troco|fundo|sangria|suprimento|reforc|retir/.test(t)) {
    const m = t.match(/(\d{1,6})(?:[.,](\d{1,2}))?/);
    if (m) e.valor = m[2] ? `${m[1]}.${m[2]}` : m[1];
  }

  // tipo de movimento de caixa
  if (t.includes('sangria') || t.includes('retir')) e.mov = 'sangria';
  else if (t.includes('suprimento') || t.includes('reforc')) e.mov = 'suprimento';

  // produto conhecido
  for (const p of ['pomada', 'gel', 'shampoo', 'cera', 'lamina', 'lâmina', 'navalha', 'toalha']) {
    if (t.includes(norm(p))) {
      e.produto = norm(p) === 'lamina' ? 'lamina' : norm(p);
      break;
    }
  }

  // quantidade (consumo/reposição de estoque)
  if (/consum|usei|gastei|repor|repoe|rep[oõ]e|abastec|chegou|baixa|comprei/.test(t)) {
    const m = t.match(/(\d{1,4})/);
    if (m) e.qtd = m[1];
  }

  // --- entidades de fidelidade / pacote ---

  // nível-alvo ("falta para virar ouro")
  for (const tier of ['bronze', 'prata', 'ouro', 'diamante', 'black']) {
    if (t.includes(tier)) {
      e.tier = tier.charAt(0).toUpperCase() + tier.slice(1);
      break;
    }
  }

  // pontos a resgatar ("usar 100 pontos")
  if (t.includes('ponto')) {
    const m = t.match(/(\d{1,5})\s*pontos?/);
    if (m) e.pontos = m[1];
  }

  // tamanho do pacote na compra ("pacote de 10 cortes")
  if (/pacote|cortes|barbas/.test(t)) {
    const m = t.match(/(\d{1,3})\s*(?:cortes?|barbas?|usos?)/);
    if (m) e.usos = m[1];
  }

  // compra como assinatura (ilimitada) vs pacote (finito)
  if (/assin|mensal|plano mensal/.test(t)) e.modo = 'assinatura';

  // tipo nomeado para cancelar/renovar (qual deles o cliente quer mexer)
  if (t.includes('pacote')) e.alvo = 'pacote';
  else if (/assinatura|mensalidade/.test(t)) e.alvo = 'assinatura';

  // NOTA: a confirmação de resgate que rebaixa o nível NÃO é derivada de texto
  // livre (seria burlável, ex.: "confirmo que sou o João"). Ela vem apenas do
  // fluxo com estado do Kernel (halt → "sim"), que injeta entities.confirmado.

  return e;
}

export class IntentClassifier {
  constructor(private ai: AIRouter) {}

  async classify(msg: InboundMessage): Promise<Intent> {
    const t = norm(msg.text);

    // 1) Camada de regras (barata)
    let melhor: { intent: IntentName; score: number } = { intent: 'desconhecido', score: 0 };
    for (const r of REGRAS) {
      const hits = r.termos.filter((termo) => t.includes(norm(termo))).length;
      if (hits > 0) {
        const score = hits * r.peso;
        if (score > melhor.score) melhor = { intent: r.intent, score };
      }
    }

    let confidence = Math.min(0.95, 0.55 + melhor.score * 0.18);
    let name = melhor.intent;

    // 2) Fallback para IA só quando regras não resolvem
    if (name === 'desconhecido' || confidence < 0.62) {
      const choice = this.ai.choose({ kind: 'classificacao', prompt: msg.text });
      // (No mock, a "classificação por IA" é simulada: se nada bateu, vira dúvida)
      if (name === 'desconhecido') {
        name = t.length > 0 ? 'duvida' : 'desconhecido';
        confidence = 0.5;
      }
      void choice;
    }

    const sentiment: Sentiment = NEGATIVO.some((w) => t.includes(w))
      ? 'negativo'
      : POSITIVO.some((w) => t.includes(w))
        ? 'positivo'
        : 'neutro';

    const urgency: Urgency = URGENTE.some((w) => t.includes(w)) ? 'alta' : 'media';

    return {
      name,
      confidence,
      urgency,
      sentiment,
      locale: msg.locale ?? 'pt-BR',
      entities: extrairEntidades(msg.text),
    };
  }
}
