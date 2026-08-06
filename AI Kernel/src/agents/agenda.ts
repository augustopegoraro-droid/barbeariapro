/**
 * agents/agenda.ts
 * -----------------------------------------------------------------------------
 * Agenda Agent — responsável APENAS por horários e agendamentos.
 * Nunca acessa módulos financeiros (regra do projeto).
 * -----------------------------------------------------------------------------
 */

import { Infra } from '../infra/store';
import {
  Agent, AgentDescriptor, AgentExecuteInput, AgentExecuteOutput, PlanStep, RequestContext,
} from '../types';
import { brl, fmtData, fmtHora } from '../kernel/util';
import {
  cancelarAgendamento, consultarHorarios, criarAgendamento, proximoAgendamento, reagendarEmMassa, resolverServico, slotNaHora,
} from '../tools/agenda.tools';

export class AgendaAgent implements Agent {
  descriptor: AgentDescriptor = {
    name: 'AgendaAgent',
    description: 'Consulta, cria, cancela e remarca agendamentos.',
    capabilities: [
      { intent: 'consultar_horarios', description: 'Listar horários livres' },
      { intent: 'agendar', description: 'Criar agendamento' },
      { intent: 'remarcar', description: 'Remarcar agendamento' },
      { intent: 'cancelar', description: 'Cancelar agendamento' },
      { intent: 'reagendar_em_massa', description: 'Reagendar em lote a agenda de um profissional (ex.: falta)' },
    ],
    permissions: ['agenda:read', 'agenda:write'],
    tools: ['consultarAgenda', 'criarAgendamento', 'cancelarAgendamento', 'reagendarEmMassa'],
    estimatedCostUsd: 0.0002,
    avgLatencyMs: 120,
    version: '1.0.0',
    health: 'healthy',
  };

  /** Rastreia agendamentos criados por step, para compensação. */
  private criadosPorStep = new Map<string, string>();

  constructor(private infra: Infra) {}

  async execute(input: AgentExecuteInput): Promise<AgentExecuteOutput> {
    const { step, context } = input;
    switch (step.action) {
      case 'consultar_horarios':
        return this.consultar(step, context);
      case 'agendar':
        return this.agendar(step, context);
      case 'remarcar':
        return this.remarcar(step, context);
      case 'cancelar':
        return this.cancelar(context);
      case 'reagendar_em_massa':
        return this.reagendarMassa(step);
      default:
        return { ok: false, error: `Ação desconhecida: ${step.action}` };
    }
  }

  /** Operacional (recepção): realoca a agenda de um profissional ausente. */
  private reagendarMassa(step: PlanStep): AgentExecuteOutput {
    const args = step.input as { barbeiro?: string; quando?: string };
    const r = reagendarEmMassa(this.infra, args);
    if (!r.ok) return { ok: true, reply: r.erro, costUsd: this.descriptor.estimatedCostUsd };

    const { movido, semVaga } = r.resultado!;
    if (movido.length === 0 && semVaga.length === 0) {
      return { ok: true, reply: `${r.barber!.name} não tinha agendamentos nesse dia.`, costUsd: this.descriptor.estimatedCostUsd };
    }
    const linhasMov = movido.map(
      (m) => `  • ${m.customer?.name ?? '??'} (${fmtHora(m.start)}) → ${m.para}`,
    );
    const linhasSem = semVaga.map(
      (s) => `  • ${s.customer?.name ?? '??'} (${fmtHora(s.start)}) — sem vaga, avisar p/ remarcar`,
    );
    const partes = [`Agenda do ${r.barber!.name} reorganizada:`];
    if (linhasMov.length) partes.push(`Realocados (${movido.length}):\n${linhasMov.join('\n')}`);
    if (linhasSem.length) partes.push(`Sem encaixe (${semVaga.length}):\n${linhasSem.join('\n')}`);
    return { ok: true, reply: partes.join('\n'), costUsd: this.descriptor.estimatedCostUsd };
  }

  private consultar(step: PlanStep, ctx: RequestContext): AgentExecuteOutput {
    const args = step.input as { servico?: string; quando?: string; barbeiro?: string; silent?: boolean };
    const { servico, slots } = consultarHorarios(this.infra, args);
    // Passo silencioso: faz parte de um agendamento/remarcação, não fala com o cliente.
    if (args.silent) {
      return { ok: true, output: { slots, servico }, costUsd: this.descriptor.estimatedCostUsd };
    }
    if (slots.length === 0) {
      return { ok: true, output: { slots: [] }, reply: `Não encontrei horários para ${servico.name} nesse dia. Quer tentar outro dia?` };
    }
    const lista = slots.map((s) => `• ${fmtData(s.start)} com ${s.barberName}`).join('\n');
    return {
      ok: true,
      output: { slots, servico },
      reply: `Horários para ${servico.name} (${brl(servico.priceBrl)}):\n${lista}`,
      costUsd: this.descriptor.estimatedCostUsd,
    };
  }

  private agendar(step: PlanStep, ctx: RequestContext): AgentExecuteOutput {
    if (!ctx.customer) {
      // Sem identidade não dá para agendar -> pausa e pede dados (sem rollback).
      return { ok: true, halt: true, reply: 'Para confirmar o agendamento, me diz seu nome, por favor 🙂' };
    }
    const args = step.input as { servico?: string; quando?: string; hora?: string; barbeiro?: string };
    const { slots, servico } = consultarHorarios(this.infra, args);

    // Escolhe o slot pela hora pedida (busca no dia inteiro), senão o primeiro livre.
    let escolhido = slots[0];
    if (args.hora) {
      escolhido = slotNaHora(this.infra, args, Number(args.hora)) ?? slots[0];
    }
    if (!escolhido) {
      return { ok: true, reply: `Não há horário livre para ${servico.name} nesse dia. Quer ver outro dia?`, halt: true };
    }

    const appt = criarAgendamento(this.infra, {
      customerId: ctx.customer.id,
      barberId: escolhido.barberId,
      service: servico,
      start: escolhido.start,
    });
    this.criadosPorStep.set(step.id, appt.id);

    return {
      ok: true,
      output: { appointmentId: appt.id, servico, start: appt.start, barberName: escolhido.barberName },
      reply: `Agendado! ${servico.name} com ${escolhido.barberName} em ${fmtData(appt.start)}.`,
      costUsd: this.descriptor.estimatedCostUsd,
    };
  }

  private remarcar(step: PlanStep, ctx: RequestContext): AgentExecuteOutput {
    if (!ctx.customer) return { ok: true, halt: true, reply: 'Me confirma seu nome para localizar seu agendamento?' };
    const atual = proximoAgendamento(this.infra, ctx.customer.id);
    if (!atual) return { ok: true, reply: 'Não achei um agendamento futuro no seu nome. Quer marcar um novo?', halt: true };

    const servico = this.infra.db.services.get(atual.serviceId)!;
    const { slots } = consultarHorarios(this.infra, step.input as any);
    const novo = slots.find((s) => s.start !== atual.start) ?? slots[0];
    if (!novo) return { ok: true, reply: 'Não encontrei novos horários nesse dia. Quer tentar outro?', halt: true };

    atual.status = 'cancelado';
    const novoAppt = criarAgendamento(this.infra, {
      customerId: ctx.customer.id, barberId: novo.barberId, service: servico, start: novo.start,
    });
    this.criadosPorStep.set(step.id, novoAppt.id);
    return {
      ok: true,
      output: { de: atual.start, para: novoAppt.start },
      reply: `Pronto! Remarquei de ${fmtHora(atual.start)} para ${fmtData(novoAppt.start)} com ${novo.barberName}.`,
      costUsd: this.descriptor.estimatedCostUsd,
    };
  }

  private cancelar(ctx: RequestContext): AgentExecuteOutput {
    if (!ctx.customer) return { ok: true, halt: true, reply: 'Me confirma seu nome para localizar o agendamento a cancelar?' };
    const cancelado = cancelarAgendamento(this.infra, ctx.customer.id);
    if (!cancelado) return { ok: true, reply: 'Não encontrei agendamento futuro para cancelar.', halt: true };
    return {
      ok: true,
      output: { appointmentId: cancelado.id },
      reply: `Cancelado o atendimento de ${fmtData(cancelado.start)}. Se quiser, marco outro dia.`,
      costUsd: this.descriptor.estimatedCostUsd,
    };
  }

  /** Compensação: desfaz um agendamento criado neste step (rollback do saga). */
  async compensate(step: PlanStep, _ctx: RequestContext): Promise<void> {
    const apptId = this.criadosPorStep.get(step.id);
    if (apptId) {
      const a = this.infra.db.appointments.get(apptId);
      if (a) {
        a.status = 'cancelado';
        this.infra.db.appointments.set(a.id, a);
      }
    }
  }
}
