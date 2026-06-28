/**
 * infra/seed.ts
 * -----------------------------------------------------------------------------
 * Popula a infraestrutura com dados de exemplo de uma barbearia real.
 * -----------------------------------------------------------------------------
 */

import { Infra } from './store';

const HOJE = new Date();
HOJE.setHours(0, 0, 0, 0);

function diaUtil(offsetDias: number, hora: number): number {
  const d = new Date(HOJE);
  d.setDate(d.getDate() + offsetDias);
  // pula domingo (0) e segunda (1), dias fechados
  while (d.getDay() === 0 || d.getDay() === 1) {
    d.setDate(d.getDate() + 1);
  }
  d.setHours(hora, 0, 0, 0);
  return d.getTime();
}

export function seed(infra: Infra): void {
  const { db, vector } = infra;

  // Barbeiros
  db.barbers.set('b1', { id: 'b1', name: 'Rafael', active: true });
  db.barbers.set('b2', { id: 'b2', name: 'Diego', active: true });

  // Serviços
  db.services.set('s_corte', { id: 's_corte', name: 'Corte', durationMin: 30, priceBrl: 45 });
  db.services.set('s_barba', { id: 's_barba', name: 'Barba', durationMin: 30, priceBrl: 35 });
  db.services.set('s_combo', { id: 's_combo', name: 'Combo (corte + barba)', durationMin: 60, priceBrl: 70 });

  // Clientes
  db.customers.set('c1', {
    id: 'c1',
    name: 'João Mendes',
    phone: '5511999990001',
    vip: true,
    inadimplente: false,
    notes: ['Prefere o Rafael', 'Gosta de máquina 2 nas laterais'],
    createdAt: Date.now(),
  });
  db.customers.set('c2', {
    id: 'c2',
    name: 'Carlos Souza',
    phone: '5511999990002',
    vip: false,
    inadimplente: true,
    notes: ['Tem 1 cobrança em aberto'],
    createdAt: Date.now(),
  });
  db.customers.set('c3', {
    id: 'c3',
    name: 'Pedro Lima',
    phone: '5511999990003',
    vip: false,
    inadimplente: false,
    notes: ['Não aparece há um tempo'],
    createdAt: Date.now(),
  });
  db.customers.set('c4', {
    id: 'c4',
    name: 'Lucas Alves',
    phone: '5511999990004',
    vip: false,
    inadimplente: false,
    notes: [],
    createdAt: Date.now(),
  });

  // Um horário já ocupado do Rafael amanhã às 10h
  db.appointments.set('a1', {
    id: 'a1',
    customerId: 'c1',
    barberId: 'b1',
    serviceId: 's_corte',
    start: diaUtil(1, 10),
    end: diaUtil(1, 10) + 30 * 60_000,
    status: 'confirmado',
  });

  // Agenda do Diego amanhã (Carlos 11h, Lucas 16h) — usada no reagendamento em massa
  db.appointments.set('a2', {
    id: 'a2',
    customerId: 'c2',
    barberId: 'b2',
    serviceId: 's_corte',
    start: diaUtil(1, 11),
    end: diaUtil(1, 11) + 30 * 60_000,
    status: 'confirmado',
  });
  db.appointments.set('a3', {
    id: 'a3',
    customerId: 'c4',
    barberId: 'b2',
    serviceId: 's_combo',
    start: diaUtil(1, 16),
    end: diaUtil(1, 16) + 60 * 60_000,
    status: 'confirmado',
  });

  // Atendimento antigo do Pedro (60 dias atrás) — deixa-o "inativo" p/ reativação
  const sessentaDias = HOJE.getTime() - 60 * 24 * 60 * 60_000;
  db.appointments.set('a_old', {
    id: 'a_old',
    customerId: 'c3',
    barberId: 'b1',
    serviceId: 's_corte',
    start: sessentaDias,
    end: sessentaDias + 30 * 60_000,
    status: 'concluido',
  });

  // Cobrança pendente real do Carlos (inadimplente)
  db.payments.set('pay_c2', {
    id: 'pay_c2',
    customerId: 'c2',
    amountBrl: 45,
    method: 'pix',
    status: 'pendente',
    pixCode: '00020126BR.GOV.BCB.PIXCARLOS0001',
    createdAt: Date.now() - 3 * 24 * 60 * 60_000,
  });

  // Produtos / estoque (pomada e shampoo já abaixo do mínimo)
  db.products.set('p_pomada', { id: 'p_pomada', name: 'Pomada modeladora', priceBrl: 39.9, stockQty: 3, minQty: 5, unit: 'un' });
  db.products.set('p_gel', { id: 'p_gel', name: 'Gel fixador', priceBrl: 24.9, stockQty: 12, minQty: 4, unit: 'un' });
  db.products.set('p_shampoo', { id: 'p_shampoo', name: 'Shampoo barba', priceBrl: 34.9, stockQty: 1, minQty: 3, unit: 'frasco' });
  db.products.set('p_lamina', { id: 'p_lamina', name: 'Lâmina descartável', priceBrl: 2.5, stockQty: 50, minQty: 20, unit: 'un' });

  // Níveis de fidelidade (configuráveis — points-driven)
  db.loyaltyTiers = [
    { name: 'Bronze', minPoints: 0, discountPct: 0, perks: ['acúmulo de pontos'] },
    { name: 'Prata', minPoints: 200, discountPct: 0.05, perks: ['5% de desconto'] },
    { name: 'Ouro', minPoints: 500, discountPct: 0.1, perks: ['10% de desconto', 'prioridade de encaixe'] },
    { name: 'Diamante', minPoints: 1000, discountPct: 0.15, perks: ['15% de desconto', 'brinde mensal'] },
    { name: 'Black', minPoints: 2000, discountPct: 0.2, perks: ['20% de desconto', 'atendimento exclusivo'] },
  ];

  const DIA = 24 * 60 * 60_000;

  // João (c1): pacote de 10 cortes, 7 usados (3 restantes), válido +60 dias
  db.memberships.set('mem_joao', {
    id: 'mem_joao',
    customerId: 'c1',
    planName: '10 Cortes',
    kind: 'pacote',
    serviceIds: ['s_corte'],
    includedUses: 10,
    usedUses: 7,
    pricePaidBrl: 350,
    unitValueBrl: 35, // 350 / 10 (avulso 45 → economia R$10/uso)
    refUnitPriceBrl: 45, // preço avulso do corte
    startAt: Date.now() - 30 * DIA,
    endAt: Date.now() + 60 * DIA,
    status: 'ativa',
    autoRenew: false,
  });

  // Lucas (c4): assinatura mensal ilimitada vencendo em 5 dias (auto-renovação)
  db.memberships.set('mem_lucas', {
    id: 'mem_lucas',
    customerId: 'c4',
    planName: 'Mensal Premium',
    kind: 'assinatura',
    serviceIds: ['s_corte', 's_barba'],
    includedUses: null,
    usedUses: 4,
    pricePaidBrl: 199,
    unitValueBrl: 199,
    refUnitPriceBrl: 80, // corte + barba avulsos (assinatura não entra na economia)
    startAt: Date.now() - 25 * DIA,
    endAt: Date.now() + 5 * DIA,
    status: 'ativa',
    autoRenew: true,
  });

  // Ledger de pontos do João (append-only): 80 boas-vindas + 280 atendimentos = 360 → Prata
  db.pointsLedger.push(
    { id: 'pts_1', customerId: 'c1', type: 'earn', delta: 80, balanceAfter: 80, reason: 'bônus de boas-vindas', at: Date.now() - 30 * DIA },
    { id: 'pts_2', customerId: 'c1', type: 'earn', delta: 280, balanceAfter: 360, reason: 'atendimentos do pacote', at: Date.now() - 5 * DIA },
  );

  // Base de conhecimento (longo prazo / vetorial)
  vector.add('A barbearia funciona de terça a sábado, das 9h às 19h. Fechado domingo e segunda.');
  vector.add('Formas de pagamento: PIX, cartão e dinheiro. PIX tem 5% de desconto.');
  vector.add('Cancelamentos com menos de 2 horas de antecedência podem ter cobrança de taxa.');
  vector.add('Clientes VIP têm prioridade de encaixe e atendimento.');
  vector.add('O combo de corte e barba dura cerca de 1 hora.');
  vector.add('Pacotes: 10 cortes, 10 barbas, ou combos. Pague adiantado e economize ~20%.');
  vector.add('Assinatura mensal: usos ilimitados de corte e barba, com renovação automática.');
  vector.add('Fidelidade: ganhe 40 pontos por atendimento. Níveis Bronze, Prata, Ouro, Diamante e Black. 1 ponto = R$ 1 de desconto.');
}
