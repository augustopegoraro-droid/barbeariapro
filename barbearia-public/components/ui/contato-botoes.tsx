/* Botões de contato (UI_SPEC_V3 §4, nível 3): contorno que vira ouro no hover.
   Ficam abaixo do CTA na hierarquia — quem quer marcar horário usa o botão
   dourado; estes são para quem quer falar com a barbearia ou ver o trabalho.

   Ícones inline (o CSP do site não carrega nada de fora e não há lib de
   ícones no projeto). */

import type { Contato } from "@/lib/contato";

function IconeWhatsApp() {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="currentColor"
      className="h-5 w-5"
      aria-hidden
    >
      <path d="M12.04 2a9.9 9.9 0 0 0-8.5 14.94L2 22l5.2-1.5A9.9 9.9 0 1 0 12.04 2Zm0 1.8a8.1 8.1 0 1 1-4.1 15.08l-.3-.18-3.08.89.9-3-.2-.31A8.1 8.1 0 0 1 12.04 3.8Zm4.65 10.3c-.25-.13-1.47-.72-1.7-.8-.23-.09-.4-.13-.56.12s-.64.8-.79.97c-.14.17-.29.19-.54.06a6.63 6.63 0 0 1-1.95-1.2 7.3 7.3 0 0 1-1.35-1.68c-.14-.25-.01-.38.11-.5.11-.12.25-.29.37-.44.12-.15.16-.25.25-.42.08-.17.04-.31-.02-.44-.06-.12-.56-1.34-.76-1.84-.2-.48-.4-.41-.56-.42h-.47a.9.9 0 0 0-.66.3 2.76 2.76 0 0 0-.86 2.05c0 1.2.88 2.37 1 2.53.13.17 1.73 2.64 4.2 3.7.58.26 1.04.4 1.4.51.59.19 1.13.16 1.55.1.47-.07 1.47-.6 1.68-1.18.2-.58.2-1.08.15-1.18-.06-.11-.23-.17-.48-.29Z" />
    </svg>
  );
}

function IconeInstagram() {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      className="h-5 w-5"
      aria-hidden
    >
      <rect x="3" y="3" width="18" height="18" rx="5" />
      <circle cx="12" cy="12" r="3.8" />
      <circle cx="17.2" cy="6.8" r="1.1" fill="currentColor" stroke="none" />
    </svg>
  );
}

function IconeFacebook() {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="currentColor"
      className="h-5 w-5"
      aria-hidden
    >
      <path d="M22 12.06C22 6.5 17.52 2 12 2S2 6.5 2 12.06c0 5.02 3.66 9.18 8.44 9.94v-7.03H7.9v-2.9h2.54V9.85c0-2.52 1.5-3.91 3.77-3.91 1.09 0 2.24.2 2.24.2v2.46h-1.26c-1.24 0-1.63.78-1.63 1.57v1.89h2.78l-.45 2.9h-2.33V22c4.78-.76 8.44-4.92 8.44-9.94Z" />
    </svg>
  );
}

function IconeTelefone() {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
      className="h-5 w-5"
      aria-hidden
    >
      <path d="M22 16.9v3a2 2 0 0 1-2.2 2 19.8 19.8 0 0 1-8.6-3.1 19.5 19.5 0 0 1-6-6A19.8 19.8 0 0 1 2.1 4.2 2 2 0 0 1 4.1 2h3a2 2 0 0 1 2 1.7c.1.9.4 1.8.7 2.7a2 2 0 0 1-.5 2.1L8.1 9.9a16 16 0 0 0 6 6l1.4-1.2a2 2 0 0 1 2.1-.5c.9.3 1.8.6 2.7.7a2 2 0 0 1 1.7 2Z" />
    </svg>
  );
}

const BOTAO =
  "inline-flex min-h-11 items-center gap-2.5 rounded-full border border-borda px-5 py-2.5 text-sm font-medium text-marfim transition-colors hover:border-ouro hover:text-ouro";

export function ContatoBotoes({
  contato,
  className = "",
}: {
  contato: Contato;
  className?: string;
}) {
  return (
    <div className={`flex flex-wrap gap-3 ${className}`}>
      <a
        href={`https://wa.me/${contato.whatsappDigits}`}
        target="_blank"
        rel="noopener noreferrer"
        className={BOTAO}
      >
        <IconeWhatsApp />
        WhatsApp
      </a>
      <a
        href={contato.instagramUrl}
        target="_blank"
        rel="noopener noreferrer"
        className={BOTAO}
      >
        <IconeInstagram />@{contato.instagram}
      </a>
      <a
        href={contato.facebookUrl}
        target="_blank"
        rel="noopener noreferrer"
        className={BOTAO}
      >
        <IconeFacebook />
        Facebook
      </a>
      <a href={`tel:${contato.phoneDigits}`} className={BOTAO}>
        <IconeTelefone />
        {contato.phone}
      </a>
    </div>
  );
}

export { IconeInstagram, IconeFacebook };
