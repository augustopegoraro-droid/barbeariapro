/**
 * index.ts
 * -----------------------------------------------------------------------------
 * Demonstração do BarbeariaPro.
 *
 * Simula várias conversas reais de uma barbearia, mostrando a trilha de eventos
 * (auditoria), as respostas e, ao final, as métricas globais.
 *
 * Rode com:  npm run demo
 * -----------------------------------------------------------------------------
 */

import { bootstrap, System } from './bootstrap';
import { RawInput } from './kernel/gateway';
import { Channel } from './types';

function titulo(t: string): void {
  console.log('\n\n' + '═'.repeat(72));
  console.log('  ' + t);
  console.log('═'.repeat(72));
}

async function conversa(sys: System, raw: RawInput, mostrarTrace = true): Promise<void> {
  console.log(`\n📲 [${raw.channel}] ${raw.from}: "${raw.text}"`);
  const res = await sys.kernel.handle(raw);
  console.log(`🤖 BarbeariaPro:\n${indent(res.text)}`);
  if (res.handoff) console.log(`   ↪︎ HANDOFF: ${res.handoffReason}`);
  if (mostrarTrace) {
    console.log('   ── trilha de auditoria ──');
    for (const linha of res.trace) console.log('   ' + linha);
  }
  console.log(`   ⏱  ${res.totalLatencyMs}ms  💰 US$ ${res.totalCostUsd.toFixed(4)}`);
}

function indent(s: string): string {
  return s.split('\n').map((l) => '   ' + l).join('\n');
}

const wa = (from: string, text: string): RawInput => ({ channel: 'whatsapp' as Channel, from, text });
const api = (from: string, text: string): RawInput => ({ channel: 'api' as Channel, from, text });

async function main(): Promise<void> {
  const sys = bootstrap();

  console.log('BarbeariaPro — Sistema Operacional de IA para barbearia');
  console.log('Clientes de exemplo: João (VIP, 5511999990001) e Carlos (inadimplente, 5511999990002)');

  titulo('1) Cliente VIP consulta horários (canal WhatsApp)');
  await conversa(sys, wa('5511999990001', 'Oi! Tem horário pra corte amanhã com o Rafael?'));

  titulo('2) Agendamento completo (multi-agente: Agenda → Finance → CRM)');
  await conversa(sys, wa('5511999990001', 'Quero agendar um combo amanhã às 14h com o Diego'));

  titulo('3) Cliente inadimplente tenta agendar (Policy Engine bloqueia)');
  await conversa(sys, wa('5511999990002', 'Quero marcar um corte pra amanhã'), false);

  titulo('4) Mesmo cliente pede o PIX para regularizar (permitido)');
  await conversa(sys, wa('5511999990002', 'Então me manda o pix do que eu devo'), false);

  titulo('5) Dúvida respondida com conhecimento de longo prazo (vetorial)');
  await conversa(sys, wa('5511988887777', 'Vocês abrem domingo?'), true);

  titulo('6) Cliente irritado → handoff humano automático');
  await conversa(sys, wa('5511999990001', 'Isso é um absurdo, cansei de esperar!'), false);

  titulo('7) Operador humano resolve e devolve a conversa para a IA');
  sys.kernel.retomarIA('5511999990001');
  console.log('   (atendente clicou em "Retomar IA")');
  await conversa(sys, wa('5511999990001', 'Obrigado, ficou resolvido. Quero remarcar pra depois de amanhã'), false);

  titulo('8) Campanha de marketing pelo painel interno (canal API, autorizado)');
  await conversa(sys, api('operador-1', 'disparar campanha de retorno para clientes ativos'), false);

  titulo('9) Campanha tentada por cliente comum (não autorizado → negado)');
  await conversa(sys, wa('5511988887777', 'quero disparar uma campanha de promoção'), false);

  console.log('\n\n' + '█'.repeat(72));
  console.log('  PARTE 2 — OPERAÇÃO DA RECEPÇÃO (Raquel, painel interno)');
  console.log('█'.repeat(72));
  const op = (text: string): RawInput => api('recepcao', text);

  titulo('10) Caixa: abrir o dia com fundo de troco');
  await conversa(sys, op('bom dia, abrir o caixa com 150 de troco'), false);

  titulo('11) Caixa: suprimento e sangria');
  await conversa(sys, op('fazer um suprimento de 200 no caixa'), false);
  await conversa(sys, op('registrar uma sangria de 50 do caixa'), false);

  titulo('12) Caixa: conferir saldo e movimentos');
  await conversa(sys, op('como está o caixa agora?'), false);

  titulo('13) Estoque: o que está abaixo do mínimo');
  await conversa(sys, op('quais produtos estão com estoque baixo?'), false);

  titulo('14) Estoque: dar baixa de consumo no atendimento');
  await conversa(sys, op('dar baixa de 2 pomadas que usei'), false);

  titulo('15) Estoque: repor produto que chegou');
  await conversa(sys, op('chegou 10 shampoo, pode repor'), false);

  titulo('16) Cobrança: cobrar os inadimplentes (mostra trilha)');
  await conversa(sys, op('cobrar os inadimplentes'), true);

  titulo('17) Relacionamento: reativar clientes sumidos');
  await conversa(sys, op('reativar os clientes inativos'), false);

  titulo('18) Lembretes dos agendamentos de amanhã');
  await conversa(sys, op('enviar os lembretes de amanhã'), false);

  titulo('19) Agenda em massa: o Diego faltou amanhã (mostra trilha)');
  await conversa(sys, op('o Diego faltou amanhã, remarca todos os clientes dele'), true);

  titulo('20) Caixa: fechar o dia com conferência');
  await conversa(sys, op('fechar o caixa, contei 305'), false);

  titulo('21) Segurança: cliente comum tenta abrir o caixa pelo WhatsApp (negado)');
  await conversa(sys, wa('5511988887777', 'quero abrir o caixa'), false);

  console.log('\n\n' + '█'.repeat(72));
  console.log('  PARTE 3 — PACOTES, FIDELIDADE & ASSINATURAS (cliente via WhatsApp)');
  console.log('█'.repeat(72));
  // João (5511999990001): pacote 10 cortes (3 restantes), 360 pontos (Prata).
  // Lucas (5511999990004): assinatura mensal vencendo em 5 dias.
  // Carlos (5511999990002): inadimplente.

  titulo('22) "Quantos cortes ainda tenho?" (João — pacote)');
  await conversa(sys, wa('5511999990001', 'oi, quantos cortes ainda tenho no meu pacote?'), false);

  titulo('23) "Tenho quantos pontos?" (João — fidelidade)');
  await conversa(sys, wa('5511999990001', 'tenho quantos pontos?'), false);

  titulo('24) "Quanto falta para virar Ouro?" (João — nível points-driven)');
  await conversa(sys, wa('5511999990001', 'quanto falta para eu virar ouro?'), false);

  titulo('25) "Quanto economizei?" (João)');
  await conversa(sys, wa('5511999990001', 'quanto economizei com o pacote?'), false);

  titulo('26) "Minha assinatura vence quando?" (Lucas — vence em 5 dias)');
  await conversa(sys, wa('5511999990004', 'minha assinatura vence quando?'), false);

  titulo('27) "Quero usar 100 pontos de desconto" (João — resgate via ledger)');
  await conversa(sys, wa('5511999990001', 'quero usar 100 pontos de desconto'), false);

  titulo('28) "Quero comprar outro pacote de 10 cortes" (João — saga Membership→CRM)');
  await conversa(sys, wa('5511999990001', 'quero comprar outro pacote de 10 cortes'), true);

  titulo('29) "Quero renovar" (Lucas — saga renovação)');
  await conversa(sys, wa('5511999990004', 'quero renovar minha assinatura'), false);

  titulo('30) Inadimplente tenta comprar pacote (Policy bloqueia)');
  await conversa(sys, wa('5511999990002', 'quero comprar um pacote de 10 cortes'), false);

  titulo('31) "Quero usar um corte do meu pacote" (João — baixa de uso + pontos)');
  await conversa(sys, wa('5511999990001', 'quero usar um corte do meu pacote'), false);

  // Métricas finais
  console.log('\n');
  console.log(sys.metrics.resumo());
}

main().catch((e) => {
  console.error('Erro fatal na demo:', e);
  process.exit(1);
});
