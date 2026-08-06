/**
 * tools/relacionamento.tools.ts
 * -----------------------------------------------------------------------------
 * Ferramentas de relacionamento (operacional): inadimplentes, clientes inativos
 * e lembretes de agendamento. Apenas leitura do domínio + envio simulado.
 * -----------------------------------------------------------------------------
 */

import { Infra } from '../infra/store';
import { Appointment, Barber, Customer, Payment } from '../types';
import { resolverDia } from './agenda.tools';

const DIA_MS = 24 * 60 * 60_000;

export function listarInadimplentes(
  infra: Infra,
): { customer: Customer; pendente?: Payment }[] {
  const res: { customer: Customer; pendente?: Payment }[] = [];
  for (const c of infra.db.customers.values()) {
    if (!c.inadimplente) continue;
    const pendente = [...infra.db.payments.values()].find(
      (p) => p.customerId === c.id && p.status === 'pendente',
    );
    res.push({ customer: c, pendente });
  }
  return res;
}

/** Clientes sem agendamento futuro e sem atendimento nos últimos `dias`. */
export function clientesInativos(infra: Infra, dias = 30): Customer[] {
  const agora = Date.now();
  const limite = agora - dias * DIA_MS;
  return [...infra.db.customers.values()].filter((c) => {
    const appts = [...infra.db.appointments.values()].filter(
      (a) => a.customerId === c.id && a.status !== 'cancelado',
    );
    const temFuturo = appts.some((a) => a.start > agora);
    const temRecente = appts.some((a) => a.start >= limite);
    return !temFuturo && !temRecente;
  });
}

export function agendamentosDeAmanha(
  infra: Infra,
): { appt: Appointment; customer?: Customer; barber?: Barber }[] {
  const dia = resolverDia('amanha');
  const fim = dia + DIA_MS;
  return [...infra.db.appointments.values()]
    .filter((a) => a.status === 'confirmado' && a.start >= dia && a.start < fim)
    .sort((a, b) => a.start - b.start)
    .map((appt) => ({
      appt,
      customer: infra.db.customers.get(appt.customerId),
      barber: infra.db.barbers.get(appt.barberId),
    }));
}

/** Envio de mensagem (simulado — em produção iria à Cloud API / Chatwoot). */
export function enviarMensagem(_infra: Infra, _to: string, _texto: string): void {
  /* no-op na simulação; a resposta do agente descreve o que foi enviado */
}
