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
import { INFO_TAG } from "@/lib/api";

export const runtime = "nodejs";

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

  /* Next 16 exige o profile de cacheLife: "seconds" é o mais curto embutido —
     a entrada antiga deixa de ser servida praticamente na hora. */
  revalidateTag(INFO_TAG, "seconds");
  return Response.json({ revalidated: INFO_TAG });
}
