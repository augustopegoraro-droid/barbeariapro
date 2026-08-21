/* Home do modo app — é a URL que o Capacitor abre (`server.url` de
   `barbearia-app/capacitor.config.ts`). Sem hero de marketing, sem
   depoimentos: quem já instalou o app vem agendar, não ser convencido.

   Continua acessível pelo browser (não é rota exclusiva), só não é divulgada. */

import InicioCliente from "@/components/inicio/inicio-cliente";

export const metadata = {
  title: "Início",
  robots: { index: false, follow: false },
};

export default function InicioPage() {
  return <InicioCliente />;
}
