/* Seção "Novidades" da home — as 3 publicações mais recentes do mural que o
   gestor mantém no painel (`/admin/novidades`). Server component, zero JS.

   Devolve `null` quando não há nada publicado: barbearia sem post não ganha
   uma seção fantasma vazia no meio da landing. */

import Link from "next/link";
import { fetchFeed, type FeedPost } from "@/lib/api";

const LIMITE_HOME = 3;

export function dataCurta(iso: string): string {
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "";
  return d.toLocaleDateString("pt-BR", {
    day: "2-digit",
    month: "long",
    year: "numeric",
  });
}

/** Primeiras linhas do corpo, sem cortar palavra ao meio. */
export function trecho(texto: string, max = 160): string {
  const limpo = texto.replace(/\s+/g, " ").trim();
  if (limpo.length <= max) return limpo;
  const corte = limpo.slice(0, max);
  const espaco = corte.lastIndexOf(" ");
  return `${corte.slice(0, espaco > 60 ? espaco : max)}…`;
}

export function CardNovidade({ post }: { post: FeedPost }) {
  return (
    <article
      className="flex h-full flex-col overflow-hidden rounded-2xl border border-borda-sutil bg-superficie"
      style={{ boxShadow: "var(--sombra-1)" }}
    >
      {post.image_url && (
        /* eslint-disable-next-line @next/next/no-img-element */
        <img
          src={post.image_url}
          alt=""
          aria-hidden
          loading="lazy"
          className="aspect-[16/9] w-full object-cover"
        />
      )}
      <div className="flex flex-1 flex-col px-6 py-5">
        <p className="rotulo text-ouro">
          {post.pinned ? "Destaque" : "Novidade"}
        </p>
        <h3 className="font-display mt-2 text-xl leading-snug text-marfim">
          {post.title}
        </h3>
        <p className="mt-2 text-sm text-tinta-suave">{trecho(post.body)}</p>
        <time
          dateTime={post.published_at}
          className="tnum mt-4 text-xs text-tinta-fraca"
        >
          {dataCurta(post.published_at)}
        </time>
      </div>
    </article>
  );
}

export async function NovidadesHome() {
  let posts: FeedPost[] = [];
  try {
    posts = await fetchFeed({ limit: LIMITE_HOME });
  } catch {
    // Falha do feed não derruba a home: a seção simplesmente não aparece.
    return null;
  }
  if (posts.length === 0) return null;

  return (
    <section
      aria-labelledby="novidades-titulo"
      id="novidades"
      className="mx-auto w-full max-w-5xl scroll-mt-20 px-5 py-16 sm:px-8"
    >
      <p className="flex items-center gap-3">
        <span className="regua-secao" aria-hidden />
        <span className="rotulo text-tinta-suave">Novidades</span>
      </p>
      <h2
        id="novidades-titulo"
        className="font-display mt-3 text-3xl leading-tight font-light text-marfim sm:text-4xl"
      >
        O que há de novo
      </h2>

      <div className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {posts.map((p) => (
          <CardNovidade key={p.id} post={p} />
        ))}
      </div>

      <Link
        href="/novidades"
        className="mt-8 inline-flex min-h-11 items-center text-sm text-ouro transition-colors hover:text-ouro-claro"
      >
        Ver todas as novidades →
      </Link>
    </section>
  );
}

export default NovidadesHome;
