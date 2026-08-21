/* Mural completo de novidades/promoções. A home mostra as 3 mais recentes
   (`components/novidades-home.tsx`); aqui vai a lista inteira, paginada. */

import Link from "next/link";
import { fetchFeed, type FeedPost } from "@/lib/api";
import NovidadesLista from "@/components/novidades-lista";

export const revalidate = 300;

export const metadata = {
  title: "Novidades",
  description:
    "Promoções, horários especiais e novidades da Taylor & Thedy, em Palmas/TO.",
};

export default async function NovidadesPage() {
  let posts: FeedPost[] = [];
  let falhou = false;
  try {
    /* Sem `limit`: o backend só serve a primeira página do cache Redis quando
       o tamanho pedido é o padrão dele. */
    posts = await fetchFeed({}, revalidate);
  } catch {
    falhou = true;
  }

  return (
    <main className="mx-auto w-full max-w-3xl px-5 py-12 pb-32 sm:px-8">
      <p className="flex items-center gap-3">
        <span className="regua-secao" aria-hidden />
        <span className="rotulo text-tinta-suave">Novidades</span>
      </p>
      <h1 className="font-display mt-3 text-3xl leading-tight font-light text-marfim sm:text-4xl">
        O que há de novo
      </h1>
      <p className="mt-3 max-w-[52ch] text-tinta-suave">
        Promoções, horários especiais e avisos da casa.
      </p>

      {falhou ? (
        <p className="mt-8 text-tinta-suave">
          Não foi possível carregar as novidades agora. Tente de novo em
          instantes.
        </p>
      ) : (
        <NovidadesLista iniciais={posts} />
      )}

      <Link
        href="/"
        className="mt-12 inline-flex min-h-11 items-center text-sm text-tinta-suave transition-colors hover:text-marfim"
      >
        ← Voltar ao início
      </Link>
    </main>
  );
}
