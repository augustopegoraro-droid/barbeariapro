/* Badge de status de agendamento (UI_SPEC_V2 §1.5): pares fundo/tinta sólidos
   — opacidade (`cor/15`) sobre claro lava a cor, então os pares v1 saem. */

const STYLES: Record<string, string> = {
  agendado: "bg-verde-fundo text-verde-tinta",
  concluido: "bg-superficie-2 text-tinta-suave",
  cancelado: "bg-vermelho-fundo text-vermelho-tinta",
  faltou: "bg-ambar-fundo text-ambar-tinta",
};

export const STATUS_LABEL: Record<string, string> = {
  agendado: "Agendado",
  concluido: "Concluído",
  cancelado: "Cancelado",
  faltou: "Não compareceu",
};

export function StatusBadge({ status }: { status: string }) {
  return (
    <span
      className={`rounded-full px-2.5 py-1 text-xs font-medium ${
        STYLES[status] ?? "bg-superficie-2 text-tinta-suave"
      }`}
    >
      {STATUS_LABEL[status] ?? status}
    </span>
  );
}
