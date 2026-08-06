/**
 * kernel/memory.ts
 * -----------------------------------------------------------------------------
 * Memory Engine — três camadas.
 *
 *   Curto prazo  (Redis)        -> conversa atual
 *   Médio prazo  (PostgreSQL)   -> histórico estruturado (no domínio)
 *   Longo prazo  (Vetorial)     -> conhecimento por similaridade
 *
 * Política de promoção: o que vira conhecimento de longo prazo é decidido aqui,
 * não espalhado pelo sistema.
 * -----------------------------------------------------------------------------
 */

import { Infra } from '../infra/store';
import { MemoryItem } from '../types';
import { now } from './util';

export class MemoryEngine {
  constructor(private infra: Infra) {}

  private chave(customerRef: string): string {
    return `conv:${customerRef}`;
  }

  // --- curto prazo ---------------------------------------------------------
  registrar(customerRef: string, role: MemoryItem['role'], text: string): void {
    this.infra.shortTerm.append(this.chave(customerRef), { role, text, at: now() });
  }

  recente(customerRef: string, n = 6): MemoryItem[] {
    return this.infra.shortTerm.recent(this.chave(customerRef), n);
  }

  // --- longo prazo ---------------------------------------------------------
  conhecimento(query: string, k = 3): string[] {
    return this.infra.vector.search(query, k);
  }

  /**
   * Política de promoção para longo prazo: só fatos estáveis e úteis viram
   * conhecimento (ex.: preferência declarada do cliente). Conversa fiada não.
   */
  talvezPromover(text: string): void {
    const gatilhos = ['prefiro', 'sempre', 'gosto de', 'alergia', 'nunca'];
    if (gatilhos.some((g) => text.toLowerCase().includes(g))) {
      this.infra.vector.add(`Preferência do cliente: ${text}`);
    }
  }
}
