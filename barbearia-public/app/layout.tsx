import type { Metadata, Viewport } from "next";
import { Quicksand, Tenor_Sans } from "next/font/google";
import "./globals.css";
import RegisterSW from "@/components/register-sw";

/* Tipografia da fachada: Tenor Sans ≈ o traço flareado de alto contraste da
   placa; Quicksand ≈ o rounded do slogan "Renove seu Estilo". */
const tenor = Tenor_Sans({
  subsets: ["latin"],
  variable: "--font-tenor",
  weight: "400",
});

const quicksand = Quicksand({
  subsets: ["latin"],
  variable: "--font-quicksand",
  weight: ["400", "500", "600", "700"],
});

const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL ?? "https://taylorethedy.com";

export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: {
    default: "Taylor & Thedy — Barbearia em Palmas/TO",
    template: "%s · Taylor & Thedy",
  },
  description:
    "Agende seu horário na Taylor & Thedy em poucos toques: corte, barba e cuidados masculinos em Palmas/TO.",
  manifest: "/manifest.webmanifest",
  appleWebApp: {
    capable: true,
    title: "Taylor & Thedy",
    statusBarStyle: "black-translucent",
  },
  openGraph: {
    type: "website",
    locale: "pt_BR",
    siteName: "Taylor & Thedy",
    title: "Taylor & Thedy — Barbearia em Palmas/TO",
    description: "Agende seu horário em poucos toques.",
  },
};

export const viewport: Viewport = {
  themeColor: "#262c36",
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="pt-BR" className={`${tenor.variable} ${quicksand.variable}`}>
      <body>
        <div className="stripe" aria-hidden />
        {children}
        <RegisterSW />
      </body>
    </html>
  );
}
