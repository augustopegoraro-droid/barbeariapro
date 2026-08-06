/**
 * kernel/policy.ts
 * -----------------------------------------------------------------------------
 * Policy Engine — centraliza regras DETERMINÍSTICAS.
 *
 * A IA nunca substitui estas regras. Aqui decidimos prioridade (VIP), bloqueios
 * (inadimplência), autorização (campanhas) e quando exigir um humano.
 * -----------------------------------------------------------------------------
 */

import { INTENTS_OPERACIONAIS, PolicyDecision, RequestContext } from '../types';

export class PolicyEngine {
  evaluate(ctx: RequestContext): PolicyDecision {
    const aplicadas: string[] = [];
    let allow = true;
    let requireHumanHandoff = false;
    let priorityBoost = 0;
    let reason: string | undefined;

    // VIP tem prioridade
    if (ctx.flags.vip) {
      priorityBoost += 2;
      aplicadas.push('cliente_vip_prioridade');
    }

    // Inadimplente: bloqueia novos agendamentos, mas permite pagar
    if (ctx.flags.inadimplente && ['agendar', 'remarcar'].includes(ctx.intent.name)) {
      allow = false;
      reason =
        'Há uma pendência financeira no seu cadastro. Para agendar, é preciso regularizar. Posso gerar o PIX para você?';
      aplicadas.push('bloqueio_inadimplente');
    }

    // Inadimplente não pode renovar/comprar pacote sem regularizar (mas pode consultar)
    if (
      ctx.flags.inadimplente &&
      ['renovar_assinatura', 'comprar_pacote'].includes(ctx.intent.name)
    ) {
      allow = false;
      reason =
        'Há uma pendência financeira no seu cadastro. Para renovar ou comprar um pacote, regularize antes. Quer o PIX?';
      aplicadas.push('bloqueio_inadimplente_membership');
    }

    // Campanhas só por usuário autorizado (operador interno)
    if (ctx.intent.name === 'campanha' && !ctx.flags.autorizado_marketing) {
      allow = false;
      reason = 'Apenas a equipe autorizada pode disparar campanhas.';
      aplicadas.push('campanha_requer_autorizacao');
    }

    // Ações operacionais (caixa, estoque, cobrança, reagendamento em massa) só
    // pelo painel interno — um cliente no WhatsApp nunca abre caixa ou dá baixa.
    if (INTENTS_OPERACIONAIS.includes(ctx.intent.name) && !ctx.flags.operador_interno) {
      allow = false;
      reason = 'Esta ação é restrita à equipe (painel interno).';
      aplicadas.push('acao_operacional_restrita');
    }

    // Cliente irritado -> humano assume
    if (ctx.intent.sentiment === 'negativo') {
      requireHumanHandoff = true;
      aplicadas.push('handoff_cliente_irritado');
    }

    // Baixa confiança na intenção -> humano assume
    if (ctx.intent.confidence < 0.5) {
      requireHumanHandoff = true;
      aplicadas.push('handoff_baixa_confianca');
    }

    return { allow, reason, requireHumanHandoff, priorityBoost, appliedRules: aplicadas };
  }
}
