/* Botões nível 2 (UI_SPEC_V3 §2.1/§2.2) — sólido OURO (commit) e secundário
   (contorno). O `.cta-agendar` (nível 1, ouro com facho e glow) é exclusivo do
   hero e do fechamento da landing, e vive em globals.css. Sem glow aqui. */

import Link from "next/link";
import type { ComponentProps, ReactNode } from "react";

const SOLID_BASE =
  "inline-flex min-h-11 items-center justify-center gap-2 rounded-xl bg-ouro font-semibold text-tinta-invertida transition-colors hover:bg-ouro-claro active:scale-[0.985] disabled:opacity-60";

const SIZE = {
  full: "w-full px-6 py-4 text-lg",
  inline: "px-6 py-3",
} as const;

type Size = keyof typeof SIZE;

export function SolidButton({
  size = "full",
  className = "",
  ...props
}: ComponentProps<"button"> & { size?: Size }) {
  return (
    <button className={`${SOLID_BASE} ${SIZE[size]} ${className}`} {...props} />
  );
}

export function SolidLink({
  size = "full",
  className = "",
  ...props
}: ComponentProps<typeof Link> & { size?: Size }) {
  return <Link className={`${SOLID_BASE} ${SIZE[size]} ${className}`} {...props} />;
}

/* Secundário (contorno) — ações alternativas visíveis. */
export function OutlineButton({
  className = "",
  ...props
}: ComponentProps<"button">) {
  return (
    <button
      className={`inline-flex min-h-11 items-center justify-center rounded-xl border border-borda bg-transparent px-6 py-3 font-medium text-marfim transition-colors hover:border-ouro hover:text-ouro active:scale-[0.985] disabled:opacity-60 ${className}`}
      {...props}
    />
  );
}

/* Spinner de loading — vive sobre o ouro (botão sólido): anel de tinta escura. */
export function Spinner() {
  return (
    <span
      aria-hidden
      className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-tinta-invertida/30 border-t-tinta-invertida"
    />
  );
}

export function GhostLink({
  className = "",
  children,
  ...props
}: ComponentProps<typeof Link> & { children: ReactNode }) {
  return (
    <Link
      className={`inline-flex min-h-11 items-center text-sm text-tinta-suave underline underline-offset-4 transition-colors hover:text-marfim ${className}`}
      {...props}
    >
      {children}
    </Link>
  );
}
