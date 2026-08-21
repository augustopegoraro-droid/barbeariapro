/* Revalidação sob demanda da vitrine (D-84).

   Chamado pelo BACKEND (rede interna do compose, nunca pela internet: o nginx
   não expõe /api/revalidate) sempre que o painel muda algo que o site mostra —
   profissional novo, serviço, horário, visibilidade. Sem isto, o cadastro só
   aparecia quando o ISR vencia (até 5 min).

   Autenticação: segredo compartilhado no header `x-revalidate-secret`,
   comparado em tempo constante. Sem REVALIDATE_SECRET no ambiente a rota
   responde 503 (fail closed) — nunca revalida sem provar identidade. */

import { revalidateTag } from "next/cache";
import { timingSafeEqual } from "node:crypto";
import { FEED_TAG, INFO_TAG } from "@/lib/api";

export const runtime = "nodejs";

/* Allowlist: só estas tags podem ser invalidadas de fora. Um corpo com tag
   desconhecida é ignorado — nunca há "revalidar tudo". */
const ALLOWED_TAGS = [INFO_TAG, FEED_TAG] as const;

function parseTags(body: unknown): string[] {
  if (!body || typeof body !== "object") return [];
  const raw = (body as { tags?: unknown }).tags;
  if (!Array.isArray(raw)) return [];
  return raw.filter(
    (t): t is string =>
      typeof t === "string" && (ALLOWED_TAGS as readonly string[]).includes(t),
  );
}

function secretOk(provided: string | null): boolean {
  const expected = process.env.REVALIDATE_SECRET;
  if (!expected || !provided) return false;
  const a = Buffer.from(provided);
  const b = Buffer.from(expected);
  if (a.length !== b.length) return false;
  return timingSafeEqual(a, b);
}

export async function POST(request: Request) {
  if (!process.env.REVALIDATE_SECRET) {
    return new Response("Revalidação não configurada.", { status: 503 });
  }
  if (!secretOk(request.headers.get("x-revalidate-secret"))) {
    return new Response("Não autorizado.", { status: 401 });
  }

  /* Corpo sem `tags` = backend antigo (que só sabia revalidar a vitrine):
     fallback para `public-info`, para que os dois lados possam ser deployados
     em qualquer ordem sem janela de site desatualizado. */
  const body = await request.json().catch(() => null);
  const tags = parseTags(body);
  const targets = tags.length > 0 ? tags : [INFO_TAG];

  /* Next 16 exige o profile de cacheLife: "seconds" é o mais curto embutido —
     a entrada antiga deixa de ser servida praticamente na hora. */
  for (const tag of targets) revalidateTag(tag, "seconds");
  return Response.json({ revalidated: targets });
}
