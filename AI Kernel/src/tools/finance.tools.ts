/**
 * tools/finance.tools.ts
 * -----------------------------------------------------------------------------
 * Ferramentas financeiras. PIX e cobranças (simulado).
 * -----------------------------------------------------------------------------
 */

import { Infra } from '../infra/store';
import { Payment, Service } from '../types';
import { id, now } from '../kernel/util';

export function emitirPix(
  infra: Infra,
  args: { customerId: string; service: Service; appointmentId?: string },
): Payment {
  const pay: Payment = {
    id: id('pay'),
    customerId: args.customerId,
    appointmentId: args.appointmentId,
    amountBrl: args.service.priceBrl,
    method: 'pix',
    status: 'pendente',
    pixCode: `00020126BR.GOV.BCB.PIX${id('').replace(/-/g, '').slice(0, 12).toUpperCase()}`,
    createdAt: now(),
  };
  infra.db.payments.set(pay.id, pay);
  return pay;
}

export function cobrancaPendente(infra: Infra, customerId: string): Payment | undefined {
  return [...infra.db.payments.values()].find(
    (p) => p.customerId === customerId && p.status === 'pendente',
  );
}

export function cancelarCobranca(infra: Infra, appointmentId: string): Payment | undefined {
  const p = [...infra.db.payments.values()].find(
    (x) => x.appointmentId === appointmentId && x.status === 'pendente',
  );
  if (p) {
    p.status = 'cancelado';
    infra.db.payments.set(p.id, p);
  }
  return p;
}

export function marcarPago(infra: Infra, paymentId: string): void {
  const p = infra.db.payments.get(paymentId);
  if (p) {
    p.status = 'pago';
    infra.db.payments.set(p.id, p);
  }
}
