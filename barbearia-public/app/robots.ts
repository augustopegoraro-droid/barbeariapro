import type { MetadataRoute } from "next";

const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL ?? "https://taylorethedy.com";

export default function robots(): MetadataRoute.Robots {
  return {
    rules: [
      {
        userAgent: "*",
        allow: "/",
        /* Área da sessão do cliente: nada a indexar e nada que faça sentido
           fora do aparelho de quem agendou. */
        disallow: ["/meus-agendamentos"],
      },
    ],
    sitemap: `${SITE_URL}/sitemap.xml`,
  };
}
