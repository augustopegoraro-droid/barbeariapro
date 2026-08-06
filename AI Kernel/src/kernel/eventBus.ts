/**
 * kernel/eventBus.ts
 * -----------------------------------------------------------------------------
 * Event Bus — todo evento interno passa por aqui.
 *
 * Permite auditoria completa: cada requisição produz uma trilha de eventos
 * correlacionados (mensagem.recebida -> intent.identificada -> ... ->
 * resposta.enviada). Assinantes (ex.: Metrics Engine) reagem aos eventos.
 * -----------------------------------------------------------------------------
 */

import { now } from './util';

export interface KernelEvent {
  type: string;
  correlationId: string;
  at: number;
  payload: Record<string, unknown>;
}

export type Subscriber = (e: KernelEvent) => void;

export class EventBus {
  private subs: Subscriber[] = [];
  private log: KernelEvent[] = [];

  subscribe(fn: Subscriber): void {
    this.subs.push(fn);
  }

  emit(type: string, correlationId: string, payload: Record<string, unknown> = {}): void {
    const e: KernelEvent = { type, correlationId, at: now(), payload };
    this.log.push(e);
    for (const s of this.subs) s(e);
  }

  /** Trilha legível de uma requisição específica. */
  trace(correlationId: string): string[] {
    return this.log
      .filter((e) => e.correlationId === correlationId)
      .map((e) => {
        const extra = Object.keys(e.payload).length
          ? ' ' + JSON.stringify(e.payload)
          : '';
        return `• ${e.type}${extra}`;
      });
  }

  all(): KernelEvent[] {
    return this.log;
  }
}
