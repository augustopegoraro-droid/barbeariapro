/* Empty state padrão (UI_SPEC_V2 §2 item 11): card branco (sombra + fio),
   frase do estado + 1 ação navy. Textos canônicos inalterados. */

import type { ReactNode } from "react";

export function EmptyState({
  message,
  action,
}: {
  message: string;
  action?: ReactNode;
}) {
  return (
    <div
      className="rounded-xl border border-borda-sutil bg-superficie p-5 text-center"
      style={{ boxShadow: "var(--sombra-1)" }}
    >
      <p className="text-tinta-suave">{message}</p>
      {action && <div className="mt-4 flex justify-center">{action}</div>}
    </div>
  );
}
