/**
 * tools/estoque.tools.ts
 * -----------------------------------------------------------------------------
 * Ferramentas de estoque/produtos (operacional). Consulta, consumo e reposição.
 * -----------------------------------------------------------------------------
 */

import { Infra } from '../infra/store';
import { Product } from '../types';

function norm(s: string): string {
  return s.toLowerCase().normalize('NFD').replace(/\p{Diacritic}/gu, '');
}

export function listarProdutos(infra: Infra): Product[] {
  return [...infra.db.products.values()].sort((a, b) => a.name.localeCompare(b.name));
}

export function estoqueBaixo(infra: Infra): Product[] {
  return infra.db.produtosAbaixoDoMinimo();
}

/** Acha o produto por correspondência de nome (ex.: "pomada" -> Pomada modeladora). */
export function acharProduto(infra: Infra, termo?: string): Product | undefined {
  if (!termo) return undefined;
  const t = norm(termo);
  return [...infra.db.products.values()].find((p) => norm(p.name).includes(t));
}

export function registrarConsumo(
  infra: Infra,
  args: { termo?: string; qtd: number },
): { ok: boolean; produto?: Product; restante?: number; alerta?: boolean; erro?: string } {
  const p = acharProduto(infra, args.termo);
  if (!p) return { ok: false, erro: `Não encontrei o produto "${args.termo ?? ''}".` };
  if (!args.qtd || args.qtd <= 0) return { ok: false, erro: 'Informe a quantidade consumida.' };
  if (args.qtd > p.stockQty) {
    return { ok: false, erro: `Estoque insuficiente de ${p.name} (há ${p.stockQty} ${p.unit}).` };
  }
  p.stockQty -= args.qtd;
  infra.db.products.set(p.id, p);
  return { ok: true, produto: p, restante: p.stockQty, alerta: p.stockQty <= p.minQty };
}

export function reporEstoque(
  infra: Infra,
  args: { termo?: string; qtd: number },
): { ok: boolean; produto?: Product; total?: number; erro?: string } {
  const p = acharProduto(infra, args.termo);
  if (!p) return { ok: false, erro: `Não encontrei o produto "${args.termo ?? ''}".` };
  if (!args.qtd || args.qtd <= 0) return { ok: false, erro: 'Informe a quantidade reposta.' };
  p.stockQty += args.qtd;
  infra.db.products.set(p.id, p);
  return { ok: true, produto: p, total: p.stockQty };
}
