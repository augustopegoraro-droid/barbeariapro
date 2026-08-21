"use client";

/* Lista paginada do feed. A primeira página vem do SSR (cache do Next, tag
   `public-feed`); as seguintes são buscadas no browser pelo CURSOR `before` —
   o `published_at` do último item já carregado. É o primeiro lugar do site com
   paginação, e o cursor evita o vício clássico do offset: um post novo entrando
   no topo entre duas páginas repetiria/pularia itens. */

import { useState } from "react";
import { api, type FeedPost } from "@/lib/api";
import { CardNovidade } from "@/components/novidades-home";

const PAGINA = 10;

export default function NovidadesLista({
  iniciais,
}: {
  iniciais: FeedPost[];
}) {
  const [posts, setPosts] = useState<FeedPost[]>(iniciais);
  const [carregando, setCarregando] = useState(false);
  const [erro, setErro] = useState("");
  /* Página inicial menor que o tamanho pedido já significa fim da lista. */
  const [fim, setFim] = useState(iniciais.length < PAGINA);

  async function carregarMais() {
    const ultimo = posts.at(-1);
    if (!ultimo || carregando) return;
    setCarregando(true);
    setErro("");
    try {
      const { posts: novos } = await api.feed({
        limit: PAGINA,
        before: ultimo.published_at,
      });
      setPosts((atuais) => {
        const vistos = new Set(atuais.map((p) => p.id));
        return [...atuais, ...novos.filter((p) => !vistos.has(p.id))];
      });
      if (novos.length < PAGINA) setFim(true);
    } catch {
      setErro("Não foi possível carregar mais novidades. Tente de novo.");
    } finally {
      setCarregando(false);
    }
  }

  if (posts.length === 0) {
    return (
      <p className="mt-8 text-tinta-suave">
        Ainda não há novidades publicadas. Volte em breve.
      </p>
    );
  }

  return (
    <>
      <div className="mt-8 grid gap-4 sm:grid-cols-2">
        {posts.map((p) => (
          <CardNovidade key={p.id} post={p} />
        ))}
      </div>

      {erro && (
        <p role="alert" className="mt-6 text-sm text-vermelho-tinta">
          {erro}
        </p>
      )}

      {!fim && (
        <button
          type="button"
          onClick={carregarMais}
          disabled={carregando}
          className="mx-auto mt-10 flex min-h-12 items-center justify-center rounded-full border border-ouro px-8 text-xs font-medium tracking-[0.16em] text-ouro uppercase transition-colors hover:bg-ouro hover:text-tinta-invertida disabled:opacity-60"
        >
          {carregando ? "Carregando…" : "Carregar mais"}
        </button>
      )}
    </>
  );
}
