/**
 * kernel/context.ts
 * -----------------------------------------------------------------------------
 * Context Builder — monta o contexto MÍNIMO necessário para resolver a
 * solicitação. Objetivo: reduzir custo e aumentar precisão.
 * -----------------------------------------------------------------------------
 */

import { Infra } from '../infra/store';
import { InboundMessage, Intent, RequestContext } from '../types';
import { MemoryEngine } from './memory';

export class ContextBuilder {
  constructor(
    private infra: Infra,
    private memory: MemoryEngine,
  ) {}

  build(msg: InboundMessage, intent: Intent): RequestContext {
    const customer =
      (msg.customerId ? this.infra.db.customers.get(msg.customerId) : undefined) ??
      this.infra.db.findCustomerByPhone(msg.customerRef);

    // Só busca conhecimento de longo prazo quando a intenção se beneficia disso.
    const precisaConhecimento = ['duvida', 'pagar', 'cancelar', 'agendar'].includes(intent.name);
    const knowledge = precisaConhecimento ? this.memory.conhecimento(msg.text, 2) : [];

    const flags: Record<string, boolean> = {
      conhecido: Boolean(customer),
      vip: customer?.vip ?? false,
      inadimplente: customer?.inadimplente ?? false,
      // canal API = painel interno (recepção/gestora): operador autorizado
      operador_interno: msg.channel === 'api',
      autorizado_marketing: msg.channel === 'api',
    };

    return {
      message: msg,
      intent,
      customer,
      recentHistory: this.memory.recente(msg.customerRef, 6),
      knowledge,
      flags,
    };
  }
}
