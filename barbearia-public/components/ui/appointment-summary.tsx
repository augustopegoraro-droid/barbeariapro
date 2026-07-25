/* Card de resumo de agendamento (UI_SPEC_V2 §2 item 9) — passo 4, sucesso e
   confirmação. No claro, todo card branco leva sombra + fio de borda (§1.6). */

import { dateLong, money, timeHM } from "@/lib/format";

export function AppointmentSummary({
  serviceName,
  startAt,
  barberName,
  price,
}: {
  serviceName: string;
  startAt: string; // ISO
  barberName: string;
  price: number;
}) {
  return (
    <div
      className="rounded-xl border border-borda-sutil bg-superficie p-5"
      style={{ boxShadow: "var(--sombra-1)" }}
    >
      <p className="font-medium text-tinta">{serviceName}</p>
      <p className="mt-1 text-tinta-suave">
        {dateLong(startAt)} às <span className="tnum">{timeHM(startAt)}</span>
      </p>
      <p className="mt-1 text-tinta-suave">com {barberName}</p>
      <p className="mt-3 font-display text-xl text-tinta tnum">{money(price)}</p>
    </div>
  );
}
