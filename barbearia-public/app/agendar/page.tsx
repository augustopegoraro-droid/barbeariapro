import Link from "next/link";
import { fetchInfo } from "@/lib/api";
import BookingFlow from "@/components/booking-flow";

export const revalidate = 60;

export const metadata = { title: "Agendar horário" };

export default async function AgendarPage() {
  let info = null;
  try {
    info = await fetchInfo(revalidate);
  } catch {
    info = null;
  }

  if (!info || info.services.length === 0) {
    return (
      <main className="mx-auto flex min-h-[80dvh] w-full max-w-md flex-col items-center justify-center gap-4 px-6 text-center">
        <h1 className="font-display text-2xl font-semibold">Agendamento indisponível</h1>
        <p className="text-creme-suave">
          Não conseguimos carregar a agenda agora. Tente de novo em instantes ou
          chame a gente no WhatsApp.
        </p>
        <Link href="/" className="text-ambar underline underline-offset-4">
          Voltar ao início
        </Link>
      </main>
    );
  }

  return <BookingFlow info={info} />;
}
