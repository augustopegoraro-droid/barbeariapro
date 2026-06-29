/**
 * tools/membership.tools.ts
 * -----------------------------------------------------------------------------
 * Ferramentas de Pacotes / Fidelidade / Assinaturas. Funções puras (sem IA),
 * determinísticas. Regras invioláveis:
 *   - saldo de pacote nunca negativo (não usa além do incluído);
 *   - saldo de pontos nunca negativo (não resgata além do que tem);
 *   - o saldo de pontos NUNCA é mutado direto — toda mudança é um lançamento
 *     no ledger append-only (earn/redeem/expire/adjust/reversal).
 * -----------------------------------------------------------------------------
 */

import { Infra } from '../infra/store';
import { LoyaltyTier, Membership, MembershipKind, PointsEntry, PointsEventType, Voucher } from '../types';
import { id, now } from '../kernel/util';

const DIA_MS = 24 * 60 * 60_000;

// Parâmetros de negócio (centralizados para não espalhar números mágicos).
export const PONTOS_POR_USO = 40;
export const DESCONTO_PACOTE = 0.2; // ~20% off ao comprar pacote adiantado
export const DIAS_PACOTE = 90;
export const DIAS_ASSINATURA = 30;
export const PRECO_ASSINATURA_PADRAO = 199;
export const USOS_PACOTE_PADRAO = 10;

// --------------------------------------------------------------------------
// Consulta
// --------------------------------------------------------------------------

export function membershipsDoCliente(infra: Infra, customerId: string): Membership[] {
  return infra.db.membershipsForCustomer(customerId);
}

/** Vigente = ativa, dentro da validade e (se pacote) com saldo. */
function vigente(m: Membership): boolean {
  if (m.status !== 'ativa' || m.endAt <= now()) return false;
  if (m.includedUses == null) return true; // assinatura ilimitada
  return m.usedUses < m.includedUses;
}

// Ordena pela validade MAIS CURTA primeiro (soonest-expiry-first): consome e
// exibe o que vence antes, minimizando perda. A renovação aposenta a anterior
// (status 'expirada'), então não há leitura stale mesmo com esta ordem.
export function pacoteAtivo(infra: Infra, customerId: string): Membership | undefined {
  return infra.db
    .membershipsForCustomer(customerId)
    .filter((m) => m.kind === 'pacote' && vigente(m))
    .sort((a, b) => a.endAt - b.endAt)[0];
}

export function assinaturaAtiva(infra: Infra, customerId: string): Membership | undefined {
  return infra.db
    .membershipsForCustomer(customerId)
    .filter((m) => m.kind === 'assinatura' && vigente(m))
    .sort((a, b) => a.endAt - b.endAt)[0];
}

/** Pacote dentro da validade, mesmo ESGOTADO (para distinguir "esgotado" de "não tem"). */
export function pacoteDentroDaValidade(infra: Infra, customerId: string): Membership | undefined {
  return infra.db
    .membershipsForCustomer(customerId)
    .filter((m) => m.kind === 'pacote' && m.status === 'ativa' && m.endAt > now())
    .sort((a, b) => a.endAt - b.endAt)[0];
}

export function saldoUsos(m: Membership): number | null {
  return m.includedUses == null ? null : Math.max(0, m.includedUses - m.usedUses);
}

export function diasParaVencer(m: Membership): number {
  return Math.ceil((m.endAt - now()) / DIA_MS);
}

/**
 * Quanto o cliente já economizou com PACOTES (preço avulso − valor por uso).
 * Só pacotes têm "economia por uso" bem definida; assinatura (uso ilimitado) e
 * planos cancelados não entram. Para combo, o avulso é a soma dos serviços do uso.
 */
export function economiaTotal(infra: Infra, customerId: string): number {
  let total = 0;
  for (const m of infra.db.membershipsForCustomer(customerId)) {
    if (m.kind !== 'pacote' || m.status === 'cancelada') continue;
    // usa o preço avulso de referência gravado na compra (não recalcula dos serviços).
    const economiaPorUso = Math.max(0, m.refUnitPriceBrl - m.unitValueBrl);
    total += economiaPorUso * m.usedUses;
  }
  return total;
}

/** Tier configurado pelo nome (para responder "falta p/ Ouro"). */
export function tierPorNome(infra: Infra, nome?: string): LoyaltyTier | undefined {
  return nome ? infra.db.loyaltyTiers.find((t) => t.name === nome) : undefined;
}

/** Tier que um saldo HIPOTÉTICO de pontos alcançaria (usado p/ prever rebaixamento). */
export function tierParaPontos(infra: Infra, pontos: number): LoyaltyTier | undefined {
  return infra.db.tierForPoints(pontos);
}

/** Crédito disponível (vouchers não consumidos) do cliente. */
export function creditoDisponivel(infra: Infra, customerId: string): number {
  return infra.db.vouchers
    .filter((v) => v.customerId === customerId && !v.consumedAt)
    .reduce((s, v) => s + v.amountBrl, 0);
}

export function criarVoucher(
  infra: Infra,
  customerId: string,
  amountBrl: number,
  reason: string,
): Voucher {
  const v: Voucher = { id: id('vch'), customerId, amountBrl, reason, createdAt: now() };
  infra.db.vouchers.push(v);
  return v;
}

/** Reativa uma membership (usado na compensação do saga ao desfazer a renovação). */
export function reativarMembership(infra: Infra, membershipId: string, ownerId?: string): void {
  const m = buscarDoCliente(infra, membershipId, ownerId);
  if (m) {
    m.status = 'ativa';
    m.canceledReason = undefined;
    infra.db.memberships.set(m.id, m);
  }
}

/** Housekeeping (cron, fase futura): marca como 'expirada' as ativas fora da validade. */
export function expirarMemberships(infra: Infra): number {
  let n = 0;
  for (const m of infra.db.memberships.values()) {
    if (m.status === 'ativa' && m.endAt <= now()) {
      m.status = 'expirada';
      infra.db.memberships.set(m.id, m);
      n++;
    }
  }
  return n;
}

// --------------------------------------------------------------------------
// Fidelidade (pontos + nível derivado)
// --------------------------------------------------------------------------

export function saldoDePontos(infra: Infra, customerId: string): number {
  return infra.db.pointsBalance(customerId);
}

export function tierAtual(infra: Infra, customerId: string): LoyaltyTier | undefined {
  return infra.db.tierForPoints(saldoDePontos(infra, customerId));
}

/** Próximo nível acima do atual e quantos pontos faltam para alcançá-lo. */
export function proximoTier(
  infra: Infra,
  customerId: string,
): { proximo: LoyaltyTier; faltam: number } | undefined {
  const saldo = saldoDePontos(infra, customerId);
  let acima: LoyaltyTier | undefined; // menor tier acima do saldo (passada única)
  for (const t of infra.db.loyaltyTiers) {
    if (t.minPoints > saldo && (!acima || t.minPoints < acima.minPoints)) acima = t;
  }
  if (!acima) return undefined; // já está no topo
  return { proximo: acima, faltam: acima.minPoints - saldo };
}

function registrarPontos(
  infra: Infra,
  customerId: string,
  type: PointsEventType,
  delta: number,
  reason: string,
  refAppointmentId?: string,
): PointsEntry {
  const balanceAfter = infra.db.pointsBalance(customerId) + delta;
  const entry: PointsEntry = {
    id: id('pts'),
    customerId,
    type,
    delta,
    balanceAfter,
    reason,
    refAppointmentId,
    at: now(),
  };
  infra.db.pointsLedger.push(entry);
  return entry;
}

export function ganharPontos(
  infra: Infra,
  customerId: string,
  qtd: number,
  reason: string,
  refAppointmentId?: string,
): { ok: boolean; saldo?: number; erro?: string } {
  if (qtd <= 0) return { ok: false, erro: 'Quantidade de pontos inválida.' };
  const e = registrarPontos(infra, customerId, 'earn', Math.abs(qtd), reason, refAppointmentId);
  return { ok: true, saldo: e.balanceAfter };
}

export function resgatarPontos(
  infra: Infra,
  customerId: string,
  qtd: number,
  reason: string,
): { ok: boolean; saldo?: number; erro?: string } {
  if (qtd <= 0) return { ok: false, erro: 'Quantidade de pontos inválida.' };
  const saldo = infra.db.pointsBalance(customerId);
  if (qtd > saldo) {
    return { ok: false, erro: `Saldo insuficiente: você tem ${saldo} pontos.` };
  }
  const e = registrarPontos(infra, customerId, 'redeem', -Math.abs(qtd), reason);
  return { ok: true, saldo: e.balanceAfter };
}

// --------------------------------------------------------------------------
// Mutações de membership
// --------------------------------------------------------------------------

/**
 * Localiza a membership validando o dono (defense-in-depth). Quando `ownerId` é
 * informado, recusa mutar membership de outro cliente — invariante garantido na
 * própria fronteira da tool, não só na orquestração do agente.
 */
function buscarDoCliente(infra: Infra, membershipId: string, ownerId?: string): Membership | undefined {
  const m = infra.db.memberships.get(membershipId);
  if (!m) return undefined;
  if (ownerId !== undefined && m.customerId !== ownerId) return undefined;
  return m;
}

/** Dá baixa de 1 uso no pacote/assinatura. Nunca deixa o saldo negativo. */
export function usarPacote(
  infra: Infra,
  membershipId: string,
  opts: { ownerId?: string; refAppointmentId?: string } = {},
): { ok: boolean; membership?: Membership; restante?: number | null; creditouPontos?: boolean; erro?: string } {
  const m = buscarDoCliente(infra, membershipId, opts.ownerId);
  if (!m) return { ok: false, erro: 'Pacote não encontrado.' };
  if (!vigente(m)) return { ok: false, erro: 'Pacote sem saldo ou fora de validade.' };
  // Conta o uso também na assinatura ilimitada (KPI de utilização); em pacote,
  // vigente() já garante usedUses < includedUses, então nunca estoura o saldo.
  m.usedUses += 1;
  infra.db.memberships.set(m.id, m);
  // Pontos só para PACOTE finito (consumo pré-pago, bounded). Em assinatura
  // ilimitada, creditar por uso self-service permitiria farming infinito de
  // pontos — pontos de assinatura virão de atendimento concluído (fase futura).
  if (m.kind === 'pacote') {
    ganharPontos(infra, m.customerId, PONTOS_POR_USO, `uso de ${m.planName}`, opts.refAppointmentId);
  }
  return { ok: true, membership: m, restante: saldoUsos(m), creditouPontos: m.kind === 'pacote' };
}

export function comprarPacote(
  infra: Infra,
  args: {
    customerId: string;
    planName: string;
    kind?: MembershipKind;
    serviceIds: string[];
    includedUses: number | null;
    priceBrl: number;
    durationDays: number;
    autoRenew?: boolean;
  },
): { ok: boolean; membership?: Membership; erro?: string } {
  if (!args.serviceIds.length) return { ok: false, erro: 'Pacote precisa de ao menos 1 serviço.' };
  if (args.priceBrl < 0) return { ok: false, erro: 'Preço inválido.' };
  const kind = args.kind ?? 'pacote';
  if (kind === 'pacote' && (args.includedUses == null || args.includedUses <= 0)) {
    return { ok: false, erro: 'Pacote precisa de usos > 0.' };
  }
  const unit =
    args.includedUses && args.includedUses > 0 ? args.priceBrl / args.includedUses : args.priceBrl;
  const refUnit = args.serviceIds.reduce(
    (s, sid) => s + (infra.db.services.get(sid)?.priceBrl ?? 0),
    0,
  );
  const m: Membership = {
    id: id('mem'),
    customerId: args.customerId,
    planName: args.planName,
    kind,
    serviceIds: [...args.serviceIds],
    includedUses: args.includedUses,
    usedUses: 0,
    pricePaidBrl: args.priceBrl,
    unitValueBrl: unit,
    refUnitPriceBrl: refUnit,
    startAt: now(),
    endAt: now() + args.durationDays * DIA_MS,
    status: 'ativa',
    autoRenew: args.autoRenew ?? false,
  };
  infra.db.memberships.set(m.id, m);
  return { ok: true, membership: m };
}

/**
 * Renova clonando o snapshot (preserva personalização) e APOSENTA a anterior
 * (status 'expirada'), para não deixar duas vigentes em paralelo. Não renova
 * uma assinatura cancelada — cancelar exige nova compra, não renovação.
 */
export function renovarMembership(
  infra: Infra,
  membershipId: string,
  ownerId?: string,
): { ok: boolean; membership?: Membership; erro?: string } {
  const old = buscarDoCliente(infra, membershipId, ownerId);
  if (!old) return { ok: false, erro: 'Assinatura não encontrada.' };
  if (old.status === 'cancelada') {
    return { ok: false, erro: 'Esta assinatura foi cancelada — para voltar, é preciso uma nova compra.' };
  }
  // Renovar clona e zera o saldo — seguro só para assinatura ilimitada ou pacote
  // esgotado/vencido. Renovar um PACOTE com usos pré-pagos válidos os descartaria.
  if (old.kind === 'pacote' && old.includedUses != null && old.endAt > now()) {
    const restante = old.includedUses - old.usedUses;
    if (restante > 0) {
      return { ok: false, erro: `Seu pacote ainda tem ${restante} uso(s) válido(s) — use-os antes de renovar, ou compre um pacote adicional.` };
    }
  }
  const durationDays = Math.round((old.endAt - old.startAt) / DIA_MS) || 30;
  const base = Math.max(old.endAt, now()); // emenda na vigência atual se ainda vigente
  const novo: Membership = {
    ...old,
    id: id('mem'),
    serviceIds: [...old.serviceIds], // cópia defensiva (sem aliasing com a antiga)
    usedUses: 0,
    startAt: base,
    endAt: base + durationDays * DIA_MS,
    status: 'ativa',
    canceledReason: undefined,
  };
  // aposenta a anterior para não empilhar vigências
  old.status = 'expirada';
  infra.db.memberships.set(old.id, old);
  infra.db.memberships.set(novo.id, novo);
  return { ok: true, membership: novo };
}

export function cancelarMembership(
  infra: Infra,
  membershipId: string,
  motivo: string,
  ownerId?: string,
): { ok: boolean; membership?: Membership; erro?: string } {
  const m = buscarDoCliente(infra, membershipId, ownerId);
  if (!m) return { ok: false, erro: 'Assinatura não encontrada.' };
  m.status = 'cancelada';
  m.canceledReason = motivo;
  infra.db.memberships.set(m.id, m);
  return { ok: true, membership: m };
}
