/**
 * infra/store.ts
 * -----------------------------------------------------------------------------
 * Implementações em memória das dependências de infraestrutura.
 *
 * Em produção cada interface abaixo seria implementada por:
 *   - ShortTermStore  -> Redis
 *   - StructuredStore -> PostgreSQL
 *   - VectorStore     -> banco vetorial (pgvector, Qdrant, etc.)
 *
 * Como tudo está atrás de interface, o Kernel e os agentes não mudam ao trocar
 * a implementação concreta.
 * -----------------------------------------------------------------------------
 */

import {
  Appointment,
  Barber,
  CashSession,
  Customer,
  LoyaltyTier,
  Membership,
  MemoryItem,
  Payment,
  PointsEntry,
  Product,
  Service,
  Voucher,
} from '../types';

// ---------------------------------------------------------------------------
// Camada de curto prazo (Redis): conversa atual por correlation/customer
// ---------------------------------------------------------------------------
export interface ShortTermStore {
  append(key: string, item: MemoryItem): void;
  recent(key: string, n: number): MemoryItem[];
}

export class InMemoryShortTerm implements ShortTermStore {
  private data = new Map<string, MemoryItem[]>();
  append(key: string, item: MemoryItem): void {
    const arr = this.data.get(key) ?? [];
    arr.push(item);
    this.data.set(key, arr.slice(-50));
  }
  recent(key: string, n: number): MemoryItem[] {
    return (this.data.get(key) ?? []).slice(-n);
  }
}

// ---------------------------------------------------------------------------
// Camada estruturada (PostgreSQL): domínio da barbearia
// ---------------------------------------------------------------------------
export class StructuredStore {
  customers = new Map<string, Customer>();
  barbers = new Map<string, Barber>();
  services = new Map<string, Service>();
  appointments = new Map<string, Appointment>();
  payments = new Map<string, Payment>();
  cashSessions = new Map<string, CashSession>();
  products = new Map<string, Product>();
  memberships = new Map<string, Membership>();
  /** Ledger de pontos APPEND-ONLY — fonte de verdade do saldo de fidelidade. */
  pointsLedger: PointsEntry[] = [];
  /** Níveis configuráveis (ordenados por minPoints crescente). */
  loyaltyTiers: LoyaltyTier[] = [];
  /** Créditos (vouchers) gerados por resgate de pontos. */
  vouchers: Voucher[] = [];

  findCustomerByPhone(phone: string): Customer | undefined {
    for (const c of this.customers.values()) {
      if (c.phone === phone) return c;
    }
    return undefined;
  }

  /** Caixa aberto no momento (no máximo um por vez nesta simulação). */
  caixaAberto(): CashSession | undefined {
    return [...this.cashSessions.values()].find((s) => s.status === 'aberto');
  }

  /** Produtos cujo estoque está no/abaixo do mínimo (gatilho de reposição). */
  produtosAbaixoDoMinimo(): Product[] {
    return [...this.products.values()].filter((p) => p.stockQty <= p.minQty);
  }

  appointmentsForBarberOnDay(barberId: string, dayStart: number, dayEnd: number): Appointment[] {
    return [...this.appointments.values()].filter(
      (a) =>
        a.barberId === barberId &&
        a.status === 'confirmado' &&
        a.start >= dayStart &&
        a.start < dayEnd,
    );
  }

  // --- membership / fidelidade ---

  membershipsForCustomer(customerId: string): Membership[] {
    return [...this.memberships.values()].filter((m) => m.customerId === customerId);
  }

  /**
   * Saldo de pontos do cliente = `balanceAfter` do último lançamento do ledger
   * (varredura do fim com parada no primeiro lançamento do cliente — barato no
   * caso típico). O ledger é a fonte de verdade append-only; `balanceAfter` é
   * mantido a cada lançamento, evitando re-somar todo o histórico.
   */
  pointsBalance(customerId: string): number {
    for (let i = this.pointsLedger.length - 1; i >= 0; i--) {
      if (this.pointsLedger[i].customerId === customerId) return this.pointsLedger[i].balanceAfter;
    }
    return 0;
  }

  /** Maior tier cujo minPoints o cliente alcança (points-driven) — passada única. */
  tierForPoints(points: number): LoyaltyTier | undefined {
    let best: LoyaltyTier | undefined;
    for (const t of this.loyaltyTiers) {
      if (points >= t.minPoints && (!best || t.minPoints > best.minPoints)) best = t;
    }
    return best;
  }
}

// ---------------------------------------------------------------------------
// Camada de longo prazo (Vetorial): conhecimento recuperado por similaridade
// ---------------------------------------------------------------------------
export interface VectorStore {
  search(query: string, k: number): string[];
}

/**
 * Implementação ingênua: similaridade por sobreposição de palavras.
 * Em produção: embeddings + ANN. A interface não muda.
 */
export class InMemoryVector implements VectorStore {
  private docs: string[] = [];
  add(doc: string): void {
    this.docs.push(doc);
  }
  search(query: string, k: number): string[] {
    const q = tokenize(query);
    return this.docs
      .map((d) => ({ d, score: overlap(q, tokenize(d)) }))
      .filter((x) => x.score > 0)
      .sort((a, b) => b.score - a.score)
      .slice(0, k)
      .map((x) => x.d);
  }
}

function tokenize(s: string): Set<string> {
  return new Set(
    s
      .toLowerCase()
      .normalize('NFD')
      .replace(/[\u0300-\u036f]/g, '')
      .split(/[^a-z0-9]+/)
      .filter((w) => w.length > 2),
  );
}

function overlap(a: Set<string>, b: Set<string>): number {
  let n = 0;
  for (const w of a) if (b.has(w)) n++;
  return n;
}

// ---------------------------------------------------------------------------
// Agregador de infraestrutura
// ---------------------------------------------------------------------------
export class Infra {
  shortTerm = new InMemoryShortTerm();
  db = new StructuredStore();
  vector = new InMemoryVector();
}
