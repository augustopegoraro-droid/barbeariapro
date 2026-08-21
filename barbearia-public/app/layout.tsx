import type { Metadata, Viewport } from "next";
import { headers } from "next/headers";
import { Cormorant_Garamond, Jost } from "next/font/google";
import "./globals.css";
import RegisterSW from "@/components/register-sw";
import AppTabBar from "@/components/app-tabbar";
import { AppModeProvider } from "@/components/app-mode";
import { isAppUserAgent } from "@/lib/native";

/* Tipografia da landing (UI_SPEC_V3): Cormorant Garamond nas palavras da marca
   e nos títulos — o serifado de alto contraste do letreiro; Jost no texto e nos
   versaletes, que é onde mora a informação prática (preço, horário, duração). */
const cormorant = Cormorant_Garamond({
  subsets: ["latin"],
  variable: "--font-cormorant",
  weight: ["300", "400", "500", "600"],
});

const jost = Jost({
  subsets: ["latin"],
  variable: "--font-jost",
  weight: ["300", "400", "500"],
});

const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL ?? "https://taylorethedy.com";

export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: {
    default: "Taylor e Thedy — Salão e Barbearia em Palmas/TO",
    template: "%s · Taylor e Thedy",
  },
  description:
    "Corte, barba, coloração e sobrancelha com hora marcada no Plano Diretor Sul, Palmas/TO. 4,8 no Google em 400 avaliações. Agende em poucos toques.",
  manifest: "/manifest.webmanifest",
  appleWebApp: {
    capable: true,
    title: "Taylor e Thedy",
    statusBarStyle: "black-translucent",
  },
  alternates: { canonical: "/" },
  openGraph: {
    type: "website",
    locale: "pt_BR",
    siteName: "Taylor e Thedy",
    title: "Taylor e Thedy — Salão e Barbearia em Palmas/TO",
    description: "Agende seu horário em poucos toques.",
    /* Sem isto o link colado no WhatsApp — que é como o negócio divulga —
       aparece sem imagem nenhuma. A foto é a fachada real. */
    images: [
      {
        url: "/og.jpg",
        width: 1200,
        height: 630,
        alt: "Fachada da Taylor e Thedy, no Plano Diretor Sul, em Palmas",
      },
    ],
  },
  twitter: {
    card: "summary_large_image",
    title: "Taylor e Thedy — Salão e Barbearia em Palmas/TO",
    description: "Agende seu horário em poucos toques.",
    images: ["/og.jpg"],
  },
};

export const viewport: Viewport = {
  themeColor: "#0a0b0d",
  width: "device-width",
  initialScale: 1,
};

export default async function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  /* Modo app pelo User-Agent (`appendUserAgent: "TTApp/1"` do Capacitor).
     Ler `headers()` aqui torna a renderização dinâmica — o custo é aceitável
     porque o dado caro (a vitrine) continua vindo do cache de fetch com tag
     `public-info` (D-84), não do cache de página. */
  const isApp = isAppUserAgent((await headers()).get("user-agent"));

  return (
    <html lang="pt-BR" className={`${cormorant.variable} ${jost.variable}`}>
      {/* `data-app` deixa o CSS esconder o que é marketing sem transformar as
          páginas server em client (ver `globals.css`). */}
      <body data-app={isApp ? "1" : undefined}>
        {/* Primeiro alvo de tabulação: pula o cabeçalho e o hero direto para a
            ação principal. Só aparece quando recebe foco. */}
        <a
          href="/agendar"
          className="sr-only focus:not-sr-only focus:absolute focus:top-3 focus:left-3 focus:z-50 focus:inline-flex focus:min-h-11 focus:items-center focus:rounded-full focus:bg-ouro focus:px-5 focus:font-semibold focus:text-tinta-invertida"
        >
          Agendar horário
        </a>
        <AppModeProvider isApp={isApp}>{children}</AppModeProvider>
        <RegisterSW />
        <AppTabBar isApp={isApp} />
      </body>
    </html>
  );
}
