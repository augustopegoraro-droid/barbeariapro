/**
 * tools/agenda.tools.ts
 * -----------------------------------------------------------------------------
 * Ferramentas de agenda. Independentes de IA — pura lógica + acesso a dados.
 * -----------------------------------------------------------------------------
 */

import { Infra } from '../infra/store';
import { Appointment, Barber, Customer, Service, Slot } from '../types';
import { id } from '../kernel/util';

const ABRE = 9;
const FECHA = 19;

/** Avança a data enquanto cai em dia fechado (domingo=0, segunda=1). */
function proximoDiaAberto(ts: number): number {
  const d = new Date(ts);
  while (d.getDay() === 0 || d.getDay() === 1) {
    d.setDate(d.getDate() + 1);
  }
  return d.getTime();
}

export function resolverDia(quando?: string): number {
  const d = new Date();
  d.setHours(0, 0, 0, 0);
  if (quando === 'hoje') {
    /* hoje */
  } else if (quando === 'depois_amanha') {
    d.setDate(d.getDate() + 2);
  } else {
    d.setDate(d.getDate() + 1); // padrão: amanhã
  }
  return proximoDiaAberto(d.getTime());
}

export function resolverServico(infra: Infra, servico?: string): Service {
  const map: Record<string, string> = { corte: 's_corte', barba: 's_barba', combo: 's_combo' };
  const sid = servico ? map[servico] : 's_corte';
  return infra.db.services.get(sid ?? 's_corte')!;
}

export function consultarHorarios(
  infra: Infra,
  args: { servico?: string; quando?: string; barbeiro?: string },
): { dia: number; servico: Service; slots: Slot[] } {
  const dia = resolverDia(args.quando);
  const fimDia = dia + 24 * 60 * 60_000;
  const servico = resolverServico(infra, args.servico);

  const barbeiros = [...infra.db.barbers.values()].filter(
    (b) => b.active && (!args.barbeiro || b.name === args.barbeiro),
  );

  const slots: Slot[] = [];
  for (const b of barbeiros) {
    const ocupados = infra.db.appointmentsForBarberOnDay(b.id, dia, fimDia);
    for (let h = ABRE; h + servico.durationMin / 60 <= FECHA; h += 0.5) {
      const start = dia + h * 60 * 60_000;
      const end = start + servico.durationMin * 60_000;
      const conflito = ocupados.some((a) => start < a.end && end > a.start);
      if (!conflito) slots.push({ barberId: b.id, barberName: b.name, start, end });
    }
  }
  // limita para não poluir a resposta
  return { dia, servico, slots: slots.slice(0, 6) };
}

export function slotNaHora(
  infra: Infra,
  args: { servico?: string; quando?: string; barbeiro?: string },
  hora: number,
): Slot | undefined {
  const dia = resolverDia(args.quando);
  const fimDia = dia + 24 * 60 * 60_000;
  const servico = resolverServico(infra, args.servico);
  if (hora < ABRE || hora + servico.durationMin / 60 > FECHA) return undefined;

  const barbeiros = [...infra.db.barbers.values()].filter(
    (b) => b.active && (!args.barbeiro || b.name === args.barbeiro),
  );
  const start = dia + hora * 60 * 60_000;
  const end = start + servico.durationMin * 60_000;
  for (const b of barbeiros) {
    const ocupados = infra.db.appointmentsForBarberOnDay(b.id, dia, fimDia);
    const conflito = ocupados.some((a) => start < a.end && end > a.start);
    if (!conflito) return { barberId: b.id, barberName: b.name, start, end };
  }
  return undefined;
}

export function criarAgendamento(
  infra: Infra,
  args: { customerId: string; barberId: string; service: Service; start: number },
): Appointment {
  const appt: Appointment = {
    id: id('appt'),
    customerId: args.customerId,
    barberId: args.barberId,
    serviceId: args.service.id,
    start: args.start,
    end: args.start + args.service.durationMin * 60_000,
    status: 'confirmado',
  };
  infra.db.appointments.set(appt.id, appt);
  return appt;
}

export function cancelarAgendamento(infra: Infra, customerId: string): Appointment | undefined {
  const futuros = [...infra.db.appointments.values()]
    .filter((a) => a.customerId === customerId && a.status === 'confirmado' && a.start > Date.now())
    .sort((a, b) => a.start - b.start);
  const alvo = futuros[0];
  if (!alvo) return undefined;
  alvo.status = 'cancelado';
  infra.db.appointments.set(alvo.id, alvo);
  return alvo;
}

export function proximoAgendamento(infra: Infra, customerId: string): Appointment | undefined {
  return [...infra.db.appointments.values()]
    .filter((a) => a.customerId === customerId && a.status === 'confirmado' && a.start > Date.now())
    .sort((a, b) => a.start - b.start)[0];
}

export function barbeiroPorNome(infra: Infra, nome?: string): Barber | undefined {
  if (!nome) return undefined;
  return [...infra.db.barbers.values()].find(
    (b) => b.name.toLowerCase() === nome.toLowerCase(),
  );
}

/** Outro profissional ativo livre no intervalo, exceto o ausente. */
function barbeiroLivreEm(
  infra: Infra,
  start: number,
  end: number,
  excetoId: string,
): Barber | undefined {
  const dia = new Date(start);
  dia.setHours(0, 0, 0, 0);
  const fim = dia.getTime() + 24 * 60 * 60_000;
  for (const b of infra.db.barbers.values()) {
    if (!b.active || b.id === excetoId) continue;
    const ocupados = infra.db.appointmentsForBarberOnDay(b.id, dia.getTime(), fim);
    const conflito = ocupados.some((a) => start < a.end && end > a.start);
    if (!conflito) return b;
  }
  return undefined;
}

export interface ReagendamentoMassa {
  movido: { customer?: Customer; de: string; para: string; start: number }[];
  semVaga: { customer?: Customer; start: number }[];
}

/**
 * Reagenda em lote a agenda de um profissional num dia (ex.: ele faltou).
 * Tenta realocar cada cliente para outro profissional no mesmo horário; quem
 * não couber entra em `semVaga` (cliente deve ser avisado para remarcar).
 */
export function reagendarEmMassa(
  infra: Infra,
  args: { barbeiro?: string; quando?: string },
): { ok: boolean; barber?: Barber; resultado?: ReagendamentoMassa; erro?: string } {
  const barber = barbeiroPorNome(infra, args.barbeiro);
  if (!barber) {
    return { ok: false, erro: `Não identifiquei o profissional "${args.barbeiro ?? ''}".` };
  }
  const dia = resolverDia(args.quando);
  const fim = dia + 24 * 60 * 60_000;
  const appts = infra.db.appointmentsForBarberOnDay(barber.id, dia, fim);

  const resultado: ReagendamentoMassa = { movido: [], semVaga: [] };
  for (const a of appts) {
    const customer = infra.db.customers.get(a.customerId);
    const livre = barbeiroLivreEm(infra, a.start, a.end, barber.id);
    a.status = 'cancelado';
    infra.db.appointments.set(a.id, a);
    if (livre) {
      const novo: Appointment = {
        id: id('appt'),
        customerId: a.customerId,
        barberId: livre.id,
        serviceId: a.serviceId,
        start: a.start,
        end: a.end,
        status: 'confirmado',
      };
      infra.db.appointments.set(novo.id, novo);
      resultado.movido.push({ customer, de: barber.name, para: livre.name, start: a.start });
    } else {
      resultado.semVaga.push({ customer, start: a.start });
    }
  }
  return { ok: true, barber, resultado };
}
