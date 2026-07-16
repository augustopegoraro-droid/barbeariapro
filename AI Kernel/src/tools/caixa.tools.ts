/**
 * tools/caixa.tools.ts
 * -----------------------------------------------------------------------------
 * Ferramentas de caixa (operacional — recepção). Abertura, movimentos
 * (sangria/suprimento/venda), conferência e fechamento. Pura lógica + dados.
 * -----------------------------------------------------------------------------
 */

import { Infra } from '../infra/store';
import { CashMovement, CashMovementType, CashSession } from '../types';
import { id, now } from '../kernel/util';

/** Saldo esperado em caixa = soma de todos os movimentos (entradas - saídas). */
export function saldoEsperado(s: CashSession): number {
  return s.movements.reduce((t, m) => t + m.amountBrl, 0);
}

export function abrirCaixa(
  infra: Infra,
  args: { operador: string; fundo: number },
): { ok: boolean; session?: CashSession; erro?: string } {
  if (infra.db.caixaAberto()) {
    return { ok: false, erro: 'Já existe um caixa aberto. Feche-o antes de abrir outro.' };
  }
  const session: CashSession = {
    id: id('caixa'),
    openedBy: args.operador,
    openedAt: now(),
    openingFloatBrl: args.fundo,
    status: 'aberto',
    movements: [
      { id: id('mov'), type: 'abertura', amountBrl: args.fundo, reason: 'fundo de troco', at: now() },
    ],
  };
  infra.db.cashSessions.set(session.id, session);
  return { ok: true, session };
}

export function registrarMovimento(
  infra: Infra,
  args: { tipo: CashMovementType; valor: number; motivo: string },
): { ok: boolean; saldo?: number; erro?: string } {
  const s = infra.db.caixaAberto();
  if (!s) return { ok: false, erro: 'Nenhum caixa aberto.' };
  if (!args.valor || args.valor <= 0) return { ok: false, erro: 'Informe um valor válido.' };

  // Sangria é saída (negativa); suprimento/venda entram (positivas).
  const amount = args.tipo === 'sangria' ? -Math.abs(args.valor) : Math.abs(args.valor);
  const mov: CashMovement = {
    id: id('mov'),
    type: args.tipo,
    amountBrl: amount,
    reason: args.motivo,
    at: now(),
  };
  s.movements.push(mov);
  infra.db.cashSessions.set(s.id, s);
  return { ok: true, saldo: saldoEsperado(s) };
}

export function resumoCaixa(
  infra: Infra,
): { ok: boolean; session?: CashSession; saldo?: number; erro?: string } {
  const s = infra.db.caixaAberto();
  if (!s) return { ok: false, erro: 'Nenhum caixa aberto.' };
  return { ok: true, session: s, saldo: saldoEsperado(s) };
}

export function fecharCaixa(
  infra: Infra,
  args: { contado: number },
): { ok: boolean; esperado?: number; contado?: number; diferenca?: number; erro?: string } {
  const s = infra.db.caixaAberto();
  if (!s) return { ok: false, erro: 'Nenhum caixa aberto.' };
  const esperado = saldoEsperado(s);
  s.status = 'fechado';
  s.closedAt = now();
  s.closingCountedBrl = args.contado;
  infra.db.cashSessions.set(s.id, s);
  return { ok: true, esperado, contado: args.contado, diferenca: args.contado - esperado };
}
