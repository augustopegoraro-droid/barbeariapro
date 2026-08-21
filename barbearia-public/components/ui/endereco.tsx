"use client";

/* Legenda de localização — mora colada à foto da fachada, que é onde a
   pergunta "onde fica?" nasce. Repete o endereço da seção "Onde e quando" de
   propósito: quem reconhece a fachada quer o mapa ali, não 3 seções abaixo.

   No app o mapa abre FORA da WebView (`handleExternalLink`), senão o Google
   Maps carregaria dentro do app sem como voltar. */

import { handleExternalLink } from "@/lib/native";

const GOOGLE_MAPS_URL = "https://maps.app.goo.gl/8QKLfpgmMgsr5CVMA";

export function mapsUrl(_endereco: string) {
  return GOOGLE_MAPS_URL;
}

export function EnderecoLegenda({
  endereco,
  className = "",
}: {
  endereco: string;
  className?: string;
}) {
  return (
    <figcaption className={`mt-3 ${className}`}>
      <p className="text-sm text-tinta-suave">{endereco}</p>
      <a
        href={mapsUrl(endereco)}
        target="_blank"
        rel="noopener noreferrer"
        onClick={(e) => handleExternalLink(e, mapsUrl(endereco))}
        className="inline-flex min-h-11 items-center gap-1.5 text-sm font-medium text-ouro transition-colors hover:text-ouro-claro"
      >
        <svg
          className="h-4 w-4"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth={1.8}
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden
        >
          <path d="M20 10c0 6-8 12-8 12s-8-6-8-12a8 8 0 1 1 16 0Z" />
          <circle cx="12" cy="10" r="3" />
        </svg>
        Abrir no Google Maps
      </a>
    </figcaption>
  );
}
