/**
 * __tests__/membership.tools.test.ts
 * -----------------------------------------------------------------------------
 * Testes unitários das ferramentas de pacote/fidelidade (funções puras).
 * Roda com: npm test  (node:test via ts-node)
 * -----------------------------------------------------------------------------
 */

import { test } from 'node:test';
import assert from 'node:assert/strict';

import { Infra } from '../infra/store';
import { seed } from '../infra/seed';
import {
  cancelarMembership, comprarPacote, criarVoucher, creditoDisponivel, economiaTotal,
  expirarMemberships, ganharPontos, pacoteAtivo, proximoTier, renovarMembership, resgatarPontos,
  saldoDePontos, saldoUsos, tierAtual, usarPacote,
} from '../tools/membership.tools';

function novaInfra(): Infra {
  const infra = new Infra();
  seed(infra);
  return infra;
}

test('saldo de pontos vem do ledger (seed João = 360)', () => {
  const infra = novaInfra();
  assert.equal(saldoDePontos(infra, 'c1'), 360);
});

test('ganharPontos é append-only e atualiza balanceAfter', () => {
  const infra = novaInfra();
  const antes = infra.db.pointsLedger.length;
  const r = ganharPontos(infra, 'c1', 40, 'teste');
  assert.equal(r.ok, true);
  assert.equal(r.saldo, 400);
  assert.equal(infra.db.pointsLedger.length, antes + 1);
  assert.equal(infra.db.pointsLedger.at(-1)?.balanceAfter, 400);
});

test('resgatarPontos nunca deixa saldo negativo', () => {
  const infra = novaInfra();
  const r = resgatarPontos(infra, 'c1', 10_000, 'desconto');
  assert.equal(r.ok, false);
  assert.equal(saldoDePontos(infra, 'c1'), 360); // inalterado
});

test('resgatarPontos debita via ledger quando há saldo', () => {
  const infra = novaInfra();
  const r = resgatarPontos(infra, 'c1', 100, 'desconto');
  assert.equal(r.ok, true);
  assert.equal(r.saldo, 260);
  assert.equal(infra.db.pointsLedger.at(-1)?.type, 'redeem');
  assert.equal(infra.db.pointsLedger.at(-1)?.delta, -100);
});

test('nível deriva do saldo (points-driven): 360 = Prata; faltam 140 p/ Ouro', () => {
  const infra = novaInfra();
  assert.equal(tierAtual(infra, 'c1')?.name, 'Prata');
  const prox = proximoTier(infra, 'c1');
  assert.equal(prox?.proximo.name, 'Ouro');
  assert.equal(prox?.faltam, 140);
});

test('usarPacote decrementa saldo, credita 40 pontos e nunca passa do incluído', () => {
  const infra = novaInfra();
  const m = pacoteAtivo(infra, 'c1')!;
  assert.equal(saldoUsos(m), 3);
  const r = usarPacote(infra, m.id);
  assert.equal(r.ok, true);
  assert.equal(r.restante, 2);
  assert.equal(saldoDePontos(infra, 'c1'), 400); // +40 pelo uso
});

test('usarPacote falha sem saldo (não fica negativo)', () => {
  const infra = novaInfra();
  const m = pacoteAtivo(infra, 'c1')!;
  usarPacote(infra, m.id);
  usarPacote(infra, m.id);
  const terceiro = usarPacote(infra, m.id); // zera (3 usos)
  assert.equal(terceiro.restante, 0);
  const quarto = usarPacote(infra, m.id); // já sem saldo
  assert.equal(quarto.ok, false);
});

test('economiaTotal: pacote 10 cortes, 7 usos, R$10/uso = R$70', () => {
  const infra = novaInfra();
  assert.equal(economiaTotal(infra, 'c1'), 70);
});

test('comprarPacote cria membership com valor por uso correto', () => {
  const infra = novaInfra();
  const r = comprarPacote(infra, {
    customerId: 'c2', planName: '5 Cortes', serviceIds: ['s_corte'],
    includedUses: 5, priceBrl: 200, durationDays: 90,
  });
  assert.equal(r.ok, true);
  assert.equal(r.membership?.unitValueBrl, 40);
  assert.equal(r.membership?.status, 'ativa');
});

test('renovarMembership clona snapshot, zera usos e estende validade', () => {
  const infra = novaInfra();
  const r = renovarMembership(infra, 'mem_lucas');
  assert.equal(r.ok, true);
  assert.notEqual(r.membership?.id, 'mem_lucas');
  assert.equal(r.membership?.usedUses, 0);
  assert.equal(r.membership?.planName, 'Mensal Premium');
  assert.ok((r.membership?.endAt ?? 0) > infra.db.memberships.get('mem_lucas')!.endAt);
});

test('cancelarMembership marca status e motivo', () => {
  const infra = novaInfra();
  const r = cancelarMembership(infra, 'mem_joao', 'teste');
  assert.equal(r.ok, true);
  assert.equal(infra.db.memberships.get('mem_joao')?.status, 'cancelada');
  assert.equal(infra.db.memberships.get('mem_joao')?.canceledReason, 'teste');
});

test('renovar aposenta a anterior — não deixa duas vigências ativas', () => {
  const infra = novaInfra();
  renovarMembership(infra, 'mem_lucas');
  assert.equal(infra.db.memberships.get('mem_lucas')?.status, 'expirada');
  const ativas = infra.db.membershipsForCustomer('c4').filter((m) => m.status === 'ativa');
  assert.equal(ativas.length, 1);
});

test('renovar uma assinatura CANCELADA é rejeitado (exige nova compra)', () => {
  const infra = novaInfra();
  cancelarMembership(infra, 'mem_lucas', 'cliente');
  const r = renovarMembership(infra, 'mem_lucas');
  assert.equal(r.ok, false);
});

test('renovar PACOTE com usos restantes é bloqueado (não descarta o pré-pago)', () => {
  const infra = novaInfra();
  const r = renovarMembership(infra, 'mem_joao'); // 3 usos restantes, vigente
  assert.equal(r.ok, false);
  assert.equal(infra.db.memberships.get('mem_joao')?.status, 'ativa'); // intacto
});

test('uso de assinatura ilimitada não credita pontos (tool)', () => {
  const infra = novaInfra();
  const r = usarPacote(infra, 'mem_lucas'); // assinatura
  assert.equal(r.ok, true);
  assert.equal(r.creditouPontos, false);
  assert.equal(saldoDePontos(infra, 'c4'), 0);
});

test('membership vencida por data é excluída de pacoteAtivo', () => {
  const infra = novaInfra();
  const m = infra.db.memberships.get('mem_joao')!;
  m.endAt = Date.now() - 1000; // venceu
  assert.equal(pacoteAtivo(infra, 'c1'), undefined);
});

test('renovar não compartilha referência de serviceIds com a antiga', () => {
  const infra = novaInfra();
  const r = renovarMembership(infra, 'mem_lucas');
  assert.notEqual(r.membership?.serviceIds, infra.db.memberships.get('mem_lucas')?.serviceIds);
});

test('expirarMemberships marca como expirada o que está fora da validade', () => {
  const infra = novaInfra();
  infra.db.memberships.get('mem_joao')!.endAt = Date.now() - 1000;
  const n = expirarMemberships(infra);
  assert.equal(n, 1);
  assert.equal(infra.db.memberships.get('mem_joao')?.status, 'expirada');
});

test('criarVoucher acumula crédito disponível do cliente', () => {
  const infra = novaInfra();
  criarVoucher(infra, 'c1', 50, 'teste');
  criarVoucher(infra, 'c1', 30, 'teste');
  assert.equal(creditoDisponivel(infra, 'c1'), 80);
});

test('economiaTotal usa o preço avulso de referência (pacote multi-serviço)', () => {
  const infra = novaInfra();
  // Pedro (c3) não tem outro pacote no seed; combo: refUnit 45+35=80, unit 60 → 20/uso
  const r = comprarPacote(infra, {
    customerId: 'c3', planName: 'Combo 5', serviceIds: ['s_corte', 's_barba'],
    includedUses: 5, priceBrl: 300, durationDays: 90,
  });
  r.membership!.usedUses = 2;
  assert.equal(economiaTotal(infra, 'c3'), 40);
});

test('comprarPacote rejeita pacote sem usos (includedUses inválido)', () => {
  const infra = novaInfra();
  const r = comprarPacote(infra, {
    customerId: 'c1', planName: 'X', serviceIds: ['s_corte'],
    includedUses: 0, priceBrl: 100, durationDays: 90,
  });
  assert.equal(r.ok, false);
});

test('tools de mutação recusam membership de outro dono (defense-in-depth)', () => {
  const infra = novaInfra();
  const r = usarPacote(infra, 'mem_joao', { ownerId: 'c4' }); // mem_joao é do c1
  assert.equal(r.ok, false);
  const c = cancelarMembership(infra, 'mem_joao', 'x', 'c4');
  assert.equal(c.ok, false);
  assert.equal(infra.db.memberships.get('mem_joao')?.status, 'ativa'); // intacto
});
