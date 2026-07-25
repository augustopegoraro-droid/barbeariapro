/* Aviso inline (banner) — retorno por 409 ao passo 3 (UX A1/§4.2).
   Anatomia derivada do toast (UI_SPEC_V2 §2 item 10): superfície branca,
   barra de acento no par -tinta do estado. role="alert" anuncia na hora. */

const ACCENT: Record<string, string> = {
  aviso: "var(--ambar-tinta)",
  erro: "var(--vermelho-tinta)",
  sucesso: "var(--verde-tinta)",
};

export function Notice({
  kind = "aviso",
  children,
}: {
  kind?: "aviso" | "erro" | "sucesso";
  children: React.ReactNode;
}) {
  return (
    <div
      role="alert"
      className="anim-entrar flex items-start gap-3 rounded-xl border border-borda bg-superficie p-4"
      style={{ boxShadow: "var(--sombra-1)" }}
    >
      <span
        aria-hidden
        className="mt-0.5 h-full w-[3px] shrink-0 self-stretch rounded-full"
        style={{ background: ACCENT[kind] }}
      />
      <p className="text-sm text-tinta">{children}</p>
    </div>
  );
}
