/* Assinaturas e pacotes — compra online (Stripe Connect).

   A lista vem VAZIA quando a barbearia ainda não habilitou recebimentos
   online: isso é estado esperado, não erro, e a página vira um "em breve"
   discreto em vez de mostrar falha. */

import Link from "next/link";
import { fetchPlanos, type MembershipPlanPublic } from "@/lib/api";
import { Planos } from "@/components/assinatura/planos";

export const revalidate = 300;

export const metadata = {
  title: "Assinaturas e pacotes",
  description:
    "Assine um pacote de serviços da Taylor & Thedy e pague online, com segurança.",
};

export default async function AssinaturaPage({
  searchParams,
}: {
  searchParams: Promise<{ cancelado?: string }>;
}) {
  const { cancelado } = await searchParams;

  let planos: MembershipPlanPublic[] = [];
  let falhou = false;
  try {
    planos = await fetchPlanos(revalidate);
  } catch {
    falhou = true;
  }

  return (
    <main className="mx-auto w-full max-w-3xl px-5 py-12 pb-32 sm:px-8">
      <p className="flex items-center gap-3">
        <span className="regua-secao" aria-hidden />
        <span className="rotulo text-tinta-suave">Assinatura</span>
      </p>
      <h1 className="font-display mt-3 text-3xl leading-tight font-light text-marfim sm:text-4xl">
        Pacotes da casa
      </h1>
      <p className="mt-3 max-w-[52ch] text-tinta-suave">
        Garanta seus cuidados do mês com um único pagamento — e chegue só para
        sentar na cadeira.
      </p>

      {cancelado && (
        <p
          role="status"
          className="mt-6 rounded-xl border border-borda-sutil bg-superficie px-4 py-3 text-sm text-tinta-suave"
        >
          Pagamento cancelado. Nada foi cobrado — você pode escolher outro
          pacote quando quiser.
        </p>
      )}

      {falhou || planos.length === 0 ? (
        <p className="mt-8 text-tinta-suave">
          Assinaturas em breve. Enquanto isso, agende seu horário normalmente.
        </p>
      ) : (
        <Planos planos={planos} />
      )}

      <div className="mt-12 flex flex-wrap gap-6">
        <Link
          href="/"
          className="inline-flex min-h-11 items-center text-sm text-tinta-suave transition-colors hover:text-marfim"
        >
          ← Voltar ao início
        </Link>
        <Link
          href="/agendar"
          className="inline-flex min-h-11 items-center text-sm text-tinta-suave transition-colors hover:text-marfim"
        >
          Agendar horário
        </Link>
      </div>
    </main>
  );
}
