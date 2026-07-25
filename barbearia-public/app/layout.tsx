import type { Metadata, Viewport } from "next";
import { Cormorant_Garamond, Jost } from "next/font/google";
import "./globals.css";
import RegisterSW from "@/components/register-sw";

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
  openGraph: {
    type: "website",
    locale: "pt_BR",
    siteName: "Taylor e Thedy",
    title: "Taylor e Thedy — Salão e Barbearia em Palmas/TO",
    description: "Agende seu horário em poucos toques.",
  },
};

export const viewport: Viewport = {
  themeColor: "#0a0b0d",
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="pt-BR" className={`${cormorant.variable} ${jost.variable}`}>
      <body>
        {children}
        <RegisterSW />
      </body>
    </html>
  );
}
