/**
 * __tests__/membership.kernel.test.ts
 * -----------------------------------------------------------------------------
 * Testes de integração via Kernel: intent → policy → planner → executor.
 * Cobre o MembershipAgent, as Policies e o saga (Membership→CRM).
 * -----------------------------------------------------------------------------
 */

import { test } from 'node:test';
import assert from 'node:assert/strict';

import { bootstrap } from '../bootstrap';
import { RawInput } from '../kernel/gateway';
import { Channel } from '../types';

const wa = (from: string, text: string): RawInput => ({ channel: 'whatsapp' as Channel, from, text });

test('classifica e responde "quantos cortes tenho" (consultar_pacote)', async () => {
  const sys = bootstrap();
  const res = await sys.kernel.handle(wa('5511999990001', 'quantos cortes ainda tenho?'));
  assert.equal(res.ok, true);
  assert.match(res.text, /3 uso/);
});

test('nível points-driven: "falta para ouro" → Prata, faltam 140', async () => {
  const sys = bootstrap();
  const res = await sys.kernel.handle(wa('5511999990001', 'quanto falta para virar ouro?'));
  assert.match(res.text, /Prata/);
  assert.match(res.text, /140/);
});

test('resgatar pontos (sem rebaixar) debita e gera crédito', async () => {
  const sys = bootstrap();
  const res = await sys.kernel.handle(wa('5511999990001', 'quero usar 100 pontos de desconto'));
  assert.match(res.text, /cr[ée]dito de R\$\s*100/);
  assert.match(res.text, /260/); // saldo após o resgate
  assert.equal(sys.infra.db.pointsBalance('c1'), 260);
});

test('resgate que REBAIXARIA o nível pede confirmação e NÃO debita', async () => {
  const sys = bootstrap();
  const res = await sys.kernel.handle(wa('5511999990001', 'quero usar 200 pontos de desconto'));
  assert.match(res.text, /rebaixar de Prata para Bronze/);
  assert.match(res.text, /Confirma\?/);
  assert.equal(sys.infra.db.pointsBalance('c1'), 360); // nada debitado
});

test('confirmação multi-turn: rebaixa pede confirmação e "sim" conclui (sem re-digitar)', async () => {
  const sys = bootstrap();
  const r1 = await sys.kernel.handle(wa('5511999990001', 'quero usar 200 pontos de desconto'));
  assert.match(r1.text, /Confirma\?/);
  assert.equal(sys.infra.db.pointsBalance('c1'), 360);
  const r2 = await sys.kernel.handle(wa('5511999990001', 'sim'));
  assert.match(r2.text, /Prata para Bronze/);
  assert.equal(sys.infra.db.pointsBalance('c1'), 160);
});

test('confirmação multi-turn: pergunta a quantidade e aceita número puro depois', async () => {
  const sys = bootstrap();
  const r1 = await sys.kernel.handle(wa('5511999990001', 'quero resgatar pontos'));
  assert.match(r1.text, /Quantos pontos/);
  const r2 = await sys.kernel.handle(wa('5511999990001', '100'));
  assert.match(r2.text, /cr[ée]dito de R\$\s*100/);
  assert.equal(sys.infra.db.pointsBalance('c1'), 260);
});

test('confirmação NÃO é burlada por afirmação ambígua ou negada', async () => {
  for (const frase of ['claro que não!', 'pode cancelar isso?', 'isso é um absurdo, não quero perder meu nível']) {
    const sys = bootstrap();
    await sys.kernel.handle(wa('5511999990001', 'quero usar 200 pontos de desconto')); // pendente (rebaixa)
    await sys.kernel.handle(wa('5511999990001', frase));
    assert.equal(sys.infra.db.pointsBalance('c1'), 360, `não pode debitar em: "${frase}"`);
  }
});

test('pedido genérico de renovar com pacote E assinatura ativos pede desambiguação', async () => {
  const sys = bootstrap();
  await sys.kernel.handle(wa('5511999990001', 'quero assinar um plano mensal')); // João: pacote (seed) + assinatura
  const res = await sys.kernel.handle(wa('5511999990001', 'quero renovar'));
  assert.match(res.text, /Qual quer renovar/);
  assert.equal(sys.infra.db.memberships.get('mem_joao')?.status, 'ativa'); // nada alterado
});

test('durante a confirmação, um número DIFERENTE não é tratado como "sim"', async () => {
  const sys = bootstrap();
  await sys.kernel.handle(wa('5511999990001', 'quero usar 200 pontos de desconto')); // pendente 200 (rebaixa)
  const r = await sys.kernel.handle(wa('5511999990001', '300')); // valor diferente, também rebaixa
  assert.match(r.text, /Confirma\?/); // re-pergunta, não debita
  assert.equal(sys.infra.db.pointsBalance('c1'), 360);
  const r2 = await sys.kernel.handle(wa('5511999990001', 'sim'));
  assert.equal(sys.infra.db.pointsBalance('c1'), 60); // só agora debita os 300
});

test('número retomado que REBAIXA ainda pede confirmação (não burla a salvaguarda)', async () => {
  const sys = bootstrap();
  await sys.kernel.handle(wa('5511999990001', 'quero resgatar pontos')); // pergunta a quantidade
  const r2 = await sys.kernel.handle(wa('5511999990001', '200')); // rebaixaria Prata→Bronze
  assert.match(r2.text, /Confirma\?/);
  assert.equal(sys.infra.db.pointsBalance('c1'), 360); // NÃO debitou sem confirmar
  const r3 = await sys.kernel.handle(wa('5511999990001', 'sim'));
  assert.equal(sys.infra.db.pointsBalance('c1'), 160); // só agora debitou
});

test('confirmação pendente é descartada se o cliente muda de assunto', async () => {
  const sys = bootstrap();
  await sys.kernel.handle(wa('5511999990001', 'quero usar 200 pontos de desconto')); // pendente
  const res = await sys.kernel.handle(wa('5511999990001', 'quantos cortes ainda tenho?'));
  assert.match(res.text, /uso\(s\) restante/); // tratou como consulta, não como resgate
  assert.equal(sys.infra.db.pointsBalance('c1'), 360); // nada debitado
});

test('cancelar tipo INEXISTENTE não age sobre o outro tipo (não destrói o que não foi pedido)', async () => {
  const sys = bootstrap();
  // Lucas (c4) só tem assinatura; pedir para cancelar o "pacote" não pode cancelar a assinatura.
  const res = await sys.kernel.handle(wa('5511999990004', 'quero cancelar meu pacote'));
  assert.doesNotMatch(res.text, /Cancelado/);
  const ass = [...sys.infra.db.memberships.values()].find((m) => m.customerId === 'c4' && m.kind === 'assinatura');
  assert.equal(ass?.status, 'ativa'); // assinatura intacta
});

test('resposta ambígua durante confirmação RE-PERGUNTA mantendo o pendente (não descarta em silêncio)', async () => {
  const sys = bootstrap();
  await sys.kernel.handle(wa('5511999990001', 'quero usar 200 pontos de desconto')); // pendente 200 (rebaixa)
  const r = await sys.kernel.handle(wa('5511999990001', 'talvez'));
  assert.match(r.text, /confirmar o resgate de 200/);
  assert.equal(sys.infra.db.pointsBalance('c1'), 360); // ainda não debitou
  const r2 = await sys.kernel.handle(wa('5511999990001', 'sim')); // pendente preservado
  assert.equal(sys.infra.db.pointsBalance('c1'), 160);
});

test('multi-turn: "sim, pode confirmar o resgate" (não-exato) conclui mesmo assim', async () => {
  const sys = bootstrap();
  await sys.kernel.handle(wa('5511999990001', 'quero usar 200 pontos de desconto'));
  const r = await sys.kernel.handle(wa('5511999990001', 'sim, pode confirmar o resgate'));
  assert.equal(sys.infra.db.pointsBalance('c1'), 160);
  assert.match(r.text, /Prata para Bronze/);
});

test('cancelar nomeando o tipo cancela o PACOTE (não a assinatura)', async () => {
  const sys = bootstrap();
  await sys.kernel.handle(wa('5511999990001', 'quero assinar um plano mensal')); // João passa a ter os dois
  const res = await sys.kernel.handle(wa('5511999990001', 'quero cancelar meu pacote'));
  assert.match(res.text, /10 Cortes/);
  assert.equal(sys.infra.db.memberships.get('mem_joao')?.status, 'cancelada');
  const ass = [...sys.infra.db.memberships.values()].find((m) => m.customerId === 'c1' && m.kind === 'assinatura');
  assert.equal(ass?.status, 'ativa'); // assinatura intacta
});

test('consultar_nivel no topo informa nível máximo', async () => {
  const sys = bootstrap();
  sys.infra.db.pointsLedger.push({ id: 'tm', customerId: 'c1', type: 'earn', delta: 2000, balanceAfter: 2360, reason: 't', at: Date.now() });
  const res = await sys.kernel.handle(wa('5511999990001', 'qual o meu nivel?'));
  assert.match(res.text, /m[áa]ximo|Black/);
});

test('resgate que rebaixa só debita após confirmação em 2 turnos (gera voucher)', async () => {
  const sys = bootstrap();
  const r1 = await sys.kernel.handle(wa('5511999990001', 'quero resgatar 200 pontos'));
  assert.match(r1.text, /Confirma\?/);
  assert.equal(sys.infra.db.pointsBalance('c1'), 360); // ainda não debitou
  const r2 = await sys.kernel.handle(wa('5511999990001', 'sim'));
  assert.match(r2.text, /Prata para Bronze/);
  assert.equal(sys.infra.db.pointsBalance('c1'), 160);
  const vouchers = sys.infra.db.vouchers.filter((v) => v.customerId === 'c1');
  assert.equal(vouchers.length, 1);
  assert.equal(vouchers[0].amountBrl, 200);
});

test('"confirmado" de texto livre NÃO burla o gate de rebaixamento', async () => {
  const sys = bootstrap();
  // confirma a IDENTIDADE, não o rebaixamento — deve pedir confirmação, não debitar.
  const res = await sys.kernel.handle(wa('5511999990001', 'quero resgatar 200 pontos, confirmo que sou o Joao'));
  assert.match(res.text, /Confirma\?/);
  assert.equal(sys.infra.db.pointsBalance('c1'), 360);
});

test('desambiguação: responder "o pacote" conclui a ação no tipo escolhido', async () => {
  const sys = bootstrap();
  await sys.kernel.handle(wa('5511999990001', 'quero assinar um plano mensal')); // João: pacote + assinatura
  const r1 = await sys.kernel.handle(wa('5511999990001', 'quero cancelar plano'));
  assert.match(r1.text, /Qual quer cancelar/);
  const r2 = await sys.kernel.handle(wa('5511999990001', 'o pacote'));
  assert.match(r2.text, /Cancelado/);
  assert.equal(sys.infra.db.memberships.get('mem_joao')?.status, 'cancelada');
  const ass = [...sys.infra.db.memberships.values()].find((m) => m.customerId === 'c1' && m.kind === 'assinatura');
  assert.equal(ass?.status, 'ativa'); // a assinatura ficou intacta
});

test('eventos de negócio são emitidos no Event Bus (auditoria)', async () => {
  const sys = bootstrap();
  const eventos: string[] = [];
  sys.bus.subscribe((e) => eventos.push(e.type));
  await sys.kernel.handle(wa('5511999990001', 'quero comprar outro pacote de 10 cortes'));
  assert.ok(eventos.includes('PackageSold'), 'esperava evento PackageSold');
});

test('comprar assinatura via WhatsApp cria membership ilimitada com autoRenew', async () => {
  const sys = bootstrap();
  await sys.kernel.handle(wa('5511999990003', 'quero assinar um plano mensal')); // Pedro (sem membership)
  const ass = [...sys.infra.db.memberships.values()].find((m) => m.customerId === 'c3' && m.kind === 'assinatura');
  assert.ok(ass, 'esperava uma assinatura criada');
  assert.equal(ass!.includedUses, null);
  assert.equal(ass!.autoRenew, true);
});

test('consumo de pacote é FIFO: dá baixa no que vence primeiro', async () => {
  const sys = bootstrap();
  await sys.kernel.handle(wa('5511999990001', 'quero comprar outro pacote de 10 cortes')); // vence em 90d
  const res = await sys.kernel.handle(wa('5511999990001', 'quero usar um corte do meu pacote'));
  assert.match(res.text, /10 Cortes/); // o pacote do seed (vence em 60d), não o novo
  assert.match(res.text, /2 restante/);
});

test('comprar_pacote roda saga de 2 passos (Membership → CRM)', async () => {
  const sys = bootstrap();
  const res = await sys.kernel.handle(wa('5511999990001', 'quero comprar outro pacote de 10 cortes'));
  assert.equal(res.ok, true);
  assert.equal(res.steps.length, 2);
  assert.deepEqual(res.steps.map((s) => s.agent), ['MembershipAgent', 'CrmAgent']);
  assert.ok(res.steps.every((s) => s.ok));
});

test('Policy bloqueia inadimplente de comprar pacote', async () => {
  const sys = bootstrap();
  const res = await sys.kernel.handle(wa('5511999990002', 'quero comprar um pacote de 10 cortes'));
  assert.match(res.text, /pend[êe]ncia/i);
  assert.equal(res.steps.length, 0); // não executou nenhum agente
});

test('sem identificar o cliente, pede o nome (halt)', async () => {
  const sys = bootstrap();
  const res = await sys.kernel.handle(wa('5511900000000', 'quantos cortes tenho?'));
  assert.match(res.text, /identificar|nome/i);
});

test('assinatura vencendo avisa o cliente', async () => {
  const sys = bootstrap();
  const res = await sys.kernel.handle(wa('5511999990004', 'minha assinatura vence quando?'));
  assert.match(res.text, /Mensal Premium/);
  assert.match(res.text, /vence em breve/);
});

test('não há regressão: agendamento multi-agente segue funcionando', async () => {
  const sys = bootstrap();
  const res = await sys.kernel.handle(wa('5511999990001', 'quero agendar um combo amanhã às 14h com o Diego'));
  assert.equal(res.ok, true);
  assert.match(res.text, /Agendado/);
});

test('usar_pacote é alcançável por linguagem natural (não cai em consultar/operacional)', async () => {
  const sys = bootstrap();
  const res = await sys.kernel.handle(wa('5511999990001', 'quero usar um corte do meu pacote'));
  assert.match(res.text, /Uso registrado/);
  assert.match(res.text, /2 restante/); // 3 → 2
});

test('saga rollback: se o CRM falhar, a compra criada é desfeita (compensate)', async () => {
  const sys = bootstrap();
  const crm = sys.registry.get('CrmAgent');
  assert.ok(crm);
  crm.execute = async () => ({ ok: false, error: 'falha forçada no CRM' });

  const res = await sys.kernel.handle(wa('5511999990001', 'quero comprar outro pacote de 10 cortes'));
  assert.equal(res.handoff, true); // workflow falhou → handoff humano
  const rollbacked = [...sys.infra.db.memberships.values()].filter(
    (m) => m.customerId === 'c1' && m.canceledReason === 'rollback (saga)',
  );
  assert.equal(rollbacked.length, 1); // a compra foi desfeita
  assert.equal(rollbacked[0].status, 'cancelada');
});

test('saga rollback de RENOVAÇÃO restaura a assinatura antiga (não perde o cliente)', async () => {
  const sys = bootstrap();
  const crm = sys.registry.get('CrmAgent');
  assert.ok(crm);
  crm.execute = async () => ({ ok: false, error: 'falha forçada no CRM' });

  await sys.kernel.handle(wa('5511999990004', 'quero renovar minha assinatura'));
  // a antiga (mem_lucas) deve voltar a 'ativa' e o cliente ficar com exatamente 1 ativa
  assert.equal(sys.infra.db.memberships.get('mem_lucas')?.status, 'ativa');
  const ativas = [...sys.infra.db.memberships.values()].filter(
    (m) => m.customerId === 'c4' && m.status === 'ativa',
  );
  assert.equal(ativas.length, 1);
});

test('inadimplente PODE consultar os próprios dados (só não compra/renova)', async () => {
  const sys = bootstrap();
  const res = await sys.kernel.handle(wa('5511999990002', 'tenho quantos pontos?'));
  assert.doesNotMatch(res.text, /pend[êe]ncia/i);
  assert.match(res.text, /ponto/);
});

test('assinante consegue usar o plano (não exige pacote finito)', async () => {
  const sys = bootstrap();
  const res = await sys.kernel.handle(wa('5511999990004', 'quero usar um corte do meu plano'));
  assert.match(res.text, /Uso registrado/);
  assert.match(res.text, /ilimitado/);
});

test('uso de assinatura ilimitada NÃO credita pontos (anti-farming)', async () => {
  const sys = bootstrap();
  for (let i = 0; i < 5; i++) {
    await sys.kernel.handle(wa('5511999990004', 'quero usar um corte do meu plano'));
  }
  assert.equal(sys.infra.db.pointsBalance('c4'), 0); // nenhum ponto auto-creditado
});

test('usar que cruza o limiar de pontos AVISA a subida de nível', async () => {
  const sys = bootstrap();
  // leva João a 480 pts (Prata); +40 do uso → 520 = Ouro
  sys.infra.db.pointsLedger.push({ id: 't480', customerId: 'c1', type: 'earn', delta: 120, balanceAfter: 480, reason: 'teste', at: Date.now() });
  const res = await sys.kernel.handle(wa('5511999990001', 'quero usar um corte do meu pacote'));
  assert.match(res.text, /subiu para o n[íi]vel Ouro/);
});

test('"renovar minha assinatura" (sem "quero") roteia para renovação, não consulta', async () => {
  const sys = bootstrap();
  const res = await sys.kernel.handle(wa('5511999990004', 'renovar minha assinatura'));
  assert.match(res.text, /Renovado/);
});

test('inadimplente PODE resgatar os próprios pontos (gera crédito)', async () => {
  const sys = bootstrap();
  sys.infra.db.pointsLedger.push({ id: 'tc', customerId: 'c2', type: 'earn', delta: 50, balanceAfter: 50, reason: 'teste', at: Date.now() });
  const res = await sys.kernel.handle(wa('5511999990002', 'quero usar 30 pontos de desconto'));
  assert.doesNotMatch(res.text, /pend[êe]ncia/i);
  assert.match(res.text, /cr[ée]dito/);
});

test('pacote esgotado-porém-vigente é distinguido de "não tem pacote"', async () => {
  const sys = bootstrap();
  const m = sys.infra.db.memberships.get('mem_joao')!;
  m.usedUses = m.includedUses!; // 10/10, ainda dentro da validade
  const res = await sys.kernel.handle(wa('5511999990001', 'quantos cortes ainda tenho?'));
  assert.match(res.text, /esgotado/);
});

test('renovar não deixa leitura stale: consultar mostra a vigência NOVA', async () => {
  const sys = bootstrap();
  await sys.kernel.handle(wa('5511999990004', 'quero renovar minha assinatura')); // vencia em 5d → +30d
  const res = await sys.kernel.handle(wa('5511999990004', 'minha assinatura vence quando?'));
  assert.match(res.text, /3[0-9] dia/); // ~35 dias, não os 5 antigos
  assert.doesNotMatch(res.text, /vence em breve/);
  const ativas = [...sys.infra.db.memberships.values()].filter(
    (m) => m.customerId === 'c4' && m.kind === 'assinatura' && m.status === 'ativa',
  );
  assert.equal(ativas.length, 1); // não empilhou duas vigências
});
