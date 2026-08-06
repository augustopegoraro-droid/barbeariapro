/**
 * tools/crm.tools.ts
 * -----------------------------------------------------------------------------
 * Ferramentas de CRM. Clientes, histórico e observações.
 * -----------------------------------------------------------------------------
 */

import { Infra } from '../infra/store';
import { Customer } from '../types';

export function buscarCliente(infra: Infra, customerId?: string): Customer | undefined {
  return customerId ? infra.db.customers.get(customerId) : undefined;
}

export function registrarInteracao(infra: Infra, customerId: string, nota: string): void {
  const c = infra.db.customers.get(customerId);
  if (c) {
    c.notes.push(`[${new Date().toLocaleDateString('pt-BR')}] ${nota}`);
    infra.db.customers.set(c.id, c);
  }
}

export function historicoAgendamentos(infra: Infra, customerId: string): number {
  return [...infra.db.appointments.values()].filter((a) => a.customerId === customerId).length;
}
